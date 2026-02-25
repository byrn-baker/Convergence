# Phase 5: Event-Driven Automation Agent

**Last Updated:** 2026-02-25
**Status:** Implemented (DRY_RUN mode — pfSense integration stubs ready for credentials)

---

## Overview

Phase 5 adds a `automation-agent` microservice that turns high-risk threat-intel signals into
auditable, human-gated (or auto-approved) pfSense blocking actions. The core design principle is
**fail-closed with a complete paper trail**: every decision the AI makes is committed to an
immutable git repository before any action is attempted, and `DRY_RUN=true` is the default.

1. **GAIT Audit Trail** — Every automation session creates a dedicated git branch with sequential
   JSON "turn" files recording exactly what data the AI saw, what prompt it received, what it
   decided, and what happened. This is the forensic record that answers "what did the AI do
   and why" indefinitely.
2. **Human Gating** — Actions scoring below `AUTO_APPROVE_THRESHOLD` (default 95) are sent to
   Discord as rich embeds with an approval URL. A human POSTs to approve or DELETEs to reject.
   The session waits up to 4 hours before expiring.
3. **Pre/Post Baseline Verification** — Before any action, VictoriaMetrics metrics are captured
   for the target IP. After execution, the service waits 5 minutes and re-queries to measure
   whether the action was effective.
4. **Redis Rate Limiting** — A sliding 60-minute window prevents more than `MAX_ACTIONS_PER_HOUR`
   live actions regardless of how many high-risk IPs appear.
5. **pfBlockerNG Integration Stubs** — Two execution paths (XML-RPC and SSH via paramiko) are
   wired up with clearly-marked TODO blocks. DRY_RUN mode logs the exact commands that would run.

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
    ├─ Rate limit check (>5/hour? skip)
    │
    ├─ Open GAIT session → git branch automation-{ts}-{ip}
    │   ├─ Turn 00: input.json         (threat data + config snapshot)
    │   ├─ Turn 01: baseline.json      (VM PromQL snapshot)
    │   ├─ Turn 02: claude_prompt.txt  (exact prompt sent to Claude)
    │   ├─ Turn 03: proposed_action.json (Claude JSON response)
    │   ├─ Turn 04: decision.json      (dry_run / pending / auto_approve)
    │   ├─ Turn 05: execution_result.json
    │   ├─ Turn 06: verification.json  (post-action metric diff)
    │   └─ Turn 07: outcome.json       (sealed)
    │
    ├─ DRY_RUN=true → log + Discord blue embed → done
    ├─ score < 95    → Discord orange embed → park in pending_approvals{}
    │                  POST /api/automation/approve/{id} to execute
    └─ score >= 95   → execute immediately → wait 5 min → verify → rollback on fail
            │
            ▼
    pfSense / pfBlockerNG (XML-RPC primary, SSH fallback)
    pfctl -t pfBlockerNG_AutoAgent_v4 -T add {cidr}

    Prometheus metrics → scraped by VictoriaMetrics every 30s
    Grafana Infinity → /api/infinity/sessions|pending|audit
```

---

## File Inventory

### New files

```
services/automation-agent/
├── Dockerfile                         python:3.12-slim + git binary
├── requirements.txt                   fastapi, apscheduler, gitpython, paramiko, redis, anthropic
└── app/
    ├── main.py                        FastAPI app — 13 endpoints
    ├── scheduler.py                   APScheduler 10-min poll + per-IP session orchestration
    ├── config.py                      Pydantic-settings env var config (all safety knobs)
    ├── state.py                       Module-level latest_report + pending_approvals dict
    ├── metrics.py                     7 Prometheus metrics definitions
    ├── audit/
    │   └── git_trail.py               GitAuditTrail + AuditSession (gitpython branch-per-session)
    ├── actions/
    │   ├── baseline.py                capture_baseline() + verify_action() via PromQL
    │   ├── pfblocker.py               PfBlockerAction + execute/rollback (XML-RPC + SSH stubs)
    │   ├── rate_limiter.py            Redis sliding-window rate limiter + IP dedup TTL
    │   └── executor.py                execute_and_verify() — shared by scheduler + approve EP
    ├── analysis/
    │   └── claude_action.py           Action-proposal prompt builder + Claude Haiku call
    └── notifications/
        └── discord.py                 Rich embeds: approval-required + outcome (success/fail/dry)

