# Convergence Platform - Project Status

**Last Updated:** 2026-02-25
**Current Phase:** Phase 5 — Event-Driven Automation Agent

---

## Phase Summary

| Phase | Name | Status | Completed |
|-------|------|--------|-----------|
| 1 | Core Observability Stack (SNMP, VictoriaMetrics, Grafana) | ✅ Complete | 2026-02-14 |
| 2 | pfSense Firewall Integration + GeoIP Enrichment | ✅ Complete | ~2026-02-15 |
| 3 | Alerting (Loki Rules + Grafana + Alertmanager) | ✅ Complete | ~2026-02-18 |
| 4 | AI Threat Intelligence Service | ✅ Complete | 2026-02-21 |
| **5** | **Event-Driven Automation Agent** | ✅ **Live** — XML-RPC alias, Discord bot, repeat-offender tracking | **2026-02-25** |

---

## Phase 5: Event-Driven Automation Agent — 2026-02-25

### What Was Built

A new `automation-agent` FastAPI microservice that polls threat-intel every 10 minutes, uses
Claude Haiku to propose pfSense blocking actions for high-risk IPs, gates on human Discord
approval (or auto-approves above a score threshold), and commits an immutable GAIT audit trail
to a dedicated git repository for every decision.

```
threat-intel (/api/infinity/blocked_ips + /api/report)
    ↓
automation-agent (FastAPI + APScheduler)   → http://localhost:8002
    ├─ Filter: score >= 80, known_bad_actor, not FP, not processed recently
    ├─ Redis: dedup + sliding-window rate limit + lifetime block count per IP
    ├─ GAIT audit trail: git branch per session, JSON turn files at every step
    ├─ Claude Haiku: action-proposal prompt with block history + volume flags
    ├─ DRY_RUN=false + score < 95: Discord bot approval (/approve /reject /approve-all)
    ├─ DRY_RUN=false + score >= 95: auto-execute → 5 min wait → verify → rollback on fail
    └─ pfSense executor: httpx XML-RPC transport → alias mode (write-serialised lock)
```

### New Services (post-Phase 5)

| Container | Port | Status |
|-----------|------|--------|
| convergence-automation-agent | 8002 | ✅ Running (DRY_RUN=false, live mode) |

Total services: **9** (+ automation-agent added to existing 8)

### Phase 5 Status

- **GAIT audit trail**: ✅ git branch-per-session with 8 sequential turn files
- **Claude action proposals**: ✅ structured JSON with block history + escalation logic
- **Discord bot**: ✅ /approve /reject /approve-all /reject-all /pending slash commands
- **Rate limiting**: ✅ Redis sliding window (auto-approve) + IP dedup TTL
- **Re-alert prevention**: ✅ mark_ip_processed called in pending path; in-memory dedup backup
- **Repeat offender tracking**: ✅ Redis block count (1-year TTL), permanent block recommendation
- **Pre/post baseline verification**: ✅ VictoriaMetrics PromQL diff
- **pfSense XML-RPC**: ✅ httpx transport (bypasses pfSense PHP echo prepend issue)
- **pfSense alias mode**: ✅ plain Firewall Alias via PHP config API (no pfBlockerNG required)
- **Concurrent write safety**: ✅ asyncio.Lock serialises all alias read-modify-write cycles
- **Idempotent setup endpoint**: ✅ POST /api/automation/setup-pfsense creates alias + rule
- **Grafana dashboard**: ✅ Automation folder with sessions, pending, metrics, audit rows

### Config Required

| Variable | Required For |
|---|---|
| `DISCORD_WEBHOOK_URL` | Outcome notifications |
| `DISCORD_BOT_TOKEN` | Slash command approval flow |
| `DISCORD_GUILD_ID` | Instant command sync (vs ~1h global) |
| `PFSENSE_HOST` | Any pfSense path (include port if non-443, e.g. `192.168.1.1:440`) |
| `PFSENSE_XMLRPC_PASS` | XML-RPC alias mode (Path B, recommended) |
| `DRY_RUN=false` | Any real pfSense changes |

---

## Phase 4: AI Threat Intelligence — Completed 2026-02-21

### What Was Built

