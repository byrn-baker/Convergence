#!/bin/bash
# NetClaw Setup Script for Convergence
# This script adds NetClaw to your existing Convergence deployment

set -e

echo "🦞 NetClaw Setup for Convergence"
echo "================================="

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ] || [ ! -d "config" ]; then
    echo "❌ Error: Please run this script from the Convergence project root directory"
    exit 1
fi

# Check if Convergence is running
echo "📋 Checking Convergence status..."
if ! docker compose ps | grep -q "Up"; then
    echo "⚠️  Warning: Convergence stack doesn't appear to be running"
    echo "   Start it first with: docker compose up -d"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "✅ Convergence stack detected"

# Create NetClaw configuration directory
echo "📁 Creating NetClaw configuration..."
mkdir -p config/netclaw

# Create OpenClaw gateway configuration
cat > config/netclaw/openclaw.json << 'EOF'
{
  "gateway": {
    "bind": "0.0.0.0",
    "port": 18789,
    "auth": {
      "mode": "none"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-6",
      "workspace": "/app/workspace",
      "mcpServers": {
        "nautobot-mcp": {
          "command": "python3",
          "args": ["/app/mcp-servers/nautobot-mcp/main.py"],
          "env": {
            "NAUTOBOT_URL": "http://host.docker.internal:8000",
            "NAUTOBOT_TOKEN": "${NAUTOBOT_TOKEN}",
            "NAUTOBOT_VERIFY_SSL": "false"
          }
        },
        "grafana-mcp": {
          "command": "uvx",
          "args": ["mcp-grafana"],
          "env": {
            "GRAFANA_URL": "http://host.docker.internal:3000"
          }
        },
        "prometheus-mcp": {
          "command": "python3",
          "args": ["/app/mcp-servers/prometheus-mcp/main.py"],
          "env": {
            "PROMETHEUS_URL": "http://host.docker.internal:8428"
          }
        }
      }
    }
  }
}
EOF

echo "✅ Created OpenClaw configuration"

# Create NetClaw environment file
cat > config/netclaw/netclaw.env << 'EOF'
# NetClaw Configuration
OPENCLAW_MODE=gateway
NETCLAW_LAB_MODE=false
NETCLAW_DEVICE_DISCOVERY=nautobot
NETCLAW_AUTO_HEALTH_CHECK=true

# Nautobot Integration
NAUTOBOT_URL=http://host.docker.internal:8000
NAUTOBOT_VERIFY_SSL=false

# Convergence Services
VICTORIAMETRICS_URL=http://host.docker.internal:8428
GRAFANA_URL=http://host.docker.internal:3000
LOKI_URL=http://host.docker.internal:3100

# Network Credentials (inherited from Convergence)
NETWORK_USERNAME=${NETWORK_USERNAME}
SNMP_COMMUNITY=${SNMP_COMMUNITY}
EOF

echo "✅ Created NetClaw environment configuration"

# Backup original docker-compose.yml
cp docker-compose.yml docker-compose.yml.backup
echo "💾 Backed up original docker-compose.yml"

# Add NetClaw service to docker-compose.yml
# Find the line with automation-agent service and add NetClaw after it
sed -i '/automation-agent:/a \
  # NetClaw - AI Network Engineering Agent\
  netclaw:\
    image: automateyournetwork/netclaw:latest\
    container_name: convergence-netclaw\
    ports:\
      - "18789:18789"    # OpenClaw Gateway\
      - "3001:3000"     # NetClaw Visual HUD\
    volumes:\
      - netclaw-workspace:/app/workspace\
      - ./config/netclaw:/app/config:ro\
    environment:\
      - OPENCLAW_MODE=gateway\
      - NETCLAW_LAB_MODE=false\
      - NAUTOBOT_URL=http://host.docker.internal:8000\
      - NAUTOBOT_TOKEN=${NAUTOBOT_TOKEN}\
      - NAUTOBOT_VERIFY_SSL=false\
      - VICTORIAMETRICS_URL=http://host.docker.internal:8428\
      - GRAFANA_URL=http://host.docker.internal:3000\
      - LOKI_URL=http://host.docker.internal:3100\
      - PFSENSE_HOST=${PFSENSE_HOST}\
      - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}\
      - NETWORK_USERNAME=${NETWORK_USERNAME}\
      - SNMP_COMMUNITY=${SNMP_COMMUNITY}\
    networks:\
      - convergence\
    restart: unless-stopped\
    healthcheck:\
      test: ["CMD", "curl", "-f", "http://localhost:18789/health"]\
      interval: 30s\
      timeout: 10s\
      retries: 3\
' docker-compose.yml

echo "✅ Added NetClaw service to docker-compose.yml"

# Add NetClaw volume to volumes section
# Find the volumes section and add netclaw-workspace
sed -i '/volumes:/a \
  netclaw-workspace:\
    name: convergence-netclaw-workspace\
' docker-compose.yml