config/grafana/provisioning/datasources/automation-agent.yaml
dashboards/automation/automation-agent.json
docs/PHASE5_AUTOMATION_AGENT.md  (this file)
```

### Modified files

```
docker-compose.yml                     Added automation-agent service + automation-audit volume
config/victoriametrics/prometheus.yml  Added automation-agent scrape job
.env / .env.example                    Added PFSENSE_*, DRY_RUN, AUTO_*_THRESHOLD, safety vars
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health, dry_run flag, config summary, rate limit status |
| GET | `/metrics` | Prometheus metrics (scraped by VictoriaMetrics) |
| GET | `/api/automation/report` | Full in-memory session report (last 100 sessions) |
| GET | `/api/automation/pending` | Sessions awaiting human approval (pruning expired) |
| POST | `/api/automation/approve/{id}` | Approve a pending session → execute in background |
| DELETE | `/api/automation/approve/{id}` | Reject a pending session → no action taken |
| GET | `/api/automation/audit` | Recent GAIT git branches summary |
| GET | `/api/infinity/sessions` | Recent sessions flat array (Grafana Infinity) |
| GET | `/api/infinity/pending` | Pending approvals flat array (Grafana Infinity) |
| GET | `/api/infinity/audit` | Audit trail branch list flat array (Grafana Infinity) |

---

## Environment Variables

Add to `.env` before enabling live mode. All safety variables default to the most conservative values.

### pfSense Integration

| Variable | Default | Description |
|---|---|---|
| `PFSENSE_HOST` | *(empty)* | pfSense management IP (e.g. `192.168.1.1`) |
| `PFSENSE_XMLRPC_USER` | `admin` | pfSense web UI username |
| `PFSENSE_XMLRPC_PASS` | *(empty)* | pfSense web UI password |
| `PFSENSE_SSH_HOST` | *(empty)* | pfSense SSH host (falls back to `PFSENSE_HOST`) |
| `PFSENSE_SSH_USER` | `admin` | pfSense SSH username |
| `PFSENSE_SSH_KEY_PATH` | `/app/secrets/pfsense_id_ed25519` | Path to private key inside container |

### Safety Controls

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `true` | **Master kill-switch.** `true` = log everything, touch nothing |
| `AUTO_ACTION_THRESHOLD` | `80` | Minimum `composite_score` to even consider a block |
| `AUTO_APPROVE_THRESHOLD` | `95` | Score above which Discord approval is skipped |
| `MAX_ACTIONS_PER_HOUR` | `5` | Hard cap on live actions per rolling 60-minute window |
| `BLOCK_TTL_HOURS` | `24` | Temporary block duration (pfBlockerNG list TTL) |
| `POLL_INTERVAL_SECONDS` | `600` | How often to poll threat-intel (10 minutes) |

> **Setting `AUTO_APPROVE_THRESHOLD=101`** effectively disables auto-approve entirely — every
> qualifying action requires a human to POST the approval URL.

---

## Safety Model

The service is designed to be safe by default and require explicit opt-in for each escalation step:

```
DRY_RUN=true (default)
    └─ Logs everything. Discord blue embed. No pfSense changes. Ever.

DRY_RUN=false + score in [80, 95)
    └─ Discord orange embed with approval URL.
       Human must POST /api/automation/approve/{id}.
       Session expires after 4 hours with no action if not approved.

DRY_RUN=false + score >= 95 (auto-approve)
    └─ Action executes automatically.
       Baseline captured → action applied → 5 min wait → metrics verified.
       Rollback attempted if execution fails.
       Discord green/red outcome embed always sent.

All paths:
    └─ GAIT git branch committed at every step.
       Redis rate limit enforced (MAX_ACTIONS_PER_HOUR).
       IP dedup TTL prevents re-processing the same IP within 4h (no-action) or BLOCK_TTL_HOURS (block).
```

### False Positive Guards

Claude's action-proposal prompt includes hard constraints Claude must follow:
- `likely_false_positive = true` → must return `type: "no_action"`
- Score below threshold → must return `type: "no_action"`
- RFC 1918 private IPs → never block
- Known CDN/infrastructure orgs (Cloudflare, Akamai, Google, Apple, Microsoft) → never block unless `abuse_score > 80`
- Outbound traffic → only propose block if score > 85 AND abuse score > 60

---

## GAIT Audit Trail

Every automation session creates a dedicated git branch in the `automation-audit` Docker volume,
mounted at `/app/audit-repo` inside the container.

