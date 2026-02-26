# Phase 4: AI Threat Intelligence Service

**Last Updated:** 2026-02-22
**Status:** Implemented

---

## Overview

Phase 4 adds a dedicated `threat-intel` microservice that enriches the top blocked and
outbound IPs collected by pfSense with four external threat intelligence APIs, generates
AI-written threat narratives via Claude Haiku, and surfaces everything through a new Grafana
"Threat Intelligence" dashboard.

1. **IP Reputation Scoring** — AbuseIPDB, GreyNoise, OTX, and IPInfo combine into a 0–100 composite threat score per IP
2. **Outbound C2 Detection** — Outbound `pass` traffic to non-RFC1918 destinations is analyzed for known bad-actor indicators
3. **Port Risk Analysis** — Loki LogQL extracts destination ports from raw pfSense filterlog entries and maps them to service names and risk levels
4. **AI Threat Narratives** — Claude Haiku generates pfSense-specific executive summaries, top threat descriptions, and actionable remediation steps using real interface names and pfBlockerNG paths

---

## Architecture

```
VictoriaMetrics (firewall_events_total)
    │ PromQL — top 50 blocked src_ips, top 20 outbound dst_ips, active interfaces
    ▼
threat-intel service (FastAPI + APScheduler)  :8001
    ├─ Startup + hourly enrichment job:
    │   ├─ Redis cache check (24h TTL per IP)
    │   ├─ AbuseIPDB  /v2/check          → confidence score 0–100
    │   ├─ GreyNoise  /v3/community/{ip} → malicious / benign / riot / unknown
    │   ├─ OTX        /api/v1/indicators → threat pulse count
    │   ├─ IPInfo     /{ip}              → country, org, ASN
    │   ├─ Port analysis: Loki LogQL filterlog regexp → dst_port
    │   └─ Claude Haiku → structured JSON threat narrative
    ├─ GET /health                 → {"status":"ok","report_available":true}
    ├─ GET /metrics                → Prometheus format → scraped by VictoriaMetrics
    ├─ GET /api/report             → full JSON report
    ├─ GET /api/report/blocked|outbound  → filtered JSON
    └─ GET /api/infinity/*         → flat arrays for Infinity datasource plugin
```

> **Infinity pattern**: All `/api/infinity/*` endpoints return arrays (`[{...}]`). This is
> required because Infinity's Go backend cannot process JSON objects as single rows regardless
> of any `root_is_not_array` options. See [THREAT_INTEL_SERVICE.md](THREAT_INTEL_SERVICE.md)
> for a full explanation of Infinity's architecture and known gotchas.

---

## File Inventory

### New files

```
services/threat-intel/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py               FastAPI app — all 15 API endpoints
    ├── scheduler.py          APScheduler: hourly job + immediate startup run
    ├── config.py             Pydantic-settings env var config
    ├── state.py              Module-level latest_report dict (shared scheduler/API)
    ├── metrics.py            prometheus_client gauge/counter definitions
    ├── models.py             Pydantic response models
    ├── enrichment/
    │   ├── cache.py          Redis 24h TTL + AbuseIPDB daily budget counter
    │   ├── abuseipdb.py      AbuseIPDB /v2/check client
    │   ├── greynoise.py      GreyNoise community client (semaphore rate-limited)
    │   ├── otx.py            OTX /api/v1/indicators/IPv4/{ip}/general client
    │   ├── ipinfo.py         IPInfo /{ip} client
    │   └── aggregator.py     Combines 4 sources → composite score + C2 detection
    └── analysis/
        ├── vm_client.py      VictoriaMetrics PromQL queries (IPs, interfaces, sources)
        ├── ports.py          Loki LogQL filterlog CSV port extraction
        └── claude_client.py  Anthropic client + pfSense-aware prompt builder

services/threat-intel/data/port_services.json   31 port definitions
config/grafana/provisioning/datasources/threat-intel.yaml
dashboards/threat-intel/threat-intelligence.json
docs/PHASE4_THREAT_INTELLIGENCE.md   (this file)
docs/THREAT_INTEL_SERVICE.md         (service internals reference)
```

### Modified files

```
docker-compose.yml                                  Added threat-intel service + Infinity plugin
config/victoriametrics/prometheus.yml               Added threat-intel scrape job
config/grafana/provisioning/dashboards/convergence.yaml   Added Threat Intelligence folder
.env / .env.example                                 Added 5 API key variables
```

