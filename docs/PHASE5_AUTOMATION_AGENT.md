# Phase 5: Event-Driven Automation Agent

**Last Updated:** 2026-03-02
**Status:** Live — XML-RPC alias mode active, Discord bot running, repeat-offender tracking enabled

### Changelog

| Date | Change |
|------|--------|
| 2026-03-02 | Fixed GAIT not recording execution turns for Discord bot approvals (`discord_bot.py` was passing `session=None` despite a comment claiming the session was re-opened inside `execute_and_verify` — it was not). Both `/approve` and `/approve-all` now properly open a `{session_id}-approved` GAIT branch and record the full execution trail. |
| 2026-03-02 | Identified that `PFSENSE_SSH_KEY_PATH` must reference a path **inside the container**, not the host filesystem. The `automation-audit` volume is the only volume mounted; host SSH keys are not accessible unless explicitly mounted in `docker-compose.yml`. |
| 2026-02-25 | Initial Phase 5 release. |

---

## Overview

Phase 5 adds an `automation-agent` microservice that turns high-risk threat-intel signals into
auditable, human-gated (or auto-approved) pfSense blocking actions. The core design principle is
**fail-closed with a complete paper trail**: every decision the AI makes is committed to an
immutable git repository before any action is attempted, and `DRY_RUN=true` is the default.

1. **GAIT Audit Trail** — Every automation session creates a dedicated git branch with sequential
   JSON "turn" files recording exactly what data the AI saw, what prompt it received, what it
   decided, and what happened. This is the forensic record that answers "what did the AI do
   and why" indefinitely.
2. **Human Gating via Discord Bot** — Actions scoring below `AUTO_APPROVE_THRESHOLD` (default 95)
   are posted to Discord as rich embeds. The bot provides `/approve`, `/reject`, `/approve-all`,
   `/reject-all`, and `/pending` slash commands directly in the alert channel.
3. **Repeat Offender Detection** — Each successful block increments a per-IP lifetime counter in
   Redis (1-year TTL). Repeated offenders get escalated block durations and a permanent-block
   recommendation for both Claude and the human reviewer.
4. **Pre/Post Baseline Verification** — Before any action, VictoriaMetrics metrics are captured
   for the target IP. After execution, the service waits 5 minutes and re-queries to measure
   whether the action was effective.
5. **Redis Rate Limiting** — A sliding 60-minute window prevents more than `MAX_ACTIONS_PER_HOUR`
   automated live actions. Human `/approve-all` from Discord bypasses this cap intentionally
   (the limit protects unattended automation, not conscious human decisions).
6. **pfSense Integration** — Three execution paths tried in order (REST API → XML-RPC → SSH).
   The XML-RPC path uses a raw httpx transport because pfSense prepends PHP echo output before
   the XML-RPC XML envelope — standard `xmlrpc.client` cannot parse these responses.

---

## Architecture

```
threat-intel service (FastAPI :8001)
    │ GET /api/infinity/blocked_ips
    │ GET /api/infinity/outbound_suspicious
    │ GET /api/report  (full enrichment data)
    ▼
automation-agent (FastAPI + APScheduler :8002)  ← poll every 10 min
    │
    ├─ Filter: score >= 80, is_known_bad_actor, not likely_false_positive
    ├─ Redis dedup check (processed recently? skip)
    ├─ In-memory dedup check (already pending? skip)
    ├─ Rate limit check (auto-approve path: >5/hour? skip)
    │
    ├─ Redis: get_block_count(ip) → enrich threat_data["block_count"]
    ├─ Open GAIT session → git branch automation-{ts}-{ip}
    │   ├─ Turn 00: input.json         (threat data + block_count + config snapshot)
    │   ├─ Turn 01: baseline.json      (VM PromQL snapshot)
    │   ├─ Turn 02: claude_prompt.txt  (exact prompt sent to Claude, inc. block history)
    │   ├─ Turn 03: proposed_action.json (Claude JSON response)
    │   ├─ Turn 04: decision.json      (dry_run / pending / auto_approve)
    │   ├─ Turn 05: execution_result.json
    │   ├─ Turn 06: verification.json  (post-action metric diff)
    │   └─ Turn 07: outcome.json       (sealed)
    │
    ├─ DRY_RUN=true → log + Discord blue embed → done
    ├─ score < 95    → Discord orange embed → park in pending_approvals{}
    │                  mark_ip_processed(4h) — prevents re-alert on next poll cycle
    │                  Discord bot: /approve|/reject|/approve-all|/reject-all|/pending
    │                  On approval → open new GAIT branch {session_id}-approved
    │                               record: approval → execution_result → verification → outcome
    └─ score >= 95   → auto-execute → wait 5 min → verify → rollback on fail
            │         increment_block_count(ip) → mark_ip_processed(block_ttl_hours)
            ▼
    pfSense Plus 25.11 (REST API → XML-RPC → SSH, first success wins)
    Path A: POST /api/v2/firewall/alias/entry → POST /api/v2/firewall/apply
    Path B: httpx → xmlrpc.php exec_php → PHP config API → write_config + filter_configure
            (alias mode: edits AutoAgent_Block_v4 Firewall Alias directly)
            _xmlrpc_write_lock serialises concurrent writes to prevent race condition
    Path C: pfctl -t AutoAgent_Block_v4 -T add {cidr}  (runtime only)

    Prometheus metrics → scraped by VictoriaMetrics every 30s
    Grafana Infinity → /api/infinity/sessions|pending|audit
```