A new `threat-intel` FastAPI microservice enriches top blocked/outbound IPs with four threat intelligence APIs, generates AI threat narratives via Claude Haiku, and surfaces everything in a new Grafana "Threat Intelligence" dashboard.

```
VictoriaMetrics (firewall_events_total)
    │ PromQL — top 50 blocked + top 20 outbound IPs
    ▼
threat-intel (FastAPI + APScheduler)   → http://localhost:8001
    ├─ Startup + hourly enrichment job
    │   ├─ Redis cache check (24h TTL per IP)
    │   ├─ AbuseIPDB  /v2/check          (confidence score 0-100)
    │   ├─ GreyNoise  /v3/community/{ip} (malicious/benign/riot)
    │   ├─ OTX        /api/v1/indicators (threat pulse count)
    │   ├─ IPInfo     /{ip}              (country, org, ASN)
    │   ├─ Port analysis via Loki LogQL regexp extraction
    │   └─ Claude Haiku → structured JSON threat narrative
    ├─ GET /health         → {"status":"ok","report_available":true}
    ├─ GET /metrics        → Prometheus format → scraped by VictoriaMetrics
    ├─ GET /api/report     → full JSON threat report
    └─ GET /api/report/blocked|outbound → filtered JSON
```

### New Services (post-Phase 4)

| Container | Port | Status |
|-----------|------|--------|
| convergence-threat-intel | 8001 | ✅ Up |

Total services: **8** (+ threat-intel added to existing 7)

### Verified on 2026-02-21

- **50 blocked IPs enriched** with GreyNoise + IPInfo (malicious CNs, RUs, etc. correctly classified)
- **20 outbound IPs enriched**
- **84 IPs cached** in Redis with 24h TTL
- **440 Prometheus samples** scraped by VictoriaMetrics every 30s
- **10 threat_intel_* metrics** flowing (see full list in PHASE4_THREAT_INTELLIGENCE.md)
- **Claude Haiku narrative** working (`claude-haiku-4-5-20251001`, risk_level: low)
- **Infinity datasource** v3.7.1 installed and querying `/api/report`
- **"Threat Intelligence" dashboard** provisioned in Grafana

### API Keys Status

| Key | Status | Impact |
|-----|--------|--------|
| `ANTHROPIC_API_KEY` | ✅ Active | Claude narratives working |
| `GREYNOISE_API_KEY` | ⬜ Not set | Community API works (rate-limited to ~60/min) |
| `ABUSEIPDB_API_KEY` | ⬜ Not set | AbuseIPDB scores show 0 |
| `OTX_API_KEY` | ⬜ Not set | OTX pulse counts show 0 |
| `IPINFO_TOKEN` | ⬜ Not set | Country/org from GreyNoise fallback |

### Bugs Fixed During Deployment

1. **GreyNoise 429 rate limit**: 70 concurrent requests on startup triggered rate limiting. Fixed by adding `asyncio.Semaphore(3)` + 150ms inter-request delay in `greynoise.py`.
2. **Claude empty/fence-wrapped response**: Added empty-response detection with stop_reason logging, plus markdown code-fence stripping before JSON parse.

---

## Overview

The Convergence platform is a network monitoring, security, and AI intelligence system that integrates OpenTelemetry Collector (OTELCOL), Nautobot as the source of truth, VictoriaMetrics for time-series data, Loki for logs, and Grafana for visualization. It now includes AI-powered threat intelligence enrichment for firewall events.

---

## Current Architecture

### Core Components

1. **OpenTelemetry Collector (OTELCOL)**
   - SNMP receiver polling network devices
   - Auto-configured from Nautobot device inventory
   - Separate pipelines per device for proper metadata tagging
   - Exports to VictoriaMetrics via Prometheus Remote Write

2. **Nautobot (External)**
   - Single source of truth for network inventory
   - GraphQL API integration for efficient data retrieval
   - Provides device metadata: hostname, IP, vendor, model, role, site

3. **VictoriaMetrics**
   - Time-series database for metrics storage
   - 1-year retention period
   - Prometheus-compatible API

4. **Grafana**
   - Pre-built dashboards for network monitoring
   - Datasource: VictoriaMetrics (Prometheus-compatible)
   - Dashboards: Interface Utilization, Interface Errors, Network Overview, Platform Health

5. **Redis**
   - Supporting service (reserved for future agent coordination)