---

## API Keys

Add to `.env` and restart: `docker compose up -d --force-recreate threat-intel`

| Variable | Source | Free Tier | Required |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com | Pay-per-token | Yes (narratives) |
| `ABUSEIPDB_API_KEY` | https://www.abuseipdb.com/register | 1,000/day | Recommended |
| `GREYNOISE_API_KEY` | https://www.greynoise.io | ~60 req/min unauthenticated | Optional |
| `OTX_API_KEY` | https://otx.alienvault.com/accounts/signup | Free | Recommended |
| `IPINFO_TOKEN` | https://ipinfo.io/signup | 50k/month | Recommended |

The service degrades gracefully — missing keys are skipped and scoring uses available sources.

---

## Composite Threat Score (0–100)

| Component | Weight | Logic |
|---|---|---|
| AbuseIPDB confidence | 50% | `score × 0.5` |
| OTX pulse count | 30% | `min(pulses, 20) / 20 × 30` |
| GreyNoise classification | 20% | malicious=+20, noise/unknown=+5, RIOT/benign=0 |

**Threat levels**: none (<10) · low (10–24) · medium (25–49) · high (50–74) · critical (75+)

RIOT-flagged IPs (GreyNoise "Reasonably Identified as OK Technology") always score 0.

---

## Outbound C2 Detection

Outbound `pass` traffic to non-RFC1918 IPs is flagged `is_known_bad_actor=true` if **any** of:
- OTX pulse_count > 2
- AbuseIPDB score > 20
- GreyNoise classification = malicious
- Composite score > 30 AND IP is not RIOT-flagged

---

## False Positive Detection

An IP is treated as likely benign if:
- GreyNoise RIOT flag is set (confirmed infrastructure), **or**
- The org name contains a known infrastructure name: Google, Cloudflare, Amazon, Microsoft,
  Apple, Akamai, Fastly, Netflix, Roblox, Meta, Facebook, Twitter, Zoom, Dropbox, GitHub, CDN,
  iCloud, Broadsoft, Charter, Comcast, Verizon, AT&T

Claude uses this to label such IPs "PROBABLE FALSE POSITIVE" and avoid block recommendations
unless `abuse_score > 50`. This is a heuristic — verify independently before whitelisting.

---

## pfSense NAT and Internal Source Tracking

pfSense logs outbound traffic at the **WAN interface after NAT**. This means `src_ip` for all
outbound `pass` events in VictoriaMetrics is the pfSense WAN IP — not the internal LAN host.

The dashboard labels this correctly as `pfSense NAT (174.x.x.x)`. Claude's recommended actions
include the step to find the true internal source:

> "pfSense Diagnostics > States — filter by [DST_IP] to identify the internal LAN host"

To find the actual internal source manually:
1. Open pfSense → **Diagnostics > States**
2. Search/filter by the suspicious destination IP
3. The state entry shows the original internal source IP and port

Alternatively, enable logging on LAN interface rules to capture traffic before NAT.

---

## Rate Limit Guards

**AbuseIPDB**: Free tier = 1,000 calls/day. Redis daily counter key
`threat-intel:budget:abuseipdb:YYYY-MM-DD` caps at 900. Combined with 24h cache TTL,
recurring IPs are not re-queried on every hourly cycle.

**GreyNoise**: Community API is rate-limited to ~60 req/min unauthenticated. A module-level
`asyncio.Semaphore(3)` with 150ms sleep enforces pacing. The sleep must be **inside** the
semaphore block — placing it outside releases the semaphore before the HTTP call is made,
defeating the rate limiting.

---

## Prometheus Metrics

| Metric | Labels |
|---|---|
| `threat_intel_ip_score` | ip, direction, country, org, classification |
| `threat_intel_ip_event_count` | ip, direction, action |
| `threat_intel_abuseipdb_score` | ip, direction |
| `threat_intel_otx_pulses` | ip, direction |
| `threat_intel_greynoise_classification` | ip, direction (2=malicious, 1=unknown, 0=benign, -1=riot) |
| `threat_intel_known_bad_actor` | ip, direction, country |
| `threat_intel_port_event_count` | port, **port_service**, risk_level |
| `threat_intel_enrichment_last_success_timestamp` | — |
| `threat_intel_enrichment_ips_processed_total` | — |
| `threat_intel_cache_hits_total` | — |