### Branch structure

```
automation-audit/ (git repo)
├── README.md                         Repo documentation + query examples
└── sessions/
    └── automation-20260225-143021-1-2-3-4/
        ├── 00_input.json             Threat intel data + config snapshot that triggered session
        ├── 01_baseline.json          VictoriaMetrics metrics snapshot before any action
        ├── 02_claude_prompt.txt      Exact text prompt sent to Claude (verbatim)
        ├── 03_proposed_action.json   Claude's structured JSON response
        ├── 04_decision.json          dry_run / pending / auto_approve decision + rationale
        ├── 05_execution_result.json  pfSense action result (method, success, message, rollback_cmd)
        ├── 06_verification.json      Post-action metric diff (before/after/pct_change per metric)
        └── 07_outcome.json           Final sealed outcome (success/fail + timestamp)
```

### Inspecting the audit trail

```bash
# List all automation sessions
docker exec convergence-automation-agent \
  git -C /app/audit-repo branch -a

# Review a specific session's turns
docker exec convergence-automation-agent \
  git -C /app/audit-repo checkout automation-20260225-143021-1-2-3-4

docker exec convergence-automation-agent \
  ls /app/audit-repo/sessions/automation-20260225-143021-1-2-3-4/

# Read what Claude proposed
docker exec convergence-automation-agent \
  cat /app/audit-repo/sessions/automation-20260225-143021-1-2-3-4/03_proposed_action.json

# See the full decision chain
docker exec convergence-automation-agent \
  git -C /app/audit-repo log --oneline automation-20260225-143021-1-2-3-4
```

---

## pfSense Integration

### Current state: stubs ready, credentials not yet wired

The service has two execution paths. Both are implemented as stub functions with detailed
TODO blocks explaining exactly what to add. DRY-run mode logs the exact `pfctl` command
that would execute.

**Target pfBlockerNG list:** `pfBlockerNG_AutoAgent_v4`

This list must be created in pfBlockerNG before enabling live mode:
> pfBlockerNG → IP → IPv4 → Custom → Add → Name: `pfBlockerNG_AutoAgent_v4`

### Path A — XML-RPC (preferred)

File: `services/automation-agent/app/actions/pfblocker.py:_xmlrpc_add()`

Uses pfSense's built-in XML-RPC interface at `/xmlrpc.php`. Calls `exec_php` to append
the CIDR to `/var/db/pfblockerng/custom/pfBlockerNG_AutoAgent_v4.txt` and trigger
`pfb_sync()`. Requires `PFSENSE_XMLRPC_PASS` to be set.

### Path B — SSH fallback (paramiko)

File: `services/automation-agent/app/actions/pfblocker.py:_ssh_add()`

Connects via SSH and runs:
```bash
pfctl -t pfBlockerNG_AutoAgent_v4 -T add {cidr}
```
This adds to the runtime pf table immediately (effective in < 1 second) but does **not**
persist across pfBlockerNG reloads. Best for short-TTL emergency blocks.

### SSH key setup

```bash
# Generate a dedicated key (do not reuse your admin key)
ssh-keygen -t ed25519 -f pfsense_autoagent_ed25519 -C "convergence-autoagent" -N ""

# Add the public key to pfSense:
# System > User Manager > admin > Authorized SSH Keys
cat pfsense_autoagent_ed25519.pub

# Mount the private key into the container via docker-compose.yml:
# volumes:
#   - ./secrets/pfsense_autoagent_ed25519:/app/secrets/pfsense_id_ed25519:ro
```

### Enabling live mode