---

## Current Capabilities

### ✅ Implemented

1. **Automated Device Discovery**
   - Python script (`scripts/nautobot_device_discovery.py`) queries Nautobot GraphQL API
   - Generates OTEL Collector configuration with device-specific receivers and processors
   - Supports SSL verification toggle for self-signed certificates

2. **SNMP Monitoring**
   - Currently monitoring 2 Cisco switches (HomeSwitch01, HomeSwitch02)
   - Metrics collected:
     - System uptime
     - Interface traffic (in/out octets)
     - Interface errors
   - Real interface names (e.g., "GigabitEthernet1/0/1") instead of index numbers

3. **Rich Device Metadata**
   - Every metric tagged with:
     - `device.name`: Hostname from Nautobot
     - `device.ip`: Management IP address
     - `device.vendor`: Manufacturer (e.g., "Cisco")
     - `device.model`: Device model (e.g., "WS-C3850-48P")
     - `device.role`: Device role from Nautobot (e.g., "home_switch")
     - `device.site`: Location from Nautobot (e.g., "House")
     - `interface.name`: Actual interface name from SNMP

4. **Grafana Dashboards**
   - Interface Utilization: Traffic visualization in bps
   - Interface Errors: Error rates and accumulation
   - Network Overview: Device and interface counts
   - Platform Health: System-level metrics
   - All dashboards auto-load on Grafana startup

---

## Recent Improvements

### GraphQL Integration (2026-02-14)

**Problem Solved:**
Initial REST API approach required 5+ sequential API calls per device to fetch nested data (primary IP, device type, manufacturer, role, location, status).

**Solution:**
Replaced with single GraphQL query that retrieves all device data and relationships in one API call.

**Benefits:**
- 5-10x faster device discovery
- Cleaner, more maintainable code
- Reduced API load on Nautobot
- Eliminated cascading timeout failures

### Separate OTEL Pipelines (2026-02-14)

**Problem Solved:**
When multiple devices shared a single metrics pipeline with multiple attribute processors, all processors applied to all metrics, causing incorrect labeling (HomeSwitch01 metrics got HomeSwitch02 labels and vice versa).

**Solution:**
Created device-specific pipelines in OTEL Collector:
```yaml
metrics/homeswitch01:
  receivers: [snmp/homeswitch01]
  processors: [memory_limiter, attributes/homeswitch01, resource, batch]

metrics/homeswitch02:
  receivers: [snmp/homeswitch02]
  processors: [memory_limiter, attributes/homeswitch02, resource, batch]
```

**Benefits:**
- Each device's metrics get only its own metadata
- Clean label separation
- Scalable architecture for adding more devices

### Environment Variable Loading (2026-02-14)

**Problem Solved:**
Python scripts couldn't load `.env` file values, and existing shell environment variables took precedence over `.env` values.

**Solution:**
Added manual `.env` parsing with explicit override of existing environment variables:
```python
with open(env_path) as f:
    for line in f:
        # Parse and override existing env vars
        os.environ[key] = value
```

**Benefits:**
- No external dependencies (python-dotenv)
- `.env` values always take precedence
- Works in restricted environments

---

## Key Files

### Configuration
- `config/otel-collector/config.yaml` - OTEL Collector configuration (auto-generated sections)
- `.env` - Environment variables (API tokens, credentials, URLs)
- `.env.example` - Template for environment variables

### Scripts
- `scripts/nautobot_device_discovery.py` - Device discovery and config generation
- `validate_stack.sh` - Stack health validation
- `validate_nautobot.sh` - Nautobot integration validation

### Dashboards
- `dashboards/unified/interface-utilization.json` - Interface traffic dashboard
- `dashboards/unified/interface-errors.json` - Interface errors dashboard
- `dashboards/unified/network-overview.json` - Network summary dashboard
- `dashboards/unified/platform-health.json` - Platform monitoring dashboard

### Documentation
- `README.md` - Main project documentation
- `docs/NAUTOBOT_ENRICHMENT.md` - Nautobot integration guide
- `docs/PROJECT_STATUS.md` - This file

---

## Monitoring Data Flow

