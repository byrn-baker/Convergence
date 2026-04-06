# Phase 10: NetClaw Migration — Sessions 2 & 3 Status

**Date:** 2026-04-05
**Status:** Sessions 2, 3 & 4 Complete — Skills written, scheduler built, net-ops-team retired, Ollama Cloud configured

---

## What Was Accomplished

### Session 2: Convergence-Specific Skills

Three deployment-specific skills created in `config/netclaw/workspace/skills/` (not upstream — these reference Convergence service URLs, device IPs, and VLAN layouts).

**convergence-noc-watch/SKILL.md** — Replaces NOC Officer + Network Engineer agents

- 6-step health check procedure: SNMP reachability → interface utilization → error rates → firewall block rate → pfSense health → critical syslog
- Preserved domain knowledge from both agent system prompts:
  - Exact metric names: `system_uptime_seconds`, `interface_in_octets_bytes_total`, `interface_in_errors_total`, `firewall_events_total`
  - WS-C3850-48P combo uplink rule: Gi1/1/x disabled when Te1/1/x active = normal hardware behavior
  - Interface speed table: Gi=1G, Te=10G, Fa=100M, Po=1G default
  - Utilization thresholds: >70% WARNING, >90% CRITICAL
  - "Empty results ≠ outage" rule — report INFO only
  - Nautobot port description lookup before reporting bandwidth findings
  - pfSense health checks via pfsense-mcp (CPU, memory, gateway RTT/loss)
- Uses: prometheus-mcp, grafana-mcp, nautobot-mcp, pfsense-mcp

**convergence-security-monitor/SKILL.md** — Replaces Security Expert + Security Engineer agents

- 5-step threat hunting procedure: block rate → threat intel → filterlog → NetFlow → pending blocks
- Preserved domain knowledge from both agent system prompts:
  - OTLP JSON attribute format for NetFlow records (`"key":"source.address","value":{"stringValue":"..."}`)
  - MANDATORY Nautobot-first internal host validation before flagging any RFC1918 IP
  - Known device roles: NAS talking to multiple VLANs = normal, IoT on mDNS/AirPlay ports = normal
  - /24 subnet blocking protocol: block the CIDR when multiple IPs from same range
  - Hard rules: max 3 block submissions per cycle, never block internal IPs, score ≥ 80 required
  - Noise reduction: no INFO findings, no "investigate" recommendations for things tools can answer
  - Full network inventory with IP ranges and device roles
- Uses: prometheus-mcp, grafana-mcp, convergence-mcp, nautobot-mcp, pfsense-mcp

**convergence-interface-reconciler/SKILL.md** — Replaces Interface Reconciler agent

- 3-phase reconciliation procedure: description enrichment → admin state sync → inventory diff
- Preserved domain knowledge from the agent system prompt:
  - Exact description format: `VLAN10 | hostname | 192.168.x.x`
  - MAC→DHCP/ARP→hostname enrichment workflow (pfSense DHCP preferred, ARP fallback)
  - Nautobot-authoritative admin state sync (enabled=false → push shutdown to switch)
  - Skip rules: Null0, StackPort1, StackPort2 for inventory; trunk/uplink ports for descriptions
  - Combo uplink rule: don't touch Gi1/1/1–4 if Te1/1/1–4 active
  - Only-write-if-changed optimization to avoid pointless write cycles
  - DHCP enrichment is best-effort — skip gracefully if pfSense unavailable
- Uses: pyats-network, pyats-config-mgmt, nautobot-mcp, pfsense-mcp, prometheus-mcp

### Session 3: convergence-scheduler Service

**services/convergence-scheduler/** — Lightweight cron + Discord notification relay (~100 lines of logic)

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI + APScheduler — sends skill prompts to NetClaw via REST proxy, parses `[CRITICAL]`/`[WARNING]` prefixed lines, posts to Discord |
| `app/config.py` | Pydantic settings: proxy URL, Discord webhook, poll/report intervals, dedup window |
| `app/discord.py` | Discord webhook posting with 30-min dedup by finding key |
| `app/__init__.py` | Package init |
| `Dockerfile` | python:3.12-slim, standard pattern |
| `requirements.txt` | fastapi, uvicorn, httpx, pydantic-settings, apscheduler |

**What it does:**
- Every 10 minutes: sends a prompt to NetClaw via REST proxy asking it to run all three Convergence skills
- Parses the response for `[CRITICAL]`, `[WARNING]`, `[INFO]` prefixed lines
- Posts WARNING/CRITICAL findings to Discord with 30-min dedup (same finding won't re-alert)
- Every 60 minutes: requests a shift report summary and posts to Discord
- Exposes `/health`, `/api/v1/latest` (last poll result), `POST /api/v1/run` (manual trigger)

**What it does NOT do:**
- No LLM calls — it's a scheduler, not an AI agent
- No tool definitions — NetClaw handles all tool use via its skills and MCP servers
- No system prompts — NetClaw's SOUL + skills handle reasoning

**Wiring:**
- `cron (APScheduler)` → `httpx POST to REST proxy /ask` → `NetClaw runs skills` → `response text` → `regex parse findings` → `Discord webhook`

### Infrastructure Changes

**docker-compose.yml:**
- Added `convergence-scheduler` service on port 8004
- Depends on `netclaw` container
- Environment: `NETCLAW_PROXY_URL`, `DISCORD_WEBHOOK_URL`, `POLL_INTERVAL_MINUTES`, `REPORT_INTERVAL_MINUTES`, `DEDUP_MINUTES`
- Standard healthcheck on `/health`

---

## Files Created

| File | Purpose |
|------|---------|
| `config/netclaw/workspace/skills/convergence-noc-watch/SKILL.md` | NOC health monitoring skill |
| `config/netclaw/workspace/skills/convergence-security-monitor/SKILL.md` | Security threat hunting skill |
| `config/netclaw/workspace/skills/convergence-interface-reconciler/SKILL.md` | Interface reconciliation skill |
| `services/convergence-scheduler/app/main.py` | FastAPI + APScheduler main app |
| `services/convergence-scheduler/app/config.py` | Pydantic settings |
| `services/convergence-scheduler/app/discord.py` | Discord webhook + dedup |
| `services/convergence-scheduler/app/__init__.py` | Package init |
| `services/convergence-scheduler/Dockerfile` | Container build |
| `services/convergence-scheduler/requirements.txt` | Python dependencies |

## Files Modified

| File | Change |
|------|--------|
| `docker-compose.yml` | Added convergence-scheduler service definition (port 8004, depends_on netclaw) |

---

## Testing

### Skills (via NetClaw chat)

```bash
# NOC Watch
docker exec convergence-netclaw openclaw agent --message "Run convergence-noc-watch"

# Security Monitor
docker exec convergence-netclaw openclaw agent --message "Run convergence-security-monitor"

# Interface Reconciler
docker exec convergence-netclaw openclaw agent --message "Run convergence-interface-reconciler"
```

### Scheduler

```bash
cd /home/ubuntu/Convergence
docker compose build convergence-scheduler
docker compose up -d convergence-scheduler
curl http://localhost:8004/health
curl -X POST http://localhost:8004/api/v1/run
curl http://localhost:8004/api/v1/latest
```

---

## What Remains (Session 5)

### ~~Session 4: Cutover~~ ✅ COMPLETE
- Stopped net-ops-team container
- Started convergence-scheduler
- Removed net-ops-team from docker-compose.yml
- Removed net-ops-team Docker images
- Fixed REST proxy: removed `--json` flag (caused hangs), switched to Popen with kill-on-timeout
- Fixed Ollama Cloud config: switched from local proxy to direct `https://ollama.com/v1` via `openai-completions` provider
- Removed fallback model (`qwen3.5:9b` doesn't exist on Ollama Cloud)
- Bumped timeouts to 900s (cloud model + multi-turn tool calls need time)
- First successful poll cycle: 18 findings across noc-watch + security-monitor
- Fixed pfSense crash: `convergence-mcp` was calling `system_get_dhcp_leases()` via xmlrpc.client — function removed in pfSense Plus 25.11. Replaced with direct `exec_php` parsing `/var/dhcpd/var/db/dhcpd.leases`
- Fixed alert quality: tightened skill prompts and scheduler prompts to demand investigation before reporting. Blocked scans are normal — only report if traffic PASSED or volume is 10x baseline. Every finding must include source IP, destination, blocked/passed, count, ASN
- Fixed blocking strategy: stopped individual /32 blocks (fills alias table, accomplishes nothing). Agent now groups by ASN and recommends pfBlockerNG instead. `submit_block_action` reserved for traffic that PASSED the firewall only
- Cleaned up stale references to net-ops-team in convergence-mcp and automation-agent
- Archived `services/net-ops-team/` to tarball, removed directory
- Purged 6 zombie Docker images (~1.5GB), 2 unused promtail versions (~526MB), 26.8GB build cache

### Session 5: Upstream Contribution
- PR pfsense-mcp to automateyournetwork/netclaw
- PR pfsense-firewall-ops skill
- PR synology-nas-monitor skill

---

## Current Container Status

- **convergence-scheduler**: Running (port 8004) — triggers NetClaw skills every 10 min
- **net-ops-team**: RETIRED — removed from docker-compose.yml, images deleted, code archived
- **netclaw**: Running with pfsense-mcp + convergence-mcp (fixed) + REST proxy sidecar + 3 Convergence skills
- **threat-intel**: Unchanged, running
- **automation-agent**: Unchanged, running (comments updated to reference NetClaw)
- All other infrastructure: Unchanged, running
- **Docker cleanup**: 6 zombie images removed, 26.8GB build cache purged, 0 stopped containers, 0 dangling volumes