```bash
# 1. Create the pfBlockerNG list in the pfSense UI
# 2. Set credentials in .env:
PFSENSE_HOST=192.168.1.1
PFSENSE_XMLRPC_PASS=your_pfsense_password
DRY_RUN=false

# 3. Rebuild and restart
docker compose build automation-agent
docker compose up -d --force-recreate automation-agent
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
| Summary | Total actions by status (stat), pending count (stat), last poll (stat), dry-run indicator | VictoriaMetrics + Infinity |
| Recent Sessions | Sessions table (session_id, ip, score, action, status, timestamp) | Infinity |
| Pending Approvals | Pending table with approve URL, expiry countdown | Infinity |
| Metrics Timeseries | `automation_actions_total` by status, session duration histogram | VictoriaMetrics |
| Audit Trail | GAIT branch list (branch name, last commit message, committed_at) | Infinity |

---

## Claude Action Proposal

The automation agent uses a separate, tighter prompt than the threat-intel narrative generator.
It asks for ONE structured JSON action and enforces hard safety rules.

**Model:** `claude-haiku-4-5-20251001`
**Max tokens:** 800

**Input context provided to Claude:**
- Full threat intel data (score, org, country, abuse score, OTX pulses, GreyNoise class)
- Pre-action VictoriaMetrics baseline metrics
- Excerpt from threat-intel narrative (executive summary)
- Safety rules (hard constraints listed explicitly)
- Duration guidelines (persistent vs first-sighting)

**Output schema:**
```json
{
  "type": "pfblocker_add" | "no_action",
  "target_list": "pfBlockerNG_AutoAgent_v4",
  "value": "x.x.x.x/32",
  "reason": "concise reason citing specific intel data",
  "duration_hours": 24,
  "confidence": "high" | "medium" | "low",
  "notes": "any caveats or recommended follow-up"
}
```

The raw prompt text is committed verbatim to the GAIT audit trail as `02_claude_prompt.txt` so
there is a permanent record of exactly what Claude was asked.

---

## Discord Approval Flow

```
1. Agent identifies qualifying IP (score ≥ 80, not FP)
2. Agent asks Claude for action proposal → pfblocker_add
3. Score < 95 → send "Approval Required" orange embed to Discord:
      ┌─────────────────────────────────────────────────┐
      │ ⚠️ Automation Approval Required — 1.2.3.4        │
      │ Composite Score: 87/100  Threat Level: HIGH      │
      │ Organization: Tamatiya EOOD  Country: BG         │
      │ Proposed Action: pfblocker_add                   │
      │ CIDR to Block: 1.2.3.4/32                        │
      │ Reason: AbuseIPDB 91%, 8 OTX pulses, GN=malicious│
      │ To Approve: POST http://host:8002/api/automation/ │
      │             approve/20260225-143021-1-2-3-4       │
      └─────────────────────────────────────────────────┘
4. Human reviews threat data independently, then:
      Approve: curl -X POST http://localhost:8002/api/automation/approve/20260225-...
      Reject:  curl -X DELETE http://localhost:8002/api/automation/approve/20260225-...
5. On approve: execution starts in background → outcome embed sent
6. Session expires after 4 hours with no action if ignored
```

> **Discord bots vs webhooks**: Discord webhooks are one-directional. The approval mechanism
> uses a REST endpoint on the automation-agent itself — not a Discord reply. A future iteration
> could add a Discord bot to handle `/approve session_id` slash commands in-channel.

---

## Deployment

### First-time setup

```bash
# 1. Ensure ANTHROPIC_API_KEY and DISCORD_WEBHOOK_URL are set in .env
# 2. Build and start (DRY_RUN=true is the default)
docker compose up -d --build automation-agent

# 3. Restart VictoriaMetrics to pick up new scrape job
docker compose restart victoriametrics

# 4. Force-recreate Grafana to load new datasource + dashboard
docker compose up -d --force-recreate grafana

# 5. Verify service health
curl http://localhost:8002/health | python3 -m json.tool
```

### After making changes

| Change | Command |
|---|---|
| Python code | `docker compose build automation-agent && docker compose up -d --force-recreate automation-agent` |
| Safety settings (DRY_RUN, thresholds) | `docker compose up -d --force-recreate automation-agent` |
| Dashboard JSON | Auto-reloads in 30 seconds — no restart needed |
| Datasource YAML | `docker compose up -d --force-recreate grafana` |

---

## Verification

```bash
# Service health + config summary
curl http://localhost:8002/health | python3 -m json.tool
# → dry_run: true, audit_trail_initialized: true, pending_approvals: 0

# Check first poll ran (45s after startup)
docker logs convergence-automation-agent --tail 30

# Pending approvals (should be empty in DRY_RUN)
curl http://localhost:8002/api/automation/pending | python3 -m json.tool

# Recent sessions
curl http://localhost:8002/api/automation/report | python3 -m json.tool

# Prometheus metrics being scraped
curl -s 'http://localhost:8428/api/v1/query?query=automation_actions_total' | \
  python3 -c "import sys,json; [print(r['metric'], r['value'][1]) for r in json.load(sys.stdin)['data']['result']]"

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

### No sessions appearing after startup