---

## File Inventory

### Service files

```
services/automation-agent/
├── Dockerfile                         python:3.12-slim + git binary
├── requirements.txt                   fastapi, apscheduler, gitpython, paramiko, redis, anthropic, httpx, discord.py
└── app/
    ├── main.py                        FastAPI app — 11 endpoints incl. setup-pfsense
    ├── scheduler.py                   APScheduler 10-min poll + per-IP session orchestration
    ├── config.py                      Pydantic-settings env var config (all safety knobs)
    ├── state.py                       Module-level latest_report + pending_approvals dict
    ├── metrics.py                     7 Prometheus metrics definitions
    ├── audit/
    │   └── git_trail.py               GitAuditTrail + AuditSession (gitpython branch-per-session)
    ├── actions/
    │   ├── baseline.py                capture_baseline() + verify_action() via PromQL
    │   ├── pfblocker.py               PfBlockerAction + execute/rollback; httpx XML-RPC transport
    │   ├── rate_limiter.py            Sliding-window rate limiter, IP dedup TTL, block count tracking
    │   └── executor.py                execute_and_verify() — shared by scheduler + approve endpoint
    ├── analysis/
    │   └── claude_action.py           Action-proposal prompt with block history + volume flags
    └── notifications/
        ├── discord.py                 Webhook: approval-required + outcome embeds (block history shown)
        └── discord_bot.py             Bot: /approve /reject /approve-all /reject-all /pending

config/grafana/provisioning/datasources/automation-agent.yaml
dashboards/automation/automation-agent.json
docs/PHASE5_AUTOMATION_AGENT.md  (this file)
```

### Modified files

```
docker-compose.yml                     automation-agent service + automation-audit volume
config/victoriametrics/prometheus.yml  automation-agent scrape job
.env / .env.example                    PFSENSE_*, DRY_RUN, AUTO_*_THRESHOLD, DISCORD_BOT_TOKEN,
                                       REPEAT_OFFENDER_THRESHOLD, HIGH_VOLUME_THRESHOLD
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health, dry_run flag, config summary, rate limit status |
| GET | `/metrics` | Prometheus metrics (scraped by VictoriaMetrics) |
| GET | `/api/automation/report` | Full in-memory session report (last 100 sessions) |
| GET | `/api/automation/pending` | Sessions awaiting human approval (expired ones pruned) |
| POST | `/api/automation/approve/{id}` | Approve a pending session → execute in background |
| DELETE | `/api/automation/approve/{id}` | Reject a pending session → no action taken |
| GET | `/api/automation/audit` | Recent GAIT git branches summary |
| POST | `/api/automation/setup-pfsense` | Create alias + WAN block rule in pfSense (idempotent) |
| GET | `/api/infinity/sessions` | Recent sessions flat array (Grafana Infinity) |
| GET | `/api/infinity/pending` | Pending approvals flat array (Grafana Infinity) |
| GET | `/api/infinity/audit` | Audit trail branch list flat array (Grafana Infinity) |

---

## Environment Variables

### pfSense Integration

**Shared (all paths)**

| Variable | Default | Description |
|---|---|---|
| `PFSENSE_HOST` | *(empty)* | pfSense management IP, optionally with port: `192.168.1.1:440` |
| `PFSENSE_VERIFY_SSL` | `false` | `false` = accept self-signed certs |

**Path A — REST API v2 (optional, preferred when available)**

| Variable | Default | Description |
|---|---|---|
| `PFSENSE_API_KEY` | *(empty)* | API key from System > API > Keys; empty = skip |
| `PFSENSE_FIREWALL_ALIAS` | `AutoAgent_Block_v4` | Firewall alias the agent manages |

**Path B — XML-RPC (no API key required)**

| Variable | Default | Description |
|---|---|---|
| `PFSENSE_XMLRPC_USER` | `admin` | pfSense web UI username (must be admin for exec_php) |
| `PFSENSE_XMLRPC_PASS` | *(empty)* | pfSense web UI password; empty = skip |
| `PFSENSE_XMLRPC_TARGET` | `alias` | `alias` = plain Firewall Alias (recommended); `pfblockerng` = pfBlockerNG custom list |

**Path C — SSH emergency fallback**

| Variable | Default | Description |
|---|---|---|
| `PFSENSE_SSH_HOST` | *(empty)* | SSH host (falls back to `PFSENSE_HOST`) |
| `PFSENSE_SSH_USER` | `admin` | pfSense SSH username |
| `PFSENSE_SSH_KEY_PATH` | *(empty)* | Path to private key inside container; empty = skip |

### Discord

| Variable | Default | Description |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | *(empty)* | Incoming webhook for outcome notifications (one-way) |
| `DISCORD_BOT_TOKEN` | *(empty)* | Bot token for slash commands. Empty = webhook-only mode |
| `DISCORD_GUILD_ID` | `0` | Guild (server) ID for instant slash command sync. `0` = global (~1h delay) |

### Safety Controls

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `true` | **Master kill-switch.** `true` = log everything, touch nothing |
| `AUTO_ACTION_THRESHOLD` | `80` | Minimum `composite_score` to even consider a block |
| `AUTO_APPROVE_THRESHOLD` | `95` | Score above which Discord approval is skipped |
| `MAX_ACTIONS_PER_HOUR` | `5` | Hard cap on **automated** live actions per 60-min window |
| `BLOCK_TTL_HOURS` | `24` | Temporary block duration (hours) |
| `REPEAT_OFFENDER_THRESHOLD` | `5` | Lifetime blocks before flagging for permanent block |
| `HIGH_VOLUME_THRESHOLD` | `50` | Events/hour above which aggressive flag is raised |
| `POLL_INTERVAL_SECONDS` | `600` | How often to poll threat-intel (10 minutes) |

> **Setting `AUTO_APPROVE_THRESHOLD=101`** effectively disables auto-approve entirely — every
> qualifying action requires a human to use the Discord bot slash commands or POST the approval URL.

---

## Safety Model

```
DRY_RUN=true (default)
    └─ Logs everything. Discord blue embed. No pfSense changes. Ever.