> **Label naming**: The port service label is `port_service`, not `service`. The label name
> `service` is effectively reserved in this deployment — the VictoriaMetrics scrape config
> applies `labels: {service: 'threat-intel'}` at scrape time, silently overwriting any
> metric-level `service` label.

VictoriaMetrics must be **restarted** after adding the scrape job — it does not hot-reload
`prometheus.yml`.

---

## Grafana Dashboard

Dashboard UID: `threat-intelligence-v1`, folder: "Threat Intelligence"

| Row | Panels | Datasource |
|---|---|---|
| Executive Summary | Risk level, bad actor counts, critical ports, max score gauge, last analysis | Infinity + VictoriaMetrics |
| AI Threat Narrative | Executive summary, recommended actions (pfSense-specific), top threats | Infinity |
| Inbound Threat Scores | Top IPs by score, AbuseIPDB scores, score over time | VictoriaMetrics |
| Outbound Traffic Analysis | Suspicious outbound with pfSense NAT source, scored destinations, OTX hits | VictoriaMetrics + Infinity |
| Port Attack Analysis | Top ports bar chart, critical ports table, risk pie chart | VictoriaMetrics + Infinity |
| Enriched IP Detail Tables | Blocked IP table, full outbound IP table | Infinity |
| Service Health | Last enrichment timestamp, IPs processed, cache hit rate | VictoriaMetrics |

**Datasources**:
- VictoriaMetrics — uid `P4169E866C3094E38`, type prometheus
- ThreatIntel — uid `threat-intel`, type yesoreyeram-infinity-datasource

> The VictoriaMetrics UID is auto-assigned at Grafana provisioning time. If panels show
> "datasource not found", look up the real UID and replace all occurrences in the dashboard JSON:
> ```bash
> curl -s -u admin:admin http://localhost:3000/api/datasources | \
>   python3 -c "import sys,json; [print(d['name'],d['uid']) for d in json.load(sys.stdin)]"
> ```

---

## Loki Port Analysis — Filterlog Format

pfSense firewall logs use filterlog CSV format. Loki stores them under `{job="syslog"}` with
no structured labels for `action` or `dst_port` — those must be extracted from the log body.

**Correct LogQL query**:
```logql
sum by (dst_port) (
  count_over_time(
    {job="syslog"}
    |~ "filterlog"
    |~ ",block,"
    | regexp `,(?:tcp|udp),\d+,[^,]+,[^,]+,\d+,(?P<dst_port>\d+),`
    [1h]
  )
)
```

The regexp matches `,tcp,<len>,<src_ip>,<dst_ip>,<src_port>,<dport>,` — capturing field [21]
(0-indexed dst_port). ICMP entries have `request`/`reply` at field [20], don't match, and are
silently skipped.

**What does NOT work**:
- `{job="syslog", log_type="firewall"}` — `log_type` label does not exist in this deployment
- `{job="syslog", action="block"}` — `action` label does not exist
- `| regexp "(?P<dst_port>\d+)$"` — end-of-line captures the TCP window size field, not dst_port

Use `GET /loki/api/v1/labels` to verify which labels actually exist before writing LogQL.

---

## Deployment

### First-time setup

```bash
# 1. Add API keys to .env
# ANTHROPIC_API_KEY, ABUSEIPDB_API_KEY, OTX_API_KEY, IPINFO_TOKEN, GREYNOISE_API_KEY

# 2. Build and start
docker compose up -d --build threat-intel

# 3. Restart VictoriaMetrics to reload prometheus.yml scrape config
docker compose restart victoriametrics

# 4. Force-recreate Grafana to install Infinity plugin + load new datasource
docker compose up -d --force-recreate grafana
```

### After making changes

| Change | Command |
|---|---|
| API keys | `docker compose up -d --force-recreate threat-intel` |
| Python code | `docker compose build threat-intel && docker compose up -d --force-recreate threat-intel` |
| Dashboard JSON | Auto-reloads in 30 seconds — no restart needed |
| Datasource YAML | `docker compose up -d --force-recreate grafana` |

---

## Verification

