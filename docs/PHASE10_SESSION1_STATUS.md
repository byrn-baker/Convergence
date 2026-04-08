# Phase 10: NetClaw Migration — Session 1 Status

**Date:** 2026-04-05
**Status:** Session 1 Complete — pfsense-mcp + convergence-mcp working, skills created

---

## What Was Accomplished

### Phase 9 Implementation (completed this session)

**Phase 9A: net-ops-team → NetClaw (REST proxy)**
- Created `mcp-servers/netclaw-proxy/netclaw_proxy.py` — HTTP→CLI bridge sidecar (port 18790)
- Created `services/net-ops-team/app/tools/netclaw.py` — async httpx client for the proxy
- Added `request_netclaw_investigation` tool to security expert agent
- Added `lookup_nautobot_device` tool to security expert (Nautobot validation before flagging internal hosts)
- Updated security expert system prompt with: Nautobot validation rules, subnet blocking protocol, noise reduction rules
- Added 30-minute dedup to Discord notifications in `main.py`
- **Result:** Findings dropped from 11-23 per cycle to 6, block submissions from 4/cycle to 0

**Phase 9B: NetClaw → Convergence (MCP server)**
- Created `mcp-servers/convergence-mcp/convergence_mcp_server.py` — 10 tools (FastMCP stdio)
- Tools: get_threat_intel_report, get_blocked_ips, get_outbound_suspicious, submit_block_action, get_pending_approvals, approve_block, get_netops_report, query_metrics, query_logs, investigate_host
- Registered via `openclaw mcp set` — tested and working

### Phase 10 Session 1: pfsense-mcp + Skills

**pfsense-mcp (NEW MCP server — upstream-ready for netclaw repo)**
- Location: `netclaw/mcp-servers/pfsense-mcp/pfsense_mcp_server.py`
- 8 read-only tools via XML-RPC exec_php:
  - `pfsense_get_dhcp_leases` — IP, MAC, hostname, state
  - `pfsense_get_arp_table` — IP → MAC → interface
  - `pfsense_get_system_info` — version, hostname, uptime, CPU, memory, disk
  - `pfsense_get_interfaces` — interface status, IPs, MAC, media, bytes
  - `pfsense_get_firewall_aliases` — alias names and address lists
  - `pfsense_get_firewall_rules` — rules by interface
  - `pfsense_get_gateway_status` — RTT, loss, status
  - `pfsense_get_states_summary` — state table total + top 10 sources
- **Tested and working** — NetClaw queried system info, DHCP leases, gateway status successfully

**Two upstream skills created:**
- `netclaw/workspace/skills/pfsense-firewall-ops/SKILL.md` — pfSense management workflows (device identification, gateway health, rule audit, state analysis, network discovery)
- `netclaw/workspace/skills/synology-nas-monitor/SKILL.md` — Synology SNMP health checks (temperature, power, disk, RAID, storage utilization, uptime)

### Infrastructure Changes

**docker-compose.yml:**
- NetClaw container: added port 18790 (REST proxy), volume mounts for convergence-mcp and netclaw-proxy
- Added PFSENSE_XMLRPC_USER/PASS env vars to netclaw container

**docker/netclaw.Dockerfile:**
- Added `python3-venv` to apt packages
- Added `rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED` for pip compatibility
- Made `install.sh` non-fatal (`|| true`) — pre-existing packet-buddy-mcp failure
- Added `pip3 install 'mcp[cli]>=1.0.0' 'httpx>=0.27.0'` for MCP Python SDK
- Changed CMD to start REST proxy sidecar alongside gateway

**config/netclaw/openclaw.json:**
- MCP servers registered via `openclaw mcp set` (NOT hand-edited JSON)
- Both pfsense-mcp and convergence-mcp registered with credentials

**Key Discovery — OpenClaw MCP Registration:**
- OpenClaw 2026.4.x does NOT accept `mcpServers` as a hand-edited key in openclaw.json
- Must use `openclaw mcp set <name> '<json>'` CLI command
- The submodule's `config/openclaw.json` uses an older object format; the deployment config uses a managed array format
- Credentials must be literal values (not `${VAR}` references) when set via CLI

---

## What Remains (Sessions 4-6)

### ~~Session 2: Convergence-specific Skills~~ ✅ COMPLETE
- See `docs/PHASE10_SESSION2_3_STATUS.md`
- `convergence-noc-watch/SKILL.md`, `convergence-security-monitor/SKILL.md`, `convergence-interface-reconciler/SKILL.md` created in `config/netclaw/workspace/skills/`

### ~~Session 3: convergence-scheduler Service~~ ✅ COMPLETE
- See `docs/PHASE10_SESSION2_3_STATUS.md`
- `services/convergence-scheduler/` built — FastAPI + APScheduler + Discord webhook
- Added to `docker-compose.yml` on port 8004

### Session 4: Cutover
- ~~Stop net-ops-team, start convergence-scheduler~~ ✅ COMPLETE
- ~~Monitor 24 hours~~ Monitoring in progress
- ~~Remove net-ops-team from docker-compose.yml~~ ✅ COMPLETE

### Session 5: Upstream Contribution
- PR pfsense-mcp to automateyournetwork/netclaw
- PR pfsense-firewall-ops skill
- PR synology-nas-monitor skill