DRY_RUN=false + score in [80, 95)
    └─ Discord orange embed sent to approval channel.
       mark_ip_processed(4h) — prevents re-alerting this IP on every poll cycle.
       Discord bot: /approve, /reject, /approve-all, /reject-all, /pending.
       Human approval:
         → opens new GAIT branch {session_id}-approved
         → records approval.json (approver, timestamp, channel)
         → fires execute_and_verify() in background (bypasses rate limit)
         → records execution_result, verification, outcome in GAIT
       Session expires after 4 hours with no action if ignored.

DRY_RUN=false + score >= 95 (auto-approve)
    └─ Action executes automatically (rate-limited by MAX_ACTIONS_PER_HOUR).
       Baseline captured → action applied → 5 min wait → metrics verified.
       Rollback attempted if execution fails.
       Discord green/red outcome embed always sent.

All paths:
    └─ GAIT git branch committed at every step.
       block_count incremented in Redis after every live block.
       IP dedup TTL prevents re-processing (4h for pending, BLOCK_TTL_HOURS for executed).
```

### False Positive Guards

Claude's action-proposal prompt includes hard constraints:
- `likely_false_positive = true` → must return `type: "no_action"`
- Score below threshold → must return `type: "no_action"`
- RFC 1918 private IPs → never block
- Known CDN/infrastructure orgs (Cloudflare, Akamai, Google, Apple, Microsoft) → never block unless `abuse_score > 80`
- Outbound traffic → only propose block if score > 85 AND abuse score > 60

---

## pfSense Integration

Targets **pfSense Plus 25.11**. Three paths tried in order; the first to succeed wins. Each path
is skipped silently if its required credentials are not configured.

### One-time setup (run once before going live)

```bash
curl -s -X POST http://localhost:8002/api/automation/setup-pfsense | python3 -m json.tool
# → {"alias": "created", "rule": "created", "success": true}
# → {"alias": "exists",  "rule": "exists",  "success": true}  (idempotent)
```

This endpoint uses XML-RPC exec_php to:
1. Create the `AutoAgent_Block_v4` Firewall Alias (Type: Host) if it doesn't exist
2. Insert a WAN block rule with Source = `AutoAgent_Block_v4` before the first existing WAN rule

Safe to call multiple times. Requires `PFSENSE_XMLRPC_PASS` and `PFSENSE_HOST`.

### Path A — REST API v2 (optional, preferred when available)

File: `services/automation-agent/app/actions/pfblocker.py` → `_rest_api_add()`

Requires `PFSENSE_API_KEY`. Adds an IP to a Firewall Alias via the pfSense Plus REST API.

```
POST /api/v2/firewall/alias/entry   Authorization: Bearer {key}
POST /api/v2/firewall/apply
```

Manual setup (if not using the setup endpoint):
```
1. System > API > Keys  →  Add key, assign to admin user
2. Firewall > Aliases   →  Add: Name=AutoAgent_Block_v4, Type=Host(s)
3. Firewall > Rules     →  Add block rule: Source = AutoAgent_Block_v4, placed above pass rules
```

### Path B — XML-RPC exec_php (no API key required)

File: `services/automation-agent/app/actions/pfblocker.py` → `_xmlrpc_add()`

Requires `PFSENSE_XMLRPC_PASS`. Connects to pfSense's `/xmlrpc.php` endpoint and runs PHP
code directly via the `pfsense.exec_php` method.

**Why httpx instead of `xmlrpc.client`**: pfSense prepends any PHP `echo` output to the HTTP
response body *before* the XML-RPC envelope. `xmlrpc.client` tries to parse the entire response
as XML and fails at byte 0. The `_xmlrpc_exec_php()` function uses httpx with HTTP Basic Auth,
locates the `<?xml` offset in the response, splits off the PHP echo output, then checks the
envelope for fault codes manually. This also avoids URL-encoding issues with special characters
(e.g. `@`) in passwords.

**Why HTTP Basic Auth instead of URL-embedded credentials**: Credentials embedded in the URL
(`user:pass@host`) break with passwords containing `@`, `#`, or other reserved characters. httpx's
`auth=` parameter handles this correctly regardless of password content.

