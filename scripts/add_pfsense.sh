#!/bin/bash
# Quick setup script for pfSense monitoring
# Usage: ./scripts/add_pfsense.sh

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env file if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "📋 Loading environment from .env file..."
    set -a  # Automatically export all variables
    source "$PROJECT_ROOT/.env"
    set +a
    echo "✅ Environment loaded"
    echo ""
else
    echo "⚠️  No .env file found at $PROJECT_ROOT/.env"
    echo "Please create one from .env.example"
    exit 1
fi

PFSENSE_IP="${PFSENSE_IP:-192.168.100.1}"
DOCKER_HOST_IP=$(hostname -I | awk '{print $1}')

echo "🔥 pfSense Monitoring Setup Script"
echo "===================================="
echo ""
echo "pfSense IP: $PFSENSE_IP"
echo "Docker Host IP: $DOCKER_HOST_IP"
echo "Nautobot URL: $NAUTOBOT_URL"
echo ""

# Check if Nautobot credentials are set
if [ -z "$NAUTOBOT_URL" ] || [ -z "$NAUTOBOT_TOKEN" ]; then
    echo "⚠️  ERROR: Nautobot credentials not set in .env file"
    echo "Please update .env with:"
    echo "  NAUTOBOT_URL=https://192.168.100.36"
    echo "  NAUTOBOT_TOKEN=your-token-here"
    exit 1
fi

echo "Step 1: Check pfSense in Nautobot"
echo "-----------------------------------"
if python3 scripts/nautobot_device_discovery.py --list-devices | grep -qi "pfsense"; then
    echo "✅ pfSense device found in Nautobot"
else
    echo "❌ pfSense NOT found in Nautobot"
    echo ""
    echo "Please add pfSense to Nautobot first:"
    echo "1. Login to Nautobot: $NAUTOBOT_URL"
    echo "2. Navigate to: Devices → Add Device"
    echo "3. Configure:"
    echo "   - Name: pfSense-FW01"
    echo "   - Device Type: pfSense Firewall"
    echo "   - Manufacturer: Netgate (or pfSense)"
    echo "   - Role: firewall"
    echo "   - Site: Your site"
    echo "   - Primary IPv4: $PFSENSE_IP/32"
    echo "   - Status: Active"
    echo ""
    echo "After adding, run this script again."
    exit 1
fi

echo ""
echo "Step 2: Test pfSense SNMP"
echo "------------------------"
if command -v snmpwalk &> /dev/null; then
    if snmpwalk -v2c -c "${SNMP_COMMUNITY:-public}" -t 2 -r 1 "$PFSENSE_IP" system 2>&1 | grep -q "iso"; then
        echo "✅ SNMP responding on $PFSENSE_IP"
    else
        echo "⚠️  SNMP not responding. Please check:"
        echo "   - pfSense: Services → SNMP → Enable SNMP daemon"
        echo "   - Community string: ${SNMP_COMMUNITY:-public}"
        echo "   - Firewall allows $DOCKER_HOST_IP → $PFSENSE_IP:161/udp"
    fi
else
    echo "⚠️  snmpwalk not installed, skipping SNMP test"
    echo "   Install with: sudo apt-get install snmp"
fi

echo ""
echo "Step 3: Test Syslog Receiver"
echo "----------------------------"
if docker exec convergence-otel-collector netstat -uln 2>/dev/null | grep -q ":514 "; then
    echo "✅ Syslog receiver listening on port 514"
else
    echo "⚠️  Syslog receiver not listening"
    echo "   Check OTEL Collector logs: docker logs convergence-otel-collector"
fi

echo ""
echo "Step 4: Generate OTEL Configuration"
echo "-----------------------------------"
python3 scripts/nautobot_device_discovery.py --generate-config > /tmp/pfsense_otel_config.yaml
if grep -qi "pfsense" /tmp/pfsense_otel_config.yaml; then
    echo "✅ Configuration generated: /tmp/pfsense_otel_config.yaml"
    echo ""
    echo "📝 Preview of pfSense configuration:"
    echo "-----------------------------------"
    grep -A50 "pfsense\|pfSense" /tmp/pfsense_otel_config.yaml | head -60
else
    echo "⚠️  No pfSense configuration generated"
    echo "   Verify pfSense device exists in Nautobot"
    exit 1
fi

echo ""
echo "Step 5: Manual Actions Required"
echo "-------------------------------"
echo ""
echo "✅ Checklist:"
echo "  [ ] 1. On pfSense: Enable SNMP (Services → SNMP)"
echo "  [ ] 2. On pfSense: Configure Syslog to send to $DOCKER_HOST_IP:514"
echo "  [ ] 3. Add generated config to config/otel-collector/config.yaml"
echo "  [ ] 4. Add log parsing processors (see docs/PFSENSE_INTEGRATION.md)"
echo "  [ ] 5. Restart OTEL Collector: docker restart convergence-otel-collector"
echo "  [ ] 6. Verify metrics: curl http://localhost:8428/api/v1/label/device_name/values"
echo ""
echo "📖 Full documentation: docs/PFSENSE_INTEGRATION.md"
echo ""
echo "🚀 Quick Test After Setup:"
echo "   # Check pfSense metrics"
echo "   curl -s 'http://localhost:8428/api/v1/query?query=interface_in_octets_bytes_total{device_name=~\".*pfSense.*\"}'"
echo ""
echo "   # Generate test firewall block (from pfSense shell)"
echo "   ping -c 1 1.1.1.1  # If blocked, will appear in logs"
echo ""