```
Network Devices (SNMP)
    ↓
OTEL Collector
    ├─ SNMP Receivers (per device)
    ├─ Attributes Processors (add Nautobot metadata)
    └─ Prometheus Remote Write Exporter
        ↓
VictoriaMetrics (Time-Series DB)
        ↓
Grafana Dashboards
```

---

## Current Deployment

### Environment
- Development mode
- Docker Compose orchestration
- 2 Cisco switches monitored
- Self-signed SSL certificate for Nautobot

### Access Points
- Grafana: http://localhost:3000 (admin/admin)
- VictoriaMetrics API: http://localhost:8428
- OTEL Collector Health: http://localhost:13133
- OTEL Collector Metrics: http://localhost:8888

### Data Retention
- VictoriaMetrics: 1 year
- OTEL Collector polling interval: 60 seconds

---

## Known Limitations

1. **Docker Health Checks**
   - OTEL Collector and VictoriaMetrics report "unhealthy" in `docker compose ps`
   - Both services are functionally healthy (verified via health endpoints)
   - Issue: Health check configuration overly strict

2. **SNMP Community String**
   - Currently using SNMPv2c with community string "public"
   - SNMPv3 credentials configured in `.env` but not yet used

3. **Single SNMP Community**
   - All devices must use the same SNMP community string
   - Enhancement needed: Per-device SNMP credentials

4. **Manual Config Updates**
   - After adding devices to Nautobot, must manually run discovery script
   - Enhancement needed: Automated config refresh

---

## Deployment Workflow

### Adding New Devices

1. **Add device to Nautobot:**
   - Create device in Nautobot web UI
   - Assign primary IPv4 address
   - Set device type, manufacturer, role, location
   - Ensure device status is "Active"

2. **Generate OTEL config:**
   ```bash
   python3 scripts/nautobot_device_discovery.py --generate-config > /tmp/otel_config.yaml
   ```

3. **Update OTEL Collector config:**
   - Manually copy receivers, processors, and pipeline entries from generated config
   - Or: Use script to automatically merge (future enhancement)

4. **Restart OTEL Collector:**
   ```bash
   docker restart convergence-otel-collector
   ```

5. **Verify in Grafana:**
   - Check Network Overview dashboard for new device
   - Verify device metadata labels are correct

---

## Testing & Validation

### Stack Health
```bash
./validate_stack.sh
```
Checks:
- All containers running
- Health endpoints responding
- VictoriaMetrics receiving data
- Grafana datasource configured

### Nautobot Integration
```bash
./validate_nautobot.sh
```
Checks:
- Nautobot API connectivity
- API token validity
- Device discovery working
- GraphQL query success

### Metrics Verification
```bash
# Check devices in VictoriaMetrics
curl http://localhost:8428/api/v1/label/device_name/values

# Check interface count
curl -s 'http://localhost:8428/api/v1/query?query=count(interface_in_octets_bytes_total)'
```

---

## Success Metrics

### Achieved
- ✅ 2 devices auto-discovered from Nautobot
- ✅ 100% device metadata enrichment (all 6 attributes)
- ✅ Real interface names (not index numbers)
- ✅ Sub-second GraphQL query performance
- ✅ Clean metric labeling (no duplicates or conflicts)
- ✅ 4 functional Grafana dashboards
- ✅ 1-year metrics retention

### Future Goals
- 🎯 10+ devices monitored
- 🎯 Automated config refresh (cron job)
- 🎯 SNMPv3 support
- 🎯 Per-device credential management
- 🎯 Additional metrics (CPU, memory, temperature)
- 🎯 Alerting rules (Prometheus Alertmanager)
- 🎯 AI agent integration for network insights

---

## Lessons Learned

### Architecture Decisions

1. **GraphQL vs REST**
   - GraphQL significantly faster for nested data
   - Single query vs multiple sequential calls
   - Lesson: Always use GraphQL for Nautobot when available

2. **OTEL Pipeline Architecture**
   - Shared pipelines cause label conflicts with multiple attribute processors
   - Device-specific pipelines ensure clean metadata
   - Lesson: One pipeline per device for proper labeling

3. **Metric Naming**
   - OTEL Collector adds suffixes when exporting to Prometheus format
   - `interface.in.octets` → `interface_in_octets_bytes_total`
   - Lesson: Account for exporter transformations in dashboard queries

4. **Nautobot as Source of Truth**
   - Better than hardcoding device metadata
   - Single place to update device information
   - Lesson: External CMDB/inventory essential for scale

### Operational Insights

1. **Docker Health Checks**
   - Default health checks may not match actual service health
   - Always verify manually via HTTP endpoints
   - Lesson: Tune health checks or monitor actual endpoints

2. **Environment Variables**
   - Shell env vars take precedence over `.env` file
   - Can cause confusing behavior with stale values
   - Lesson: Always override in script when loading `.env`

3. **SNMP Interface Names**
   - Must use `indexed_value_prefix: ""` with actual OID lookup
   - Default behavior gives generic names like "if.68"
   - Lesson: Always fetch interface names from ifDescr OID

---

## Next Steps

### Immediate (Phase 3)
1. ⚠️ Fix Docker health checks or ignore them
2. 🔧 Add validation for SNMP connectivity before adding to config
3. 📊 Add more interface metrics (discards, utilization percentage)
4. 🔔 Create basic alerting rules (interface down, high errors)

### Short-term
1. 🤖 Automated config refresh (cron job or webhook)
2. 🔐 SNMPv3 implementation
3. 📈 Device-specific dashboards (drill-down from overview)
4. 🔍 Log aggregation (syslog collection working but not visualized)

### Long-term
1. 🧠 AI agent integration for network insights
2. 📡 Additional protocols (NETCONF, gNMI)
3. ⚡ Real-time alerting (PagerDuty, Slack)
4. 🌐 Multi-site deployment
5. 🔄 Configuration backup and compliance checking

---

## Contributors

- Primary Development: Assisted by Claude Code
- Nautobot Instance: User-managed external deployment
- Network Devices: 2x Cisco WS-C3850-48P switches

---

## Change Log

### 2026-02-25 — Phase 5: Automation Agent hardening + live activation

**pfSense XML-RPC transport rewrite**
- ✅ Replaced `xmlrpc.client.ServerProxy` with direct httpx POST (`_xmlrpc_exec_php()`) — pfSense
  prepends PHP echo output before the XML-RPC envelope, which `xmlrpc.client` cannot parse
- ✅ HTTP Basic Auth via httpx `auth=` parameter — handles special chars (`@`) in passwords correctly
- ✅ Manual XML envelope extraction: splits response at `<?xml` offset, parses fault codes with ElementTree
- ✅ `PFSENSE_XMLRPC_TARGET=alias` mode: edits plain Firewall Alias via PHP config API (`config_set_path`,
  `write_config`, `filter_configure`) — no pfBlockerNG required
- ✅ `POST /api/automation/setup-pfsense` endpoint — idempotent alias + WAN block rule creation via exec_php
- ✅ `_xmlrpc_write_lock` (asyncio.Lock) — serialises concurrent alias writes; fixes race condition where
  `/approve-all` with N IPs resulted in only 1 IP landing in the alias (last-writer-wins)
- ✅ `PFSENSE_HOST` now supports `host:port` format for non-standard GUI ports (e.g. `192.168.1.1:440`)

**Discord bot (/approve /reject /approve-all /reject-all /pending)**
- ✅ Added `notifications/discord_bot.py` — discord.py Gateway bot with 5 slash commands
- ✅ Guild-scoped slash command sync via `DISCORD_GUILD_ID` (instant vs ~1h global propagation)
- ✅ `/approve-all` bypasses `MAX_ACTIONS_PER_HOUR` — rate limit protects unattended auto-approve,
  not conscious human bulk decisions; `record_action_taken()` still fires for metrics accuracy
- ✅ Fixed `analysis/claude_action.py:_PFBLOCKER_LIST` — was hardcoded to old `pfBlockerNG_AutoAgent_v4`
  name; changed to `settings.pfsense_firewall_alias` so target list always matches `.env`

**Re-alert spam prevention**
- ✅ `mark_ip_processed(ip, ttl_hours=4)` now called in pending-approval path — previously absent,
  causing the same IP to generate a fresh Discord alert on every 10-min poll cycle
- ✅ In-memory dedup check (`already_pending`) added before rate limit check — catches container-restart
  scenarios where Redis keys are cleared but `pending_approvals` dict still has the session