---

## Files Created/Modified

### New Files
| File | Purpose |
|------|---------|
| `mcp-servers/netclaw-proxy/netclaw_proxy.py` | REST proxy sidecar (HTTP→CLI bridge) |
| `mcp-servers/convergence-mcp/convergence_mcp_server.py` | Convergence platform MCP server (10 tools) |
| `mcp-servers/convergence-mcp/requirements.txt` | Python deps |
| `mcp-servers/convergence-mcp/README.md` | Documentation |
| `netclaw/mcp-servers/pfsense-mcp/pfsense_mcp_server.py` | pfSense MCP server (8 tools) |
| `netclaw/mcp-servers/pfsense-mcp/requirements.txt` | Python deps |
| `netclaw/mcp-servers/pfsense-mcp/README.md` | Documentation |
| `netclaw/workspace/skills/pfsense-firewall-ops/SKILL.md` | pfSense skill |
| `netclaw/workspace/skills/synology-nas-monitor/SKILL.md` | Synology NAS skill |
| `services/net-ops-team/app/tools/netclaw.py` | NetClaw HTTP client |
| `docs/PHASE10_NETCLAW_MIGRATION.md` | Full migration plan |

### Modified Files
| File | Change |
|------|--------|
| `services/net-ops-team/app/team/security_expert.py` | Added lookup_nautobot_device + request_netclaw_investigation tools, Nautobot validation rules, subnet blocking, noise reduction |
| `services/net-ops-team/app/main.py` | Added 30-min Discord alert dedup |
| `docker-compose.yml` | NetClaw ports, volumes, env vars |
| `docker/netclaw.Dockerfile` | pip fix, MCP SDK install, proxy sidecar CMD |
| `netclaw/config/openclaw.json` | Added pfsense-mcp + convergence-mcp (submodule config) |
| `config/netclaw/openclaw.json` | MCP servers registered via CLI (managed by openclaw) |

---

## Current Container Status

- **net-ops-team**: Running with improved security expert (Nautobot validation, dedup)
- **netclaw**: Running with pfsense-mcp + convergence-mcp + REST proxy sidecar
- **threat-intel**: Unchanged, running
- **automation-agent**: Unchanged, running
- All other infrastructure: Unchanged, running


---

## Critical Finding: MCP Server Registration Gap

The install script (`scripts/install.sh`) has 53 steps and installs 36 MCP servers on disk. However:

1. **`openclaw onboard` (Step 3) never runs** — the Dockerfile runs `install.sh || true` which skips the interactive onboard step that registers MCP servers with the gateway
2. **Only 2 of 36 MCP servers are registered** — pfsense-mcp and convergence-mcp (manually added via `openclaw mcp set`)
3. **The pyATS testbed points to sandbox devices** (10.10.20.x), not the actual network (192.168.3.2/3)
4. **Grafana MCP (75 tools), Prometheus MCP, Nautobot MCP, nmap MCP, GAIT MCP** — all installed on disk but unregistered and unused

### MCP Servers That MUST Be Registered for Session 2

The Convergence-specific skills need these MCP servers working:

| MCP Server | Needed By | Status |
|---|---|---|
| `pfsense-mcp` | security-monitor, interface-reconciler | ✅ Registered, tested |
| `convergence-mcp` | security-monitor, noc-watch | ✅ Registered, tested |
| `grafana-mcp` (mcp-grafana) | noc-watch, security-monitor (Loki LogQL) | ❌ Installed, NOT registered |
| `prometheus-mcp` | noc-watch, nas-monitor | ❌ Installed, NOT registered |
| `nautobot-mcp` (mcp-nautobot) | interface-reconciler, security-monitor | ❌ Installed, NOT registered |
| `pyats-mcp` (pyATS_MCP) | interface-reconciler (show commands) | ❌ Installed, NOT registered, testbed wrong |
| `nmap-mcp` | security-monitor (service detection) | ❌ Installed, NOT registered |
| `gait-mcp` | all skills (audit trail) | ❌ Installed, NOT registered |

### Action Required for Session 2

Before writing the Convergence-specific skills:

1. Register the required MCP servers via `openclaw mcp set`
2. Update the pyATS testbed with actual device credentials (HomeSwitch01/02)
3. Test each MCP server individually
4. Consider running `openclaw onboard` or creating a setup script that registers all needed servers

### Testbed Update Needed

Current testbed: sandbox devices at 10.10.20.x
Required testbed:
```yaml
devices:
  HomeSwitch01:
    os: iosxe
    platform: cat3850
    connections:
      cli:
        protocol: ssh
        ip: 192.168.3.2
        port: 22
    credentials:
      default:
        username: ${SWITCH_SSH_USER}
        password: ${SWITCH_SSH_PASS}
      enable:
        password: ${SWITCH_SSH_ENABLE_PASS}
  HomeSwitch02:
    os: iosxe
    platform: cat3850
    connections:
      cli:
        protocol: ssh
        ip: 192.168.3.3
        port: 22
    credentials:
      default:
        username: ${SWITCH_SSH_USER}
        password: ${SWITCH_SSH_PASS}
      enable:
        password: ${SWITCH_SSH_ENABLE_PASS}
```