**Two sub-modes** controlled by `PFSENSE_XMLRPC_TARGET`:

| Mode | What it does | Requires |
|---|---|---|
| `alias` (default) | Adds IP to a plain Firewall Alias via PHP config API (`config_set_path`, `write_config`, `filter_configure`). Persistent across reboots, no pfBlockerNG. | `AutoAgent_Block_v4` alias + block rule (created by setup endpoint) |
| `pfblockerng` | Appends CIDR to `/var/db/pfblockerng/custom/{list}.txt` and calls `pfblockerng_sync_cron()`. | pfBlockerNG installed, list named in `PFSENSE_FIREWALL_ALIAS` |

**Concurrent write serialization**: `_xmlrpc_write_lock` (an `asyncio.Lock`) serialises all alias
add and delete operations. Without this, `/approve-all` with many IPs would fire concurrent
read-modify-write cycles that all read the same initial alias state — last writer wins, others'
IPs are lost.

Minimal `.env` to activate alias mode:
```bash
PFSENSE_HOST=192.168.1.1          # or 192.168.1.1:440 for non-standard GUI port
PFSENSE_XMLRPC_USER=admin         # must be admin for exec_php
PFSENSE_XMLRPC_PASS=your_password
PFSENSE_XMLRPC_TARGET=alias
DRY_RUN=false
```

### Path C — SSH pfctl (emergency fallback)

File: `services/automation-agent/app/actions/pfblocker.py` → `_ssh_add()`

Requires `PFSENSE_SSH_KEY_PATH`. Connects via paramiko and runs:
```bash
pfctl -t AutoAgent_Block_v4 -T add {cidr}
```
**Runtime-only** — does not survive a reboot or pfSense config reload. Intended for emergency
use when both REST API and XML-RPC are unavailable.

SSH key setup:
```bash
ssh-keygen -t ed25519 -f pfsense_id_ed25519 -C "convergence-autoagent" -N ""
# Add public key: System > User Manager > admin > Authorized SSH Keys
# Mount private key via docker-compose.yml volumes:
#   - ./secrets/pfsense_id_ed25519:/app/secrets/pfsense_id_ed25519:ro
```

---

## Discord Bot

File: `services/automation-agent/app/notifications/discord_bot.py`

The bot connects via the Discord Gateway (persistent outbound WebSocket), so no public IP or
inbound HTTPS is required — works in home-lab and NAT environments.

### Slash commands

| Command | Description |
|---|---|
| `/pending` | List all unexpired pending approvals with session IDs, scores, and expiry times |
| `/approve <session_id>` | Approve and execute a specific pending session |
| `/reject <session_id>` | Reject a specific pending session — no pfSense changes |
| `/approve-all` | Approve every unexpired pending session immediately (no rate limit cap) |
| `/reject-all` | Reject every unexpired pending session at once |

### GAIT recording for Discord approvals

Both `/approve` and `/approve-all` open a new `{session_id}-approved` git branch before firing
the execution task. The branch records:

1. `00_approval.json` — who approved (`approved_by`), when, and via which path (`discord` or
   `discord_bulk`)
2. `01_execution_result.json` — pfSense XML-RPC / REST API result
3. `02_verification.json` — post-action metric comparison
4. `03_outcome.json` — final sealed result

This mirrors exactly what the REST API `/api/automation/approve/{id}` endpoint does. If execution
fails the failure is visible in `01_execution_result.json` rather than disappearing silently.

### Rate limit behaviour

`/approve-all` bypasses `MAX_ACTIONS_PER_HOUR`. The rate limit exists to protect the unattended
auto-approve path from runaway automation — when a human explicitly issues `/approve-all` they are
making a conscious decision and the cap is counterproductive. The `record_action_taken()` call
inside `execute_and_verify()` still fires for metrics accuracy.

### Setup

```
1. https://discord.com/developers/applications → New Application → Bot tab
2. Bot tab → Reset Token → copy to DISCORD_BOT_TOKEN in .env
3. OAuth2 → URL Generator → scopes: bot + applications.commands
   Permissions: Send Messages, Use Slash Commands
   → copy invite URL → add bot to your server
4. Set DISCORD_GUILD_ID to your server ID for instant slash command sync
   (Enable Developer Mode: User Settings → Advanced → right-click server → Copy Server ID)
```

---

## Repeat Offender & Block Count Tracking

File: `services/automation-agent/app/actions/rate_limiter.py`

Every successful live block increments a per-IP counter in Redis DB 1:

