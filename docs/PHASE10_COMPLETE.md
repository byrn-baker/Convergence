# Phase 10: NetClaw Migration — Complete

**Date:** 2026-04-06
**Status:** ✅ Complete — net-ops-team retired, NetClaw multi-agent team operational

## What Changed

The six-agent Python NOC team (`services/net-ops-team/`) was retired and replaced by NetClaw skills triggered by a lightweight scheduler. The automation-agent's independent poll cycle was disabled — it now operates as an execute-only service receiving block requests from NetClaw.

### Architecture Before (Phase 7-9)

```
net-ops-team (6 Python agents, each with own LLM client + tools)
  → NOC Officer, Network Engineer, Security Expert, Security Engineer,
    NAS Engineer, Interface Reconciler
  → Each runs own agentic loop against Anthropic/Ollama
  → 1-2M tokens per poll cycle across 6 concurrent agents
  → 158 findings in 6 hours, most noise

automation-agent (independent poll cycle)
  → Fetches IPs from threat-intel, blocks /32s independently
  → No coordination with net-ops-team
```

### Architecture After (Phase 10)

```
NetClaw (OpenClaw Gateway + 4 named agents)
  ├── noc agent        → convergence-noc-watch skill
  ├── security agent   → convergence-security-monitor skill
  ├── reconciler agent → convergence-interface-reconciler skill
  └── main agent       → Discord chat (ad-hoc questions)

convergence-scheduler (100 lines Python)
  → Triggers skills concurrently via REST proxy
  → Posts full responses to Discord
  → Discord bot for interactive questions

automation-agent (execute-only, poll disabled)
  → Receives block requests via /api/automation/submit
  → GAIT audit trail, approval pipeline, pfSense execution
  → No independent decision-making
```

### Key Changes

| Component | Before | After |
|-----------|--------|-------|
| AI agents | 6 Python modules (~3,800 lines) | 3 SKILL.md files (~450 lines Markdown) |
| Agent runtime | Custom agentic loops per agent | OpenClaw gateway with named agents |
| Concurrency | Sequential (session lock) | Parallel (4 agents, each own session) |
| LLM provider | Custom multi-provider client | OpenClaw `openai-completions` → Ollama Cloud |
| Scheduler | APScheduler + supervisor.py | convergence-scheduler (100 lines) |
| Discord bot | discord.py in net-ops-team | discord.py in convergence-scheduler |
| Blocking | Independent poll + /32 whack-a-mole | Compromise-only, recommend pfBlockerNG ASN |
| automation-agent | Rogue independent polling | Execute-only (POLL_ENABLED=false) |
| Alert quality | 158 findings/6h, mostly noise | Full detailed responses with ASN/IP/action specifics |

### Files Created

| File | Purpose |
|------|---------|
| `config/netclaw/workspace/skills/convergence-noc-watch/SKILL.md` | NOC health monitoring |
| `config/netclaw/workspace/skills/convergence-security-monitor/SKILL.md` | Security threat hunting |
| `config/netclaw/workspace/skills/convergence-interface-reconciler/SKILL.md` | Interface reconciliation |
| `services/convergence-scheduler/app/main.py` | FastAPI + APScheduler + concurrent skill dispatch |
| `services/convergence-scheduler/app/config.py` | Pydantic settings |
| `services/convergence-scheduler/app/discord.py` | Discord webhook + full response posting |
| `services/convergence-scheduler/app/bot.py` | Discord bot for interactive questions |
| `services/convergence-scheduler/Dockerfile` | Container build |
| `services/convergence-scheduler/requirements.txt` | Python dependencies |

### Files Removed/Archived

| File | Action |
|------|--------|
| `services/net-ops-team/` | Archived to `net-ops-team-ARCHIVED-phase10.tar.gz` |
| net-ops-team Docker images | Deleted (~350MB) |
| 6 zombie Docker images | Deleted (~1.5GB) |
| 26.8GB Docker build cache | Purged |

### Files Modified

| File | Change |
|------|--------|
| `docker-compose.yml` | Removed net-ops-team, added convergence-scheduler, added POLL_ENABLED=false to automation-agent, added skill volume mount to netclaw |
| `docker/netclaw.Dockerfile` | Added skill symlink to CMD for OpenClaw skill discovery |
| `mcp-servers/convergence-mcp/convergence_mcp_server.py` | Fixed pfSense crash (replaced xmlrpc.client with exec_php), marked net-ops-team references as retired |
| `mcp-servers/netclaw-proxy/netclaw_proxy.py` | Threaded server, per-agent locks, agent parameter support, BrokenPipeError handling |
| `services/automation-agent/app/config.py` | Added `poll_enabled` setting |
| `services/automation-agent/app/scheduler.py` | Skip scheduler start when `poll_enabled=false` |
| `services/automation-agent/app/main.py` | Updated comments to reference NetClaw |

### Bugs Fixed

| Bug | Impact | Fix |
|-----|--------|-----|
| `--json` flag hangs openclaw CLI | Proxy never returns response | Removed `--json` |
| Zombie openclaw-agent processes | Memory leak, session locks | Popen with proc.kill() |
| Session file locks from killed processes | Cascading failures | Lock cleanup on timeout |
| Ollama proxy hop latency | 12s per "hello", skills timeout | Direct Ollama Cloud API |
| OpenClaw Ollama provider no Bearer auth | 401 on every request | Use `openai-completions` provider |
| Invalid API type enum `"openai"` | Gateway crash loop | Changed to `"openai-completions"` |
| Fallback model doesn't exist on cloud | 404 after every timeout | Removed fallback |
| 300s timeout too short | BrokenPipeError | Bumped to 600-900s |
| `system_get_dhcp_leases()` removed in pfSense 25.11 | PHP fatal error every 10 min | Replaced with direct lease file parsing |
| Useless alerts ("RDP targeted" without specifics) | Alert fatigue | Strict finding rules in skills |
| /32 IP blocking | Fills alias table, accomplishes nothing | Compromise-only, recommend pfBlockerNG |
| automation-agent independent polling | Rogue blocking without context | POLL_ENABLED=false |
| Skills not found by OpenClaw | Agents can't run skills | Symlink into OpenClaw install path |
| Single-threaded proxy | Requests queue and timeout | ThreadingMixIn + per-agent locks |

### OpenClaw Configuration

4 named agents created via `openclaw agents add`:

| Agent | Purpose | Session |
|-------|---------|---------|
| main | Discord interactive chat | Independent |
| noc | convergence-noc-watch skill | Independent |
| security | convergence-security-monitor skill | Independent |
| reconciler | convergence-interface-reconciler skill | Independent |

LLM provider: `ollama-cloud/qwen3-coder:480b` via `openai-completions` API at `https://ollama.com/v1`

### Container Status (Final)

| Container | Port | Status |
|-----------|------|--------|
| convergence-alertmanager | 9093 | Running |
| convergence-automation-agent | 8002 | Running (poll disabled) |
| convergence-grafana | 3000 | Running |
| convergence-loki | 3100 | Running |
| convergence-netclaw | 18789, 18790, 3001 | Running (4 agents) |
| convergence-otel-collector | 4317, 514, 8888 | Running |
| convergence-promtail | 9080 | Running |
| convergence-redis | 6379 | Running |
| convergence-scheduler | 8004 | Running (cron + Discord bot) |
| convergence-threat-intel | 8001 | Running |
| convergence-victoriametrics | 8428 | Running |
