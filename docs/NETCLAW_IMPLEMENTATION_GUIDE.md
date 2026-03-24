# NetClaw Implementation Guide for Convergence

**Quick Start:** Add NetClaw to enhance your network operations in 30 minutes

---

## Prerequisites

- Convergence stack running (`docker compose up -d`)
- Nautobot accessible with API token
- Network device SSH/SNMP access configured

---

## Step 1: Add NetClaw to Docker Compose

Add this service to your `docker-compose.yml`:

```yaml
# Add after the automation-agent service
netclaw:
  image: automateyournetwork/netclaw:latest
  container_name: convergence-netclaw
  ports:
    - "18789:18789"    # OpenClaw Gateway (API)
    - "3001:3000"     # NetClaw Visual HUD (Web UI)
  volumes:
    - netclaw-workspace:/app/workspace
    - ./config/netclaw:/app/config:ro
  environment:
    - OPENCLAW_MODE=gateway
    - NETCLAW_LAB_MODE=false
    # Nautobot Integration (your existing config)
    - NAUTOBOT_URL=${NAUTOBOT_URL}
    - NAUTOBOT_TOKEN=${NAUTOBOT_TOKEN}
    - NAUTOBOT_VERIFY_SSL=false
    # Convergence Services
    - VICTORIAMETRICS_URL=http://victoriametrics:8428
    - GRAFANA_URL=http://grafana:3000
    - LOKI_URL=http://loki:3100
    - PFSENSE_HOST=${PFSENSE_HOST}
    - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}
    # NetClaw Configuration
    - NETCLAW_DEVICE_DISCOVERY=nautobot
    - NETCLAW_SITE_FILTER=home-lab
    - NETCLAW_AUTO_HEALTH_CHECK=true
  networks:
    - convergence
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:18789/health"]
    interval: 30s
    timeout: 10s
    retries: 3
```

Add volume declaration:
```yaml
volumes:
  # ... existing volumes ...
  netclaw-workspace:
    name: convergence-netclaw-workspace
```

---

## Step 2: Create NetClaw Configuration

Create directory structure:
```bash
mkdir -p config/netclaw
```

Create `config/netclaw/openclaw.json`:
```json
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
            "NAUTOBOT_TOKEN": "${NAUTOBOT_TOKEN}"
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
```

---

## Step 3: Deploy and Initialize

```bash
# Deploy NetClaw
docker compose up -d netclaw

# Wait for healthy status
docker compose ps netclaw

# Initialize NetClaw workspace
docker compose exec netclaw openclaw onboard --skip-gateway
```

---

## Step 4: Configure Device Access

NetClaw needs SSH access to your network devices. Create `config/netclaw/devices.env`:

```bash
# Device Credentials (use your existing network credentials)
NETWORK_USERNAME=${NETWORK_USERNAME:-admin}
NETWORK_PASSWORD=${NETWORK_PASSWORD:-admin}

# SSH Keys (if using key-based auth)
SSH_PRIVATE_KEY_PATH=/app/secrets/id_rsa

# SNMP Community
SNMP_COMMUNITY=${SNMP_COMMUNITY:-public}
```

---

## Step 5: Sync Devices from Nautobot

```bash
# Generate device inventory from Nautobot
docker compose exec netclaw python3 scripts/nautobot_device_sync.py

# This creates config/netclaw/testbed.yaml with your devices
```

---

## Step 6: Test Core Functionality

### Health Check All Devices
```bash
curl -X POST http://localhost:18789/v1/agents/default/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Run health check on all devices",
    "stream": false
  }'
```

### Check Network Topology
```bash
curl -X POST http://localhost:18789/v1/agents/default/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Discover network topology via CDP/LLDP",
    "stream": false
  }'
```

### Audit Security Posture
```bash
curl -X POST http://localhost:18789/v1/agents/default/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Audit security configuration on all devices",
    "stream": false
  }'
```

---

## Step 7: Integrate with Existing Automation

### Discord Bot Enhancement

Add NetClaw commands to your existing Discord bot in `services/automation-agent/app/discord_bot.py`:

```python
# Add to existing command handlers
@bot.slash_command(name="netclaw", description="NetClaw network operations")
async def netclaw_command(interaction, action: str, target: str = None):
    """Execute NetClaw actions via Discord"""

    actions = {
        "health": f"Check health of {target or 'all devices'}",
        "troubleshoot": f"Troubleshoot connectivity to {target}",
        "config": f"Show running config for {target}",
        "topology": "Generate network topology diagram"
    }

    if action not in actions:
        await interaction.response.send_message(f"Unknown action: {action}")
        return

    # Call NetClaw API
    async with aiohttp.ClientSession() as session:
        payload = {"message": actions[action], "stream": False}
        async with session.post("http://netclaw:18789/v1/agents/default/chat",
                               json=payload) as response:
            result = await response.json()

    await interaction.response.send_message(f"NetClaw: {result['response']}")
```

### Grafana Integration

Create a new dashboard at `dashboards/netclaw/netclaw-overview.json`:

```json
{
  "dashboard": {
    "title": "NetClaw Network Operations",
    "panels": [
      {
        "title": "Device Health Status",
        "type": "table",
        "targets": [
          {
            "expr": "netclaw_device_health_status",
            "legendFormat": "{{device}}"
          }
        ]
      },
      {
        "title": "Active Troubleshooting Sessions",
        "type": "stat",
        "targets": [
          {
            "expr": "netclaw_active_sessions",
            "legendFormat": "Active Sessions"
          }
        ]
      }
    ]
  }
}
```

---

## Step 8: Advanced Configuration

### Custom Skills for Convergence

Create `config/netclaw/skills/convergence-integration.skill`:

```yaml
name: convergence-integration
description: "Custom skills for Convergence platform integration"

skills:
  - name: convergence-threat-analysis
    description: "Analyze threats using Convergence threat-intel service"
    triggers:
      - webhook: threat-intel-service
    actions:
      - http: GET http://threat-intel:8000/api/infinity/blocked_ips
      - pyats-security: audit_firewall_rules
      - nautobot-sot: check_ipam_compliance

  - name: convergence-config-drift
    description: "Detect configuration drift against Nautobot"
    triggers:
      - cron: "0 */4 * * *"
    actions:
      - nautobot-sot: get_device_configs
      - pyats: collect_running_configs
      - diff: compare_configs
      - alert: send_drift_notification
```

### Automated Workflows

Set up cron jobs in NetClaw for regular tasks:

```bash
# Add to netclaw environment
NETCLAW_AUTO_WORKFLOWS='
health-check: "0 */2 * * *"    # Every 2 hours
topology-scan: "0 6 * * *"    # Daily at 6 AM
security-audit: "0 2 * * 1"   # Weekly on Monday
config-backup: "0 3 * * *"    # Daily backup
'
```

---

## Step 9: Monitoring and Alerting

### NetClaw Health Monitoring

Add to your existing `config/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  # ... existing configs ...
  - job_name: 'netclaw'
    static_configs:
      - targets: ['netclaw:18789']
    metrics_path: '/metrics'
```

### Alert Rules

Add to `config/loki/rules/fake/firewall_alerts.yaml`:

```yaml
groups:
  - name: netclaw_alerts
    rules:
      - alert: NetClawDeviceUnreachable
        expr: netclaw_device_reachability == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Device unreachable"
          description: "{{ $labels.device }} is not responding to health checks"

      - alert: NetClawConfigDrift
        expr: netclaw_config_drift_detected > 0
        labels:
          severity: warning
        annotations:
          summary: "Configuration drift detected"
          description: "Device {{ $labels.device }} config differs from Nautobot"
```

---

## Step 10: Production Deployment

### Security Hardening

```bash
# Enable authentication
NETCLAW_AUTH_MODE=password
NETCLAW_ADMIN_PASSWORD=your-secure-password

# Restrict MCP server access
NETCLAW_MCP_RESTRICTED_SERVERS=pyats-mcp,pfsense-mcp

# Enable audit logging
NETCLAW_AUDIT_LOG_ENABLED=true
NETCLAW_AUDIT_LOG_PATH=/app/audit/netclaw.log
```

### Backup Strategy

```bash
# Add to your backup script
docker run --rm -v convergence-netclaw-workspace:/data \
  -v /backup/netclaw:/backup \
  alpine tar czf /backup/netclaw-workspace-$(date +%Y%m%d).tar.gz -C /data .
```

### Scaling Considerations

For larger networks:
- Increase NetClaw container resources (CPU: 2, Memory: 4GB)
- Enable NetClaw clustering for high availability
- Configure external PostgreSQL for workspace persistence
- Set up NetClaw federation for multi-site deployments

---

## Troubleshooting

### Common Issues

**NetClaw can't reach Nautobot:**
```bash
# Check network connectivity
docker compose exec netclaw curl -f http://nautobot:8000/api/

# Verify environment variables
docker compose exec netclaw env | grep NAUTOBOT
```

**Device access fails:**
```bash
# Test SSH connectivity
docker compose exec netclaw ssh -o StrictHostKeyChecking=no admin@device-ip "show version"

# Check credentials
docker compose exec netclaw cat /app/config/devices.env
```

**MCP servers not loading:**
```bash
# Check MCP server logs
docker compose logs netclaw | grep mcp

# Validate configuration
docker compose exec netclaw openclaw doctor
```

### Logs and Debugging

```bash
# View NetClaw logs
docker compose logs -f netclaw

# Access NetClaw debug interface
open http://localhost:3001

# Check workspace files
docker compose exec netclaw ls -la /app/workspace/
```

---

## Next Steps

1. **Monitor Performance:** Track NetClaw's impact on your network and systems
2. **Train Team:** Provide NetClaw usage training for network operators
3. **Expand Skills:** Develop custom skills for your specific network workflows
4. **Integrate More:** Connect NetClaw with additional tools (ServiceNow, GitHub, etc.)
5. **Automate More:** Create automated remediation workflows for common issues

---

## Support Resources

- **NetClaw Documentation:** https://github.com/automateyournetwork/netclaw
- **OpenClaw Gateway:** https://docs.openclaw.ai/
- **MCP Servers:** Review available servers in NetClaw's MCP directory
- **Community:** Join NetClaw Discord for support and best practices

This implementation provides immediate value while setting up a foundation for advanced network automation capabilities.