**Repeat offender / block count tracking**
- ✅ `get_block_count()` / `increment_block_count()` in `rate_limiter.py` — per-IP Redis counter
  (`automation:block_count:{ip}`) with 1-year TTL, incremented after every successful live block
- ✅ Block count fetched in `scheduler.py` before Claude analysis, stored in `threat_data["block_count"]`
- ✅ Claude prompt updated with repeat-offender and high-volume labels; duration escalation to 168h +
  `recommend_permanent_block: true` when thresholds exceeded
- ✅ Discord approval embeds show "Block History" field (🆕/🟢/🟡/🔴 indicators)
- ✅ Outcome notifications include total block count and repeat-offender callout
- ✅ `REPEAT_OFFENDER_THRESHOLD=5` and `HIGH_VOLUME_THRESHOLD=50` added to config + `.env`

---

### 2026-02-25 — Phase 5: Event-Driven Automation Agent (initial build)
- ✅ Built `services/automation-agent/` FastAPI service (19 new files, 2,395 lines)
- ✅ APScheduler 10-min polling loop with per-IP session orchestration
- ✅ GAIT audit trail: gitpython branch-per-session, 8 sequential JSON turn files
- ✅ Claude Haiku action-proposal prompt with hard safety constraints
- ✅ Discord webhook: approval-required orange embeds + dry-run/success/fail outcome embeds
- ✅ Redis rate limiter (sliding window) + IP deduplication TTL
- ✅ VictoriaMetrics baseline capture + post-action verification
- ✅ pfSense executor: XML-RPC + SSH paths implemented
- ✅ 7 new Prometheus metrics (`automation_actions_total`, `session_duration`, etc.)
- ✅ Grafana Automation dashboard (`dashboards/automation/automation-agent.json`)
- ✅ Grafana Infinity datasource provisioned (`automation-agent.yaml`)
- ✅ Added `automation-audit` Docker named volume for git persistence
- 📝 Created `docs/PHASE5_AUTOMATION_AGENT.md`

### 2026-02-21 — Phase 4: AI Threat Intelligence
- ✅ Built `services/threat-intel/` FastAPI service (20 new files)
- ✅ Integrated AbuseIPDB, GreyNoise, OTX, IPInfo enrichment clients
- ✅ Composite threat scoring (50/30/20 weighting across 3 sources)
- ✅ Redis caching (24h TTL, AbuseIPDB rate-limit guard at 900/day)
- ✅ Claude Haiku AI narrative generation (executive summary, threats, recommendations)
- ✅ 10 new Prometheus metrics flowing into VictoriaMetrics
- ✅ Grafana Infinity datasource (yesoreyeram-infinity-datasource v3.7.1)
- ✅ 7-row "Threat Intelligence" Grafana dashboard provisioned
- ✅ Fixed GreyNoise 429 rate limiting (semaphore + delay)
- ✅ Fixed Claude empty-response edge case
- ✅ Updated `docker-compose.yml`, `prometheus.yml`, `convergence.yaml`, `.env`, `.env.example`
- 📝 Created `docs/PHASE4_THREAT_INTELLIGENCE.md`

### 2026-02-14
- ✅ Implemented GraphQL device discovery
- ✅ Created device-specific OTEL pipelines
- ✅ Fixed environment variable loading
- ✅ Added comprehensive device metadata tagging
- ✅ Cleaned VictoriaMetrics data and restarted stack
- ✅ Verified 2-device monitoring with proper labels
- 📝 Created this project status document

### Earlier Work
- ✅ Initial OTELCOL and VictoriaMetrics deployment
- ✅ Grafana dashboard creation
- ✅ SNMP receiver configuration
- ✅ Interface name resolution (ifDescr OID)
- ✅ Nautobot REST API integration (replaced with GraphQL)
- ✅ Docker Compose orchestration
- ✅ Git ignore rules for secrets

---

## References

- [OpenTelemetry Collector Documentation](https://opentelemetry.io/docs/collector/)
- [Nautobot GraphQL Guide](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/graphql/)
- [VictoriaMetrics Documentation](https://docs.victoriametrics.com/)
- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/)
- [SNMP OID Reference](https://www.iana.org/assignments/smi-numbers/smi-numbers.xhtml)

---

**Status:** ✅ **Operational** - Monitoring 2 devices with full Nautobot enrichment