**Cause A**: threat-intel service hasn't completed its first enrichment cycle yet (runs ~45s
after startup). The automation-agent also waits 45s before first poll.

**Check**: `curl http://localhost:8001/health` → `report_available` must be `true`

**Cause B**: No IPs qualify — all scores are below `AUTO_ACTION_THRESHOLD=80`.

**Check**: `curl http://localhost:8001/api/infinity/blocked_ips | python3 -c "import sys,json; print(max(r['score'] for r in json.load(sys.stdin)))"` — compare to threshold.

---

### `audit_trail_initialized: false` in /health

**Cause**: Git initialization failed. The audit volume may have a permissions issue or the
git binary is missing from the container.

**Check**: `docker logs convergence-automation-agent | grep -i "GAIT"`

**Fix**: `docker exec convergence-automation-agent git version` — should print `git version 2.x.x`.
If missing: `docker compose build --no-cache automation-agent` (the Dockerfile installs git via apt).

---

### "Both execution methods failed" in logs

**Cause**: `DRY_RUN=false` is set but neither XML-RPC nor SSH stubs are implemented yet.

**Fix**: Keep `DRY_RUN=true` (the default) until the TODO blocks in `pfblocker.py` are filled
with real credentials and tested. The stubs raise `NotImplementedError` by design.

---

### Approval session not found (404) when POSTing to approve

**Cause A**: The session expired (4-hour TTL). Check `/api/automation/pending` for current sessions.

**Cause B**: The session was already approved or rejected.

**Cause C**: The service restarted — `pending_approvals` is an in-memory dict, not Redis-persisted.
A restart clears all pending sessions. (Future improvement: persist pending sessions to Redis.)

---

### Discord embeds not arriving

**Cause A**: `DISCORD_WEBHOOK_URL` is empty or incorrect.
**Check**: `curl http://localhost:8002/health | python3 -c "import sys,json; print(json.load(sys.stdin)['discord_configured'])"`

**Cause B**: `DRY_RUN=true` — in dry-run mode a Discord blue embed IS sent (to confirm the
agent is alive and finding threats). If even the dry-run embed is missing, check the webhook URL.

---

## Known Limitations

- **`pending_approvals` is in-memory**: A container restart clears all pending sessions.
  Future improvement: persist to Redis with TTL keys.
- **One-directional Discord**: Approvals require a curl/HTTP call to the API, not a Discord reply.
  Future improvement: add a Discord bot with slash commands.
- **pfBlockerNG stubs**: XML-RPC and SSH paths raise `NotImplementedError`. Set `DRY_RUN=false`
  only after implementing the TODO blocks in `pfblocker.py` with real pfSense credentials.
- **SSH adds are not persistent**: SSH `pfctl -T add` writes to the runtime pf table, which
  is cleared on pfBlockerNG reload. XML-RPC writes to the list file and triggers a pfB sync,
  making the block persistent across reloads.
- **Verification is informational**: Post-action metric comparison is recorded in the audit
  trail but does not trigger rollback on its own. pfBlockerNG blocks may *decrease* the block
  event count (pfB drops before pf logs), which looks like "not effective" but is correct.

---

## Next Steps (Phase 6 ideas)

- **Implement real pfSense XML-RPC** — Fill in `_xmlrpc_add()` in `pfblocker.py` with live
  credentials; test against a pfSense lab instance; set `DRY_RUN=false`.
- **Persist pending approvals in Redis** — Survive container restarts; add expiry scanning.
- **Discord bot approval** — Replace curl-based approval with a Discord slash command bot
  that can approve sessions directly from the alert channel.
- **LangGraph multi-step agent** — The current `poll_cycle → propose_action → execute_and_verify`
  flow maps directly to a LangGraph state machine. Upgrade for multi-hop reasoning (e.g.:
  "check VirusTotal → check NVD for device CVEs → propose action → verify").
- **Dynamic anomaly baselines** — Replace fixed `AUTO_ACTION_THRESHOLD` with VictoriaMetrics
  `outlier_iqr_over_time()` to adapt to your network's traffic baseline.
- **NVD CVE enrichment** — When pfSense firmware version is known (from SNMP), query the
  free NVD API for CVEs affecting that version and include in the Claude prompt.
- **pfBlockerNG DNSBL integration** — Extend `PfBlockerAction` with a `dnsbl_add` type to
  block malicious domains at the DNS level in addition to IP blocking.