```bash
# Service health
curl http://localhost:8001/health
# → {"status":"ok","report_available":true}

# Summary stats (wait up to 60s after startup for first enrichment)
curl http://localhost:8001/api/infinity/summary | python3 -m json.tool

# Port analysis working
curl http://localhost:8001/api/infinity/ports | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'{len(d)} ports detected')
for p in d[:5]: print(f'  port={p[\"port\"]:6} service={p[\"service\"]:15} risk={p[\"risk_level\"]}')"

# Suspicious outbound destinations
curl http://localhost:8001/api/infinity/outbound_suspicious | python3 -m json.tool

# pfSense-specific recommended actions
curl http://localhost:8001/api/infinity/actions | python3 -c "
import sys,json
for a in json.load(sys.stdin): print('•', a['action'])"

# VictoriaMetrics scraping with correct port_service label
curl -s 'http://localhost:8428/api/v1/query?query=threat_intel_port_event_count' | python3 -c "
import sys,json
for m in json.load(sys.stdin)['data']['result'][:5]:
    print(m['metric'].get('port'), m['metric'].get('port_service'), m['metric'].get('risk_level'))"

# Redis cache populated
docker exec convergence-redis redis-cli KEYS 'threat-intel:ip:*' | wc -l

# Claude narrative
curl -s http://localhost:8001/api/report | python3 -c "
import sys,json; r=json.load(sys.stdin); n=r['narrative']
print('available:', n['available'], '| risk:', n.get('risk_level','N/A'))"

# Service logs
docker logs convergence-threat-intel --tail 50
```

---

## Troubleshooting

### `report_available: false` after 60+ seconds

**Cause**: First enrichment run failed. VictoriaMetrics may have no `firewall_events_total`
data yet, or Loki is unreachable.

**Check**: `docker logs convergence-threat-intel --tail 100 | grep -E "ERROR|WARNING|Enrichment"`

---

### Stat panels show "No Data"

**Cause**: Infinity uses the column `text` property as the DataFrame field name, not `selector`.
If `text` is `"Risk Level"` but the panel's `reduceOptions.fields` regex is `/^overall_risk_level$/`,
no field matches and the panel shows "No Data". This failure is completely silent — the query
reports `status: ok` and the data is present in `meta.custom.data`.

**Fix**: Set `text` equal to `selector` in all Infinity column definitions for stat/gauge panels.
Use `fieldConfig.overrides[].properties[displayName]` for human-readable display labels instead.

---

### Suspicious Outbound Destinations panel is empty

**Cause A**: No outbound IPs are flagged `is_known_bad_actor=true` in the current report.
This is correct behaviour if outbound traffic is clean.

**Cause B**: Enrichment has not run yet.

**Check**: `curl http://localhost:8001/api/infinity/outbound_suspicious`

---

### Port panels show no data

**Cause A**: Loki query failed. Check `docker logs convergence-threat-intel | grep "Loki port"`.

**Cause B**: No `filterlog` lines with `,block,` in the lookback window. Verify pfSense is
logging WAN blocks — go to **Firewall > Rules > WAN** and confirm a logged default-deny rule
exists at the bottom of the ruleset.

---

### GreyNoise scores are all zero after first run

**Cause**: The startup enrichment burst of ~70 concurrent requests hit the community API's
~60 req/min rate limit. First-run GreyNoise data may be incomplete.

**Resolution**: Scores correct themselves on the next hourly cycle as the Redis cache warms
and only new IPs hit the API. Optionally set `GREYNOISE_API_KEY` for a higher rate limit.

---

### "datasource not found" on VictoriaMetrics panels

**Cause**: Dashboard JSON contains a hardcoded UID that doesn't match the provisioned instance.

**Fix**:
```bash
curl -s -u admin:admin http://localhost:3000/api/datasources | \
  python3 -c "import sys,json; [print(d['name'],d['uid']) for d in json.load(sys.stdin)]"
```
Replace all occurrences in `dashboards/threat-intel/threat-intelligence.json`.

---

### `port_service` label shows `threat-intel` for all port metrics

**Cause**: The scrape config applies `labels: {service: 'threat-intel'}` to all series from
this target, but the metric uses `service` as a label name. Prometheus-compatible scrapers
overwrite conflicting metric-level labels at ingest time — silently.

**Correct label**: The port service label is `port_service`, not `service`.
Query: `threat_intel_port_event_count{port_service="SSH"}`.

---

## Known Limitations