```
Key:   automation:block_count:{ip}
Type:  integer (INCR)
TTL:   365 days (1 year)
```

The count is fetched before Claude's analysis in each poll cycle (`scheduler.py`) and added to
`threat_data["block_count"]`. Two thresholds drive escalation:

| Threshold | Variable | Default | Effect |
|---|---|---|---|
| Lifetime blocks | `REPEAT_OFFENDER_THRESHOLD` | `5` | Claude instructed to use 168h duration and recommend permanent block. Discord shows 🔴 REPEAT OFFENDER. |
| Events per hour | `HIGH_VOLUME_THRESHOLD` | `50` | Same escalation, triggered by current-hour connection volume regardless of history. |

**Why these defaults**: 5 lifetime blocks means the IP has returned on 5 separate days after
each previous 24h block — clearly a persistent threat. 50 hourly events indicates an active,
aggressive scan in progress. Either signal is sufficient to recommend permanent listing.

Claude's action prompt surfaces both signals explicitly:
```
Block history:   ⚠️ REPEAT OFFENDER — blocked 7 time(s) previously.
                 Consider recommending permanent block list addition.
Events (1h):     ⚠️ HIGH VOLUME — 73 events in the last hour.
                 Actively hammering the network. Consider recommending permanent block.
```

The outcome notification in Discord also calls out repeat offenders:
```
✅ Action Completed — 1.2.3.4
Added `1.2.3.4/32` to `AutoAgent_Block_v4` (TTL=168h ...) — ⚠️ 6x blocked total
(repeat offender — consider adding to a permanent block list)
```

---

## Claude Action Proposal

File: `services/automation-agent/app/analysis/claude_action.py`

**Model:** `claude-haiku-4-5-20251001`
**Max tokens:** 800

**Input context provided to Claude:**
- Threat intel data (score, org, country, abuse score, OTX pulses, GreyNoise class)
- Block history: lifetime block count with repeat-offender flag if ≥ `REPEAT_OFFENDER_THRESHOLD`
- Hourly events with high-volume flag if ≥ `HIGH_VOLUME_THRESHOLD`
- Pre-action VictoriaMetrics baseline metrics
- Excerpt from threat-intel narrative (executive summary)
- Safety rules (hard constraints listed explicitly)
- Duration guidelines (first sighting vs persistent vs repeat offender)

**Output schema:**
```json
{
  "type": "pfblocker_add" | "no_action",
  "target_list": "AutoAgent_Block_v4",
  "value": "x.x.x.x/32",
  "reason": "concise reason citing specific intel data and block history",
  "duration_hours": 24,
  "confidence": "high" | "medium" | "low",
  "notes": "any caveats or recommended follow-up steps"
}
```

**Duration escalation logic:**
- Borderline score: 12 hours
- First sighting, high score: 24 hours
- Persistent bad actor (OTX pulses > 5, abuse > 70): 72 hours
- Repeat offender (≥5 blocks) OR high volume (≥50/h): 168 hours + `recommend_permanent_block: true` in notes

The raw prompt text is committed verbatim to the GAIT audit trail as `02_claude_prompt.txt`.

---

## GAIT Audit Trail

Every automation session creates a dedicated git branch in the `automation-audit` Docker volume,
mounted at `/app/audit-repo` inside the container.

### Branch structure

Every automation session creates one git branch from `main`. For human-approved sessions the
trail is split across two branches — the scheduler creates the first, the approval handler
creates the second.

**Auto-approve sessions** (score ≥ `AUTO_APPROVE_THRESHOLD`): single branch, 8 turns.

```
automation-20260225-143021-1-2-3-4/
    ├── 00_input.json             Threat intel data + block_count + config snapshot
    ├── 01_baseline.json          VictoriaMetrics metrics snapshot before any action
    ├── 02_claude_prompt.txt      Exact text prompt sent to Claude (verbatim)
    ├── 03_proposed_action.json   Claude's structured JSON response
    ├── 04_decision.json          auto_approve decision + score
    ├── 05_execution_result.json  pfSense action result (method, success, message)
    ├── 06_verification.json      Post-action metric diff (before/after/pct_change)
    └── 07_outcome.json           Final sealed outcome with timestamp
```

**Human-approved sessions** (score in `[AUTO_ACTION_THRESHOLD, AUTO_APPROVE_THRESHOLD)`):
two branches. Original branch stops at turn 04 (`decision: pending_approval`). On approval a
new `-approved` branch is created and the execution trail is recorded there.

```
automation-20260225-143021-1-2-3-4/          ← scheduler branch (turns 00–04)
    ├── 00_input.json
    ├── 01_baseline.json
    ├── 02_claude_prompt.txt
    ├── 03_proposed_action.json
    └── 04_decision.json                     decision: pending_approval

automation-20260225-143021-1-2-3-4-approved/ ← approval branch (turns 00–03)
    ├── 00_approval.json                     who approved, when, via discord/api
    ├── 01_execution_result.json             pfSense action result
    ├── 02_verification.json                 post-action metric diff
    └── 03_outcome.json                      final sealed outcome
```