echo "✅ Added NetClaw volume to docker-compose.yml"

# Create Nautobot device sync script
cat > scripts/netclaw_nautobot_sync.py << 'EOF'
#!/usr/bin/env python3
"""
NetClaw Device Synchronization with Nautobot

Generates NetClaw testbed.yaml from Nautobot device inventory
"""

import os
import sys
import json
import requests
from pathlib import Path
import yaml

# Load environment variables from .env if it exists
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                os.environ[key] = value

# Configuration
NAUTOBOT_URL = os.getenv('NAUTOBOT_URL', 'http://nautobot:8000')
NAUTOBOT_TOKEN = os.getenv('NAUTOBOT_TOKEN', '')
NAUTOBOT_VERIFY_SSL = os.getenv('NAUTOBOT_VERIFY_SSL', 'false').lower() == 'true'

def get_nautobot_devices():
    """Fetch devices from Nautobot GraphQL API"""
    query = """
    query {
      devices {
        name
        primary_ip4 {
          address
        }
        device_type {
          model
          manufacturer {
            name
          }
        }
        platform {
          name
        }
        site {
          name
        }
        status
        custom_fields
      }
    }
    """

    headers = {
        'Authorization': f'Token {NAUTOBOT_TOKEN}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(
            f"{NAUTOBOT_URL}/graphql/",
            json={'query': query},
            headers=headers,
            verify=NAUTOBOT_VERIFY_SSL,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        return data['data']['devices']

    except Exception as e:
        print(f"❌ Error fetching devices from Nautobot: {e}")
        return []

def generate_testbed_yaml(devices):
    """Generate NetClaw testbed.yaml from Nautobot devices"""

    testbed = {
        'devices': {},
        'topology': {}
    }

    for device in devices:
        if device['status'] != 'active':
            continue

        device_name = device['name']
        ip_address = device['primary_ip4']['address'].split('/')[0] if device['primary_ip4'] else None

        if not ip_address:
            print(f"⚠️  Skipping {device_name}: no IP address")
            continue

        # Map Nautobot platform to pyATS platform
        platform_mapping = {
            'cisco_ios': 'ios',
            'cisco_nxos': 'nxos',
            'cisco_iosxe': 'iosxe',
            'juniper_junos': 'junos',
            'arista_eos': 'eos'
        }

        platform = device.get('platform', {}).get('name', '').lower()
        pyats_platform = platform_mapping.get(platform, 'ios')

        testbed['devices'][device_name] = {
            'alias': device_name,
            'type': 'router',  # Default to router, can be customized
            'os': pyats_platform,
            'platform': pyats_platform,
            'credentials': {
                'default': {
                    'username': os.getenv('NETWORK_USERNAME', 'admin'),
                    'password': os.getenv('NETWORK_PASSWORD', 'admin')
                }
            },
            'connections': {
                'cli': {
                    'protocol': 'ssh',
                    'ip': ip_address,
                    'port': 22
                },
                'snmp': {
                    'protocol': 'snmp',
                    'ip': ip_address,
                    'port': 161,
                    'community': os.getenv('SNMP_COMMUNITY', 'public')
                }
            }
        }

        print(f"✅ Added device: {device_name} ({ip_address})")

    return testbed

def main():
    print("🔄 Syncing NetClaw devices from Nautobot...")

    if not NAUTOBOT_TOKEN:
        print("❌ Error: NAUTOBOT_TOKEN not set")
        sys.exit(1)

    devices = get_nautobot_devices()

    if not devices:
        print("❌ No devices found in Nautobot")
        sys.exit(1)

    print(f"📋 Found {len(devices)} devices in Nautobot")

    testbed = generate_testbed_yaml(devices)

    # Write testbed.yaml
    config_dir = Path(__file__).parent.parent / 'config' / 'netclaw'
    config_dir.mkdir(parents=True, exist_ok=True)

    testbed_file = config_dir / 'testbed.yaml'
    with open(testbed_file, 'w') as f:
        yaml.dump(testbed, f, default_flow_style=False)

    print(f"✅ Generated NetClaw testbed: {testbed_file}")
    print(f"📊 Configured {len(testbed['devices'])} devices")

if __name__ == '__main__':
    main()
EOF

chmod +x scripts/netclaw_nautobot_sync.py
echo "✅ Created NetClaw Nautobot sync script"

echo ""
echo "🎉 NetClaw setup complete!"
echo ""
echo "Next steps:"
echo "1. Start NetClaw: docker compose up -d netclaw"
echo "2. Sync devices: python3 scripts/netclaw_nautobot_sync.py"
echo "3. Test connection: curl http://localhost:18789/health"
echo "4. Access UI: http://localhost:3001"
echo ""
echo "For full documentation, see:"
echo "- docs/NETCLAW_INTEGRATION_PLAN.md"
echo "- docs/NETCLAW_IMPLEMENTATION_GUIDE.md"
echo ""
echo "🦞 Happy networking with NetClaw!"