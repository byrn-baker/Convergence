# Convergence MCP Server

MCP server that exposes the Convergence security platform to NetClaw via stdio JSON-RPC.

## Tools

| Tool | Description |
|------|-------------|
| `get_threat_intel_report` | Full threat intel report with scored IPs |
| `get_blocked_ips` | Top blocked IPs with threat scores |
| `get_outbound_suspicious` | Suspicious outbound destinations |
| `submit_block_action` | Submit IP for blocking via automation pipeline |
| `get_pending_approvals` | List pending block actions |
| `approve_block` | Approve a pending block action |
| `get_netops_report` | Latest NET-OPS team findings |
| `query_metrics` | PromQL query against VictoriaMetrics |
| `query_logs` | LogQL query against Loki |
| `investigate_host` | DHCP/ARP/Nautobot lookup for an internal IP |

## Setup

Mounted into the NetClaw container and registered in `openclaw.json`:

```json
{
  "mcpServers": {
    "convergence-mcp": {
      "command": "python3",
      "args": ["-u", "/app/mcp-servers/convergence-mcp/convergence_mcp_server.py"]
    }
  }
}
```

## Environment Variables

- `THREAT_INTEL_URL` — threat-intel service (default: `http://threat-intel:8000`)
- `AUTOMATION_AGENT_URL` — automation agent (default: `http://automation-agent:8000`)
- `NET_OPS_TEAM_URL` — net-ops-team service (default: `http://net-ops-team:8000`)
- `VICTORIAMETRICS_URL` — VictoriaMetrics (default: `http://victoriametrics:8428`)
- `LOKI_URL` — Loki (default: `http://loki:3100`)
- `PFSENSE_HOST` — pfSense hostname for XML-RPC
- `PFSENSE_XMLRPC_USER` / `PFSENSE_XMLRPC_PASS` — pfSense credentials
- `NAUTOBOT_URL` / `NAUTOBOT_TOKEN` — Nautobot API access