The `-approved` branch name convention is the same whether approval comes from the Discord bot
(`/approve`, `/approve-all`) or the REST API (`POST /api/automation/approve/{id}`).

### Inspecting the audit trail

```bash
# List all automation sessions (including -approved branches)
docker exec convergence-automation-agent \
  git -C /app/audit-repo branch -a

# Review a specific scheduler session (turns 00–04)
docker exec convergence-automation-agent \
  git -C /app/audit-repo checkout automation-20260225-143021-1-2-3-4

# Read what Claude proposed
docker exec convergence-automation-agent \
  cat /app/audit-repo/sessions/automation-20260225-143021-1-2-3-4/03_proposed_action.json

# Read the execution result for a human-approved session
docker exec convergence-automation-agent \
  git -C /app/audit-repo checkout automation-20260225-143021-1-2-3-4-approved
docker exec convergence-automation-agent \
  cat /app/audit-repo/sessions/automation-20260225-143021-1-2-3-4-approved/01_execution_result.json

# See the full decision chain across both branches
docker exec convergence-automation-agent \
  git -C /app/audit-repo log --oneline automation-20260225-143021-1-2-3-4
docker exec convergence-automation-agent \
  git -C /app/audit-repo log --oneline automation-20260225-143021-1-2-3-4-approved

# Show all sessions that were actually executed (have an -approved branch)
docker exec convergence-automation-agent \
  git -C /app/audit-repo branch | grep '\-approved'

# Inspect the audit repo directly from the host (even when the container is down)
docker run --rm -v convergence-automation-audit:/audit --entrypoint /bin/sh alpine/git -c \
  "git -C /audit branch | grep approved | wc -l"
```

---

## Prometheus Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `automation_actions_total` | Counter | `status` (dry_run, pending, success, fail, skipped) | Total action decisions |
| `automation_session_duration_seconds` | Histogram | — | Wall-clock time per full session |
| `automation_pending_approvals` | Gauge | — | Sessions awaiting human approval |
| `automation_last_poll_timestamp_seconds` | Gauge | — | Unix time of last threat-intel poll |
| `automation_qualifying_ips_total` | Counter | — | IPs that met the action threshold |
| `automation_rate_limited_total` | Counter | — | Actions skipped due to hourly rate limit |
| `automation_audit_commits_total` | Counter | — | GAIT git commits written |

---

## Grafana Dashboard

Dashboard: `dashboards/automation/automation-agent.json`
Folder: **Automation**
Datasources: `AutomationAgent` (Infinity UID `automation-agent`) + VictoriaMetrics

| Row | Panels | Datasource |
|---|---|---|
| Summary | Total actions by status (stat), pending count, last poll, dry-run indicator | VictoriaMetrics + Infinity |
| Recent Sessions | Sessions table (session_id, ip, score, action, status, timestamp) | Infinity |
| Pending Approvals | Pending table with session ID, expiry countdown | Infinity |
| Metrics Timeseries | `automation_actions_total` by status, session duration histogram | VictoriaMetrics |
| Audit Trail | GAIT branch list (branch name, last commit message, committed_at) | Infinity |

---

## Deployment

### First-time setup

```bash
# 1. Set required vars in .env:
#    ANTHROPIC_API_KEY, DISCORD_WEBHOOK_URL, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID
#    PFSENSE_HOST, PFSENSE_XMLRPC_USER, PFSENSE_XMLRPC_PASS
#    DRY_RUN=false (when ready for live mode)

# 2. Build and start
docker compose up -d --build automation-agent

# 3. Restart VictoriaMetrics to pick up new scrape job
docker compose restart victoriametrics

# 4. Force-recreate Grafana to load new datasource + dashboard
docker compose up -d --force-recreate grafana

# 5. Create pfSense alias + block rule (run once)
curl -s -X POST http://localhost:8002/api/automation/setup-pfsense | python3 -m json.tool

# 6. Verify health
curl http://localhost:8002/health | python3 -m json.tool
```

### After making changes

| Change | Command |
|---|---|
| Python code | `docker compose build automation-agent && docker compose up -d automation-agent` |
| Safety settings (DRY_RUN, thresholds) | `docker compose restart automation-agent` |
| `.env` credentials | `docker compose restart automation-agent` |
| Dashboard JSON | Auto-reloads in 30 seconds — no restart needed |
| Datasource YAML | `docker compose up -d --force-recreate grafana` |

---

## Verification

