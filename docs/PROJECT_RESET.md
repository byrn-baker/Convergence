# Project Reset: Getting Convergence + NetClaw On Track

**Date:** 2026-04-05
**Context:** End of Phase 9/10 Session 1. Stepping back to assess the right path forward.

---

## The Honest Assessment

We've been building Convergence backwards. We built custom Python agents that reimplemented what NetClaw already does, then spent Phase 9 building bridges between the two systems, then realized the agents should have been NetClaw skills all along. Now we're in Phase 10 trying to migrate — but the NetClaw deployment itself is broken.

**The core problem:** NetClaw was deployed as a Docker container, not as a properly onboarded network engineering workstation. The Dockerfile runs `install.sh || true` (which silently fails on several steps), never runs `openclaw onboard`, and the result is:

- **36 MCP servers installed on disk, only 2 registered** (pfsense-mcp and convergence-mcp, manually added today)
- **pyATS installed but testbed points to Cisco sandbox devices** (10.10.20.x), not the actual network
- **Grafana MCP (75 tools), Prometheus MCP, Nautobot MCP, pyATS MCP, nmap MCP, GAIT MCP** — all sitting on disk, unregistered, unused
- **124 skills in the workspace** but no scheduled monitoring invokes them
- **The net-ops-team service** reimplements what these unregistered MCP servers already do

We need to stop adding features and fix the foundation.

---

## What's Actually Working Right Now

| Component | Status | Notes |
|---|---|---|
| OTEL Collector | ✅ Working | SNMP, syslog, NetFlow ingestion |
| VictoriaMetrics | ✅ Working | Metrics storage, 90d retention |
| Loki | ✅ Working | Log aggregation |
| Grafana | ✅ Working | 9 dashboards |
| threat-intel service | ✅ Working | IP enrichment + AI narratives |
| automation-agent | ✅ Working | pfSense blocking with GAIT audit |
| net-ops-team | ⚠️ Working but wrong | Should be NetClaw skills, not separate agents |
| NetClaw gateway | ✅ Working | OpenClaw gateway + REST proxy sidecar |
| pfsense-mcp | ✅ Working | 8 tools, tested today |
| convergence-mcp | ✅ Working | 10 tools, tested today |
| Grafana MCP | ❌ Not registered | 75 tools sitting on disk |
| Prometheus MCP | ❌ Not registered | Installed but not configured |
| Nautobot MCP | ❌ Not registered | Installed but not configured |
| pyATS MCP | ❌ Not registered | Installed, testbed wrong |
| nmap MCP | ❌ Not registered | Installed but not configured |
| GAIT MCP | ❌ Not registered | Installed but not configured |
| All other MCP servers | ❌ Not registered | 30+ servers on disk, unused |

---

## The Right Path Forward

### Step 1: Fix the NetClaw Deployment (MUST DO FIRST)

Before writing any more skills or agents, NetClaw needs to be properly set up:

1. **Register the MCP servers that matter for this network:**

   ```bash
   # These are the ones the Convergence skills will actually use
   openclaw mcp set grafana-mcp '...'        # 75 tools: PromQL, LogQL, dashboards, alerts
   openclaw mcp set prometheus-mcp '...'      # Metric queries, discovery
   openclaw mcp set nautobot-mcp '...'        # Device/interface/IPAM lookups
   openclaw mcp set pyats-mcp '...'           # SSH, show commands, Genie parsers
   openclaw mcp set nmap-mcp '...'            # Network scanning, service detection
   openclaw mcp set gait-mcp '...'            # Audit trail
   # Already registered:
   # pfsense-mcp ✅
   # convergence-mcp ✅
   ```

2. **Update the pyATS testbed** with actual devices:
   - HomeSwitch01 (192.168.3.2) — Cisco WS-C3850-48P
   - HomeSwitch02 (192.168.3.3) — Cisco WS-C3850-48P
   - Credentials from SWITCH_SSH_USER/PASS/ENABLE_PASS env vars

3. **Update TOOLS.md** with the actual network:
   - Device map (switches, firewall, NAS devices, IPs)
   - Subnet layout (192.168.1.0/24 LAN, 192.168.3.0/24 mgmt, 192.168.100.0/24 servers)
   - Grafana URL, VictoriaMetrics URL, Loki URL, Nautobot URL
   - pfSense host and port

4. **Test each MCP server individually** before building skills on top of them:
   ```bash
   openclaw agent --message "Use grafana-mcp to list available dashboards"
   openclaw agent --message "Use prometheus-mcp to query system_uptime_seconds"
   openclaw agent --message "Use nautobot-mcp to list all devices"
   openclaw agent --message "Use pyats-mcp to run 'show version' on HomeSwitch01"
   ```

### Step 2: Write the Convergence Skills

Once the MCP servers are working, write three deployment-specific skills:

- `convergence-noc-watch` — uses grafana-mcp + prometheus-mcp + nautobot-mcp
- `convergence-security-monitor` — uses grafana-mcp + convergence-mcp + nautobot-mcp + pfsense-mcp
- `convergence-interface-reconciler` — uses pyats-mcp + nautobot-mcp + pfsense-mcp

These are SKILL.md files — no Python code. They describe workflows that NetClaw executes using its existing MCP tools.

### Step 3: Build the Scheduler

A lightweight service (~100 lines) that:
- Runs on a cron schedule (every 10 minutes)
- Sends prompts to NetClaw via the REST proxy
- Parses responses for findings
- Posts to Discord

No LLM calls, no tool definitions, no system prompts. Just cron + HTTP + webhook.

### Step 4: Retire net-ops-team

Stop the container. Remove from docker-compose. The ~3,000 lines of agent code, tool wrappers, and LLM client are replaced by skill documents and MCP servers.

### Step 5: Contribute Upstream

PR to automateyournetwork/netclaw:
- `mcp-servers/pfsense-mcp/` — pfSense MCP server (8 tools)
- `workspace/skills/pfsense-firewall-ops/` — pfSense skill
- `workspace/skills/synology-nas-monitor/` — Synology NAS skill

---

## What NOT to Do

- **Don't write more Python agent code.** The net-ops-team pattern is the wrong pattern.
- **Don't add more tools to the security expert.** It's being retired.
- **Don't fork NetClaw.** Use the submodule + deployment config pattern it was designed for.
- **Don't register MCP servers you don't need.** 36 servers on disk doesn't mean 36 need to be active. Register only what this network uses.
- **Don't skip testing MCP servers before building skills.** A skill that calls a broken MCP server will fail silently and waste LLM tokens.

---

## The Dockerfile Question

The current Dockerfile approach (bake everything into an image) has problems:
- `install.sh` fails on some steps and we `|| true` past them
- `openclaw onboard` never runs (it's interactive)
- MCP server registration is done manually after container start
- The testbed is baked in with wrong device IPs

**Two options:**

**Option A: Fix the Dockerfile (pragmatic)**
- Keep the current approach but add a `setup-convergence.sh` script that runs after container start
- Script registers the needed MCP servers, updates the testbed, and validates connectivity
- Run it once after `docker compose up`, or as an init container

**Option B: Run NetClaw natively (correct)**
- Install NetClaw on the host (not in Docker)
- Run `install.sh` properly with all prerequisites
- Run `openclaw onboard` interactively to configure provider, gateway, and MCP servers
- Update testbed with real devices
- The OpenClaw gateway runs as a systemd service or in tmux
- Docker Compose only runs the infrastructure (OTEL, VM, Loki, Grafana, Redis) and data services (threat-intel, automation-agent, scheduler)

Option B is how NetClaw was designed to be deployed. Option A is a compromise for keeping everything in Docker Compose.

**Recommendation:** Option A for now (we're already invested in the Docker approach), with a `setup-convergence.sh` script that handles the MCP registration and testbed setup. Move to Option B later if the Docker approach keeps causing friction.

---

## Files That Matter for Next Session

| File | What It Is |
|------|-----------|
| `docs/PHASE10_NETCLAW_MIGRATION.md` | Full migration plan (Sessions 1-6) |
| `docs/PHASE10_SESSION1_STATUS.md` | What was accomplished + critical MCP registration gap |
| `config/netclaw/openclaw.json` | Deployment config (MCP servers registered here via CLI) |
| `netclaw/config/openclaw.json` | Submodule config (older format, has all MCP server defs) |
| `netclaw/mcp-servers/pfsense-mcp/` | New pfSense MCP server (tested, working) |
| `mcp-servers/convergence-mcp/` | Convergence platform MCP server (tested, working) |
| `mcp-servers/netclaw-proxy/` | REST proxy sidecar (tested, working) |
| `netclaw/workspace/skills/pfsense-firewall-ops/` | pfSense skill (written, not tested via skill invocation) |
| `netclaw/workspace/skills/synology-nas-monitor/` | Synology skill (written, not tested via skill invocation) |
| `docker/netclaw.Dockerfile` | Current Dockerfile (needs setup script addition) |
| `netclaw/testbed/testbed.yaml` | pyATS testbed (WRONG — points to sandbox, needs real devices) |
| `netclaw/TOOLS.md` | Deployment notes (needs update with actual network info) |