- **pfSense NAT masks internal sources**: Outbound events always show the WAN IP as source.
  True internal host requires `Diagnostics > States` on the pfSense appliance or enabling
  LAN-side logging before NAT.
- **Loki port analysis requires filterlog**: If Promtail is not shipping pfSense syslog, port
  panels will be empty. The Loki query depends on `{job="syslog"}` containing filterlog entries.
- **AbuseIPDB free tier**: 1,000 calls/day. With 70 IPs/hour and 24h cache, the service stays
  within budget under normal conditions, but a cache flush on a high-traffic day could exhaust
  the quota early.

---

## Bug Reference

15 distinct failures occurred across the build sessions. The detailed explanations with root
causes and general lessons are in [THREAT_INTEL_SERVICE.md — Architecture Decisions & Gotchas](THREAT_INTEL_SERVICE.md#architecture-decisions--gotchas).

| # | Symptom | Root Cause | Fix |
|---|---|---|---|
| 1 | GreyNoise 429 errors | 70 concurrent startup requests exceeded ~60/min community limit | `asyncio.Semaphore(3)` + 150ms sleep **inside** semaphore block |
| 2 | Narrative `available: false` | Claude returned empty body on sparse first-run data | Guard `if not raw_text` before `json.loads` |
| 3 | `JSONDecodeError` on Claude response | Model wrapped JSON in ` ```json ``` ` fences | Strip ` ``` ` prefix/suffix before parsing |
| 4 | `http: no Host in request URL` | Infinity Go backend requires absolute URLs, not relative paths | Use full `http://threat-intel:8000/...` in every panel target |
| 5 | Stat panels blank | Infinity cannot iterate a JSON object; `root_is_not_array` is frontend-only | Return `[{...}]` arrays from all `/api/infinity/*` endpoints |
| 6 | Executive Summary shows "Loading..." | Grafana `type: text` panels ignore datasource targets entirely | Use `type: table` with `showHeader: false` |
| 7 | "datasource prometheus not found" | `"uid": "prometheus"` is the plugin type ID, not the instance UID | Query `/api/datasources` for real UID; replace all 22 occurrences |
| 8 | Stat panels blank after array fix | Infinity uses `text` as DataFrame field name; regex matched `selector` | Set `text` = `selector` in stat panel column definitions |
| 9 | Port query returns zero results | Labels `log_type` and `action` don't exist in Loki | Use `\|~ "filterlog"` and `\|~ ",block,"` line filters instead |
| 10 | Port 65535 extracted instead of port 80 | `(?P<dst_port>\d+)$` captured TCP window size (last field), not dst_port | Positional regexp anchored to CSV structure around field [21] |
| 11 | Outbound table columns empty | Infinity Go backend treats `intel.country` as a literal key name | Return flat objects; no nested fields in `/api/infinity/*` endpoints |
| 12 | Outbound filter shows no rows | Dashboard filter value `"true"` (string) ≠ JSON boolean `true` | Pre-filter server-side; `/api/infinity/outbound_suspicious` returns only bad actors |
| 13 | Port service names show `threat-intel` | Scrape-level `service: 'threat-intel'` label overwrote metric-level `service` | Renamed metric label `service` → `port_service` |
| 14 | All outbound appears from same WAN IP | pfSense logs outbound after NAT; `src_ip` is always the WAN address | Label as "pfSense NAT (x.x.x.x)"; recommend `Diagnostics > States` |
| 15 | Infinity `root_is_not_array` has no effect | Option is TypeScript-only; Go backend returns `fields: []` regardless | Return arrays (see Bug 5) |

---

## Next Steps (Phase 5 Ideas)

- **Automated pfSense response**: Call pfSense API to add firewall rules when threat score
  exceeds a threshold, without manual intervention
- **Contextual memory**: Persist threat reports to compare IPs across hourly cycles;
  flag IPs that appear persistently over days or weeks
- **GeoIP correlation**: Cross-reference threat intelligence scores with the geographic attack
  clusters visible on the pfSense Security Dashboard Geomap panels
- **Threshold alerting**: Grafana alert rule on `threat_intel_known_bad_actor` count or on
  `threat_intel_ip_score` exceeding a high-risk threshold, routing to Discord

See [THREAT_INTEL_SERVICE.md](THREAT_INTEL_SERVICE.md) for service internals, all API endpoints,
and development notes.