```bash
# Service health + config summary
curl http://localhost:8002/health | python3 -m json.tool
# → dry_run: false, discord_configured: true, pfsense_configured: true

# Check poll ran (45s after startup)
docker logs convergence-automation-agent --tail 30

# Pending approvals
curl http://localhost:8002/api/automation/pending | python3 -m json.tool

# Recent sessions
curl http://localhost:8002/api/automation/report | python3 -m json.tool

# Prometheus metrics being scraped
curl -s 'http://localhost:8428/api/v1/query?query=automation_actions_total' | \
  python3 -c "import sys,json; [print(r['metric'], r['value'][1]) for r in json.load(sys.stdin)['data']['result']]"

# Block counts in Redis (inspect repeat offenders)
docker exec convergence-redis redis-cli -n 1 KEYS 'automation:block_count:*'
docker exec convergence-redis redis-cli -n 1 GET 'automation:block_count:1.2.3.4'

# GAIT audit branches
docker exec convergence-automation-agent \
  git -C /app/audit-repo branch | head -20

# Rate limiter status
curl http://localhost:8002/health | python3 -c "
import sys,json; h=json.load(sys.stdin)
r=h['rate_limit']
print(f'Actions this hour: {r[\"actions_last_hour\"]}/{r[\"max_actions_per_hour\"]} (remaining: {r[\"remaining\"]})')"
```

---

## Troubleshooting

### Discord alerts firing repeatedly for the same IP

**Cause**: The `mark_ip_processed()` call was absent from the pending-approval path in early
versions. Each 10-minute poll cycle would re-evaluate already-pending IPs and send a new alert.

**Fixed in current version**: `mark_ip_processed(ip, ttl_hours=4)` is called immediately after
adding a session to `pending_approvals`. An in-memory dedup check (`already_pending`) also
catches the case where Redis keys are cleared by a container restart.

**If still occurring after update**: check that the container is running the latest image:
```bash
docker compose build automation-agent && docker compose up -d automation-agent
```

---

### `/approve-all` only adds 1 of N IPs to pfSense alias

**Cause**: Concurrent `execute_and_verify()` tasks all called `_xmlrpc_alias_add()` simultaneously.
Each independently read the same initial alias state from pfSense, added its one IP, and wrote
back — last writer wins, others' additions are discarded.

**Fixed in current version**: `_xmlrpc_write_lock` (module-level `asyncio.Lock`) serialises all
alias add and delete operations so each read-modify-write cycle completes fully before the next begins.

---

### "Setup failed: timed out" from setup endpoint

**Cause**: `PFSENSE_HOST` is unreachable. pfSense may not have a firewall rule allowing access
from the automation-agent container's host IP on the GUI port.

**Fix**:
1. Verify the port: `curl -k https://192.168.1.1/xmlrpc.php` (default 443; may be 440 or custom)
2. Set `PFSENSE_HOST=192.168.1.1:440` if using a non-standard port
3. Add a pfSense firewall rule allowing HTTPS from the agent host IP
4. Test with: `curl -k -u admin:pass -X POST https://192.168.1.1:440/xmlrpc.php`

---

### "Authentication failed" from setup endpoint

**Cause A**: Wrong username. XML-RPC exec_php requires the `admin` user (not a custom account).
Set `PFSENSE_XMLRPC_USER=admin`.

**Cause B**: Wrong password. Verify against the pfSense web UI login. Note: the XML-RPC path uses
HTTP Basic Auth via httpx, so special characters (`@`, `#`, etc.) in passwords are handled correctly.

---

### "not well-formed (invalid token)" XML parse error

This error should not appear in the current version. It was caused by pfSense prepending PHP echo
output before the XML-RPC envelope, which broke `xmlrpc.client`. The current `_xmlrpc_exec_php()`
function uses httpx and manual XML extraction.

If it reappears: check for PHP warnings/errors being echoed by pfSense before the XML response.
The function splits on `<?xml` and only parses from that offset forward.

---

### "Alias 'X' not found in pfSense config"

**Cause**: The alias name in `.env` (`PFSENSE_FIREWALL_ALIAS`) doesn't match what exists in pfSense, or the alias hasn't been created yet.

**Fix**: Run the setup endpoint once:
```bash
curl -s -X POST http://localhost:8002/api/automation/setup-pfsense | python3 -m json.tool
```
This creates `AutoAgent_Block_v4` (or whatever `PFSENSE_FIREWALL_ALIAS` is set to) idempotently.

---

### Approved IPs not appearing in pfSense alias

**Symptom**: Discord bot responds "Approved — executing in background" but the `AutoAgent_Block_v4`
alias in pfSense never grows. No red "Action Failed" notifications appear in Discord either.

**Cause A (most common): Alias doesn't exist in pfSense.**
The XML-RPC PHP code searches for the alias by name and echoes `alias_not_found` if it's missing.
This raises a `RuntimeError` that falls through to the SSH path, which also fails (see Cause B).
All paths fail → `execute_pfblocker_add` returns `success=False` → a red "Action Failed" Discord
webhook is sent → if you're not monitoring that channel, it looks like silence.

**Fix**: Run the setup endpoint once before going live — it creates the alias and WAN block rule
idempotently via XML-RPC:
```bash
curl -s -X POST http://localhost:8002/api/automation/setup-pfsense | python3 -m json.tool
# Expected: {"alias": "created", "rule": "created", "success": true}
# Or:       {"alias": "exists",  "rule": "exists",  "success": true}
```

**Cause B: SSH key path not mounted in container.**
`PFSENSE_SSH_KEY_PATH` must be a path **inside the container**. The automation-agent only mounts
one volume (`automation-audit:/app/audit-repo`). A path like
`PFSENSE_SSH_KEY_PATH=/home/ubuntu/.ssh/id_ed25519` refers to the host filesystem, which is not
visible inside the container — paramiko will fail immediately with a file-not-found error.

**Fix**: Either mount the key explicitly in `docker-compose.yml`:
```yaml
automation-agent:
  volumes:
    - automation-audit:/app/audit-repo
    - /home/ubuntu/.ssh/pfsense_id_ed25519:/app/secrets/pfsense_id_ed25519:ro
```
Then set `PFSENSE_SSH_KEY_PATH=/app/secrets/pfsense_id_ed25519`. Or simply leave
`PFSENSE_SSH_KEY_PATH` empty to disable the SSH path entirely — XML-RPC is the recommended path.

**Cause C: GAIT audit trail previously hid these failures.**
Prior to 2026-03-02, Discord bot approvals passed `session=None` to `execute_and_verify()`,
meaning execution results were never committed to GAIT. A failure would send a Discord webhook
notification but leave no trace in the git audit trail. After the fix, check the `-approved`
branch for the session to see `01_execution_result.json` with the specific error message.

**Diagnosis after fix** (with container running):
```bash
# Check logs for the actual failure reason during an approval
docker logs -f convergence-automation-agent | grep -E "xmlrpc|alias|execution|failed|FAILED"

# Check a recent -approved branch for the execution result
docker exec convergence-automation-agent \
  git -C /app/audit-repo branch | grep approved | tail -5
```

---

### No sessions appearing after startup

**Cause A**: threat-intel service hasn't completed its first enrichment cycle (runs ~45s after
startup). The automation-agent also waits 45s before its first poll.

**Check**: `curl http://localhost:8001/health` — `report_available` must be `true`.

**Cause B**: No IPs qualify — all scores are below `AUTO_ACTION_THRESHOLD=80`.

**Check**: `curl http://localhost:8001/api/infinity/blocked_ips | python3 -c "import sys,json; print(max(r['score'] for r in json.load(sys.stdin)))"`

---

### Approval session not found (404)

**Cause A**: Session expired (4-hour TTL). Check `/api/automation/pending` for current sessions.

**Cause B**: Session was already approved or rejected.

**Cause C**: Service restarted — `pending_approvals` is in-memory. A restart clears all pending
sessions. The next poll cycle will re-evaluate the same IPs and create new sessions (with new
session IDs) thanks to `mark_ip_processed` — the re-evaluation triggers after the 4h TTL expires.

---

### `audit_trail_initialized: false` in /health

**Cause**: Git binary missing or audit volume permissions issue.

**Check**: `docker exec convergence-automation-agent git version`

**Fix**: `docker compose build --no-cache automation-agent` (Dockerfile installs git via apt).

---

## Known Limitations

- **`pending_approvals` is in-memory**: A container restart clears all pending sessions. On the
  next poll cycle (after the 4h `mark_ip_processed` TTL expires), the same IPs will generate fresh
  sessions with new session IDs. Future improvement: persist to Redis with TTL keys.
- **SSH fallback is runtime-only**: `pfctl -T add` entries do not survive a reboot or pfSense
  config reload. SSH is intended for emergency use; XML-RPC alias mode is the recommended path.
  Additionally, `PFSENSE_SSH_KEY_PATH` must reference a path inside the container — only the
  `automation-audit` volume is mounted by default. Mount the key explicitly in `docker-compose.yml`
  if the SSH path is needed (see Troubleshooting).
- **Verification is informational**: Post-action metric comparison is recorded in the audit trail
  but does not trigger automatic rollback. pfBlockerNG blocks may *decrease* block event count
  (pfB drops before pf logs), which looks like "not effective" but is the correct outcome.
- **Permanent block list**: Repeat-offender detection flags IPs for permanent listing and
  recommends it in Claude's output and Discord notifications, but does not automatically manage
  a separate permanent alias. That step requires manual action in pfSense.

---

## Next Steps (Phase 6 ideas)

- **Persist pending approvals in Redis** — Survive container restarts cleanly; add expiry scanning.
- **Permanent block alias** — Add a second pfSense alias (`AutoAgent_Permanent_Block_v4`) and a
  `/promote-permanent` Discord command / API endpoint that moves a repeat offender from the temp
  alias to the permanent one.
- **LangGraph multi-step agent** — The current `poll_cycle → propose_action → execute_and_verify`
  flow maps directly to a LangGraph state machine. Upgrade for multi-hop reasoning (e.g.:
  "check VirusTotal → check NVD for device CVEs → propose action → verify").
- **Dynamic anomaly baselines** — Replace fixed `AUTO_ACTION_THRESHOLD` with VictoriaMetrics
  `outlier_iqr_over_time()` to adapt to your network's traffic baseline.
- **NVD CVE enrichment** — When pfSense firmware version is known (from SNMP), query the
  free NVD API for CVEs affecting that version and include in the Claude prompt.
- **pfBlockerNG DNSBL integration** — Extend `PfBlockerAction` with a `dnsbl_add` type to
  block malicious domains at the DNS level in addition to IP blocking.
