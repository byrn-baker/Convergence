# Threat Intel Service — Technical Reference

This is the internal reference for `services/threat-intel/`. For deployment, dashboard
configuration, and project context, see [PHASE4_THREAT_INTELLIGENCE.md](PHASE4_THREAT_INTELLIGENCE.md).

---

## What This Service Does

`threat-intel` is a FastAPI microservice that runs an hourly enrichment job. The job queries
VictoriaMetrics for the top blocked and outbound IPs from pfSense firewall events, enriches
each IP against four external threat intelligence APIs, computes a composite 0–100 threat score,
and generates a pfSense-specific AI threat narrative via Claude Haiku. The enriched report is
held in memory and served through 15 REST endpoints — some consumed by VictoriaMetrics
(Prometheus scrape), some by Grafana Infinity datasource panels (JSON).

---

## Enrichment Pipeline: Data Flow

```
APScheduler (hourly + immediate on startup)
    │
    ├─ vm_client.get_top_blocked_ips(n=50, hours=1)
    │     PromQL: topk(50, sum by (src_ip)(increase(firewall_events_total{action='block'}[1h])))
    │     → [{ip, count, direction="in", action="block"}, ...]
    │
    ├─ vm_client.get_top_outbound_ips(n=20, hours=1)
    │     PromQL: topk(20, sum by (dst_ip)(increase(...{direction='out',action='pass'}[1h])))
    │     RFC1918 destinations are filtered out
    │     → [{ip, count, direction="out", action="pass"}, ...]
    │
    ├─ vm_client.get_active_interfaces(hours=1)
    │     PromQL: count by (interface)(increase(firewall_events_total[1h]) > 0)
    │     → ["igc0.201", "lagg0.102", ...]  (passed to Claude for pfSense-specific actions)
    │
    ├─ For each IP (blocked + outbound):
    │   │
    │   ├─ cache.get_ip(ip)  →  hit: return cached record (increments cache_hits_total)
    │   │                        miss: continue below
    │   │
    │   ├─ cache.check_abuseipdb_budget()  → True if daily calls < 900
    │   │
    │   ├─ asyncio.gather(
    │   │     abuseipdb.query(ip)   →  {abuse_confidence_score}
    │   │     greynoise.query(ip)   →  {classification, riot, name}    [rate-limited]
    │   │     otx.query(ip)         →  {pulse_count}
    │   │     ipinfo.query(ip)      →  {country, org}
    │   │   )
    │   │
    │   ├─ aggregator._compute_score(abuse, otx_pulses, gn_classification, is_riot)
    │   │     → composite_score (0–100), threat_level (none/low/medium/high/critical)
    │   │
    │   ├─ cache.set_ip(ip, record, TTL=24h)
    │   │
    │   ├─ aggregator._is_outbound_c2(record, direction)  → is_known_bad_actor (bool)
    │   │
    │   └─ Write 6 Prometheus metrics for this IP
    │
    ├─ For each outbound IP only:
    │     vm_client.get_outbound_sources(dst_ip)
    │     → [src_ip, ...]  (NOTE: always the WAN IP due to pfSense NAT — see below)
    │
    ├─ ports.get_top_blocked_ports(hours=1)
    │     Loki LogQL query with filterlog regexp → [{port, service, risk_level, count}, ...]
    │     Writes threat_intel_port_event_count Prometheus metrics
    │
    ├─ Build report dict (summary + blocked_ips + outbound_ips + port_analysis)
    │
    ├─ claude_client.generate_narrative(report, interfaces)
    │     → {risk_level, executive_summary, top_threats, recommended_actions, ...}
    │
    ├─ report["narrative"] = narrative
    │
    └─ state.latest_report = report   (served by all /api/* endpoints)
```

---

## Module Reference

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app; 15 route handlers; lifespan handler that starts the scheduler |
| `scheduler.py` | APScheduler `BackgroundScheduler`; adds hourly job + fires immediate startup run via `threading.Thread` (required because APScheduler uses its own event loop) |
| `config.py` | `pydantic_settings.BaseSettings`; reads all env vars with defaults; singleton `settings` object |
| `state.py` | Single module-level `latest_report: dict` — shared mutable state between the scheduler thread and FastAPI request handlers |
| `metrics.py` | All `prometheus_client` Gauge/Counter definitions; imported by `aggregator.py` and `ports.py` to write values |
| `models.py` | Pydantic response models for type validation |
| `enrichment/cache.py` | Async Redis client; `get_ip`/`set_ip` with 24h TTL; AbuseIPDB daily budget counter (atomic incr + expire pipeline) |
| `enrichment/abuseipdb.py` | HTTP client for `/v2/check`; returns `{abuse_confidence_score}` |
| `enrichment/greynoise.py` | HTTP client with `asyncio.Semaphore(3)` + 150ms inter-request delay; returns `{classification, riot, name}` |
| `enrichment/otx.py` | HTTP client for `/api/v1/indicators/IPv4/{ip}/general`; returns `{pulse_count}` |
| `enrichment/ipinfo.py` | HTTP client for `/{ip}`; returns `{country, org}` |
| `enrichment/aggregator.py` | Orchestrates cache + 4 API calls; computes composite score; sets `is_known_bad_actor`; writes 6 Prometheus metrics per IP |
| `analysis/vm_client.py` | PromQL instant queries: top blocked IPs, top outbound IPs, active interfaces, outbound sources; `_is_rfc1918()` helper |
| `analysis/ports.py` | Loki LogQL filterlog query; local `port_services.json` lookup; writes `threat_intel_port_event_count` metrics |
| `analysis/claude_client.py` | Builds pfSense-aware prompt; calls `anthropic.AsyncAnthropic`; strips markdown fences; parses JSON response |

---

## API Endpoints

All 15 endpoints are read-only GET requests. The `/api/infinity/*` endpoints return flat arrays
specifically shaped for the Grafana Infinity datasource plugin.

### Core endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | `{"status": "ok", "report_available": true\|false}` |
| `GET /metrics` | Prometheus text format — scraped by VictoriaMetrics |
| `GET /api/report` | Full enriched report as JSON |
| `GET /api/report/blocked` | Blocked IPs subset + `generated_at` |
| `GET /api/report/outbound` | Outbound IPs subset + `generated_at` |

### Infinity datasource endpoints (all return arrays)

| Endpoint | Array Shape | Used By |
|---|---|---|
| `GET /api/infinity/summary` | `[{overall_risk_level, known_bad_actors_inbound, known_bad_actors_outbound, critical_ports_targeted, total_blocked_ips, generated_at}]` | Stat panels, Row 1 |
| `GET /api/infinity/narrative` | `[{executive_summary, risk_level, model, inbound_analysis, outbound_analysis, port_analysis}]` | Executive Summary panel, Row 2 |
| `GET /api/infinity/threats` | `[{"threat": "..."}, ...]` | Top Threats table, Row 2 |
| `GET /api/infinity/actions` | `[{"action": "..."}, ...]` | Recommended Actions table, Row 2 |
| `GET /api/infinity/outbound_suspicious` | `[{ip, events, org, country, score, threat_level, abuse_score, otx_pulses, greynoise, source}]` — pre-filtered to `is_known_bad_actor=true` only | Suspicious Outbound table, Row 4 |
| `GET /api/infinity/outbound_all` | Same shape + `is_known_bad_actor`, `internal_sources` — all outbound | Outbound IP table, Row 6 |
| `GET /api/infinity/blocked_ips` | `[{ip, events, org, country, score, threat_level, abuse_score, otx_pulses, greynoise, is_known_bad_actor}]` | Blocked IP table, Row 6 |
| `GET /api/infinity/ports` | `[{port, service, risk_level, count, description}]` | Top Targeted Ports, Row 5 |
| `GET /api/infinity/critical_ports` | Same shape, pre-filtered to `risk_level="critical"` | Critical Ports table, Row 5 |

### Example: `/api/infinity/summary` response

```json
[
  {
    "overall_risk_level": "critical",
    "known_bad_actors_inbound": 39,
    "known_bad_actors_outbound": 3,
    "critical_ports_targeted": 2,
    "total_blocked_ips": 50,
    "generated_at": "2026-02-22T18:00:00Z"
  }
]
```

### Example: `/api/infinity/outbound_suspicious` response

```json
[
  {
    "ip": "158.51.125.98",
    "events": 21,
    "org": "AS399804 Hostodo",
    "country": "US",
    "score": 20,
    "threat_level": "low",
    "abuse_score": 0,
    "otx_pulses": 3,
    "greynoise": "unknown",
    "source": "pfSense NAT (174.29.213.100)"
  }
]
```

---

## Redis Key Schema

| Key Pattern | Type | TTL | Value |
|---|---|---|---|
| `threat-intel:ip:{ip}` | JSON string | 24 hours | Enriched intel record — `{ip, country, org, composite_score, threat_level, abuse_confidence_score, pulse_count, gn_classification, gn_name, riot}` |
| `threat-intel:budget:abuseipdb:{YYYY-MM-DD}` | Integer string | 24 hours (auto-expires at rollover) | Running count of AbuseIPDB API calls today; capped at `ABUSEIPDB_DAILY_BUDGET` (default 900) |

**Note**: The `is_known_bad_actor` field is **not** cached. It is computed per-call in
`aggregator.enrich_ip()` because the same IP can legitimately be blocked inbound but also
appear as a benign outbound destination — the `is_known_bad_actor` threshold differs by
direction.

---

## Configuration Reference

All variables read by `services/threat-intel/app/config.py` via `pydantic_settings`:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | Claude Haiku API key — narratives disabled if not set |
| `ABUSEIPDB_API_KEY` | `""` | AbuseIPDB key — scores show 0 if not set |
| `GREYNOISE_API_KEY` | `""` | GreyNoise key — community API used without key (rate-limited) |
| `OTX_API_KEY` | `""` | OTX key — pulse counts show 0 if not set |
| `IPINFO_TOKEN` | `""` | IPInfo token — country/org from GreyNoise fallback if not set |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `VICTORIAMETRICS_URL` | `http://victoriametrics:8428` | VictoriaMetrics base URL |
| `LOKI_URL` | `http://loki:3100` | Loki base URL |
| `ENRICHMENT_INTERVAL_SECONDS` | `3600` | Seconds between scheduled enrichment runs |
| `TOP_BLOCKED_IPS` | `50` | Blocked IPs to enrich per cycle |
| `TOP_OUTBOUND_IPS` | `20` | Outbound IPs to enrich per cycle |
| `CACHE_TTL_SECONDS` | `86400` | Redis TTL per cached IP record |
| `ABUSEIPDB_DAILY_BUDGET` | `900` | Max AbuseIPDB calls per day (hard cap; free tier is 1000) |
| `LOOKBACK_HOURS` | `1` | PromQL and Loki query time window |
| `DATA_DIR` | `/app/data` | Path to `port_services.json` inside container |

---

## Prometheus Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `threat_intel_ip_score` | Gauge | ip, direction, country, org, classification | Composite threat score 0–100 |
| `threat_intel_ip_event_count` | Gauge | ip, direction, action | Firewall event count for this IP |
| `threat_intel_abuseipdb_score` | Gauge | ip, direction | AbuseIPDB confidence score 0–100 |
| `threat_intel_otx_pulses` | Gauge | ip, direction | OTX threat pulse count |
| `threat_intel_greynoise_classification` | Gauge | ip, direction | 2=malicious, 1=unknown, 0=benign, -1=riot |
| `threat_intel_known_bad_actor` | Gauge | ip, direction, country | 1 if flagged bad actor, 0 otherwise |
| `threat_intel_port_event_count` | Gauge | port, **port_service**, risk_level | Blocked event count per destination port |
| `threat_intel_enrichment_last_success_timestamp` | Gauge | — | Unix timestamp of last successful enrichment |
| `threat_intel_enrichment_ips_processed_total` | Gauge | — | Total IPs processed in last cycle |
| `threat_intel_cache_hits_total` | Counter | — | Cumulative Redis cache hits |

---

## Scoring Details

### Why these weights

- **AbuseIPDB (50%)**: Community-reported abuse is the strongest direct signal for malicious
  intent. The confidence score is already normalised to 0–100.
- **OTX (30%)**: Threat pulse count indicates how many independent threat researchers have
  flagged the IP. Capped at 20 pulses to prevent a single prolific researcher from dominating
  the score.
- **GreyNoise (20%)**: Classification provides context but is binary — it confirms or denies
  known scanning behaviour rather than grading intensity.

### RIOT override

RIOT (Reasonably Identified as OK Technology) is a GreyNoise designation for IPs belonging
to well-known infrastructure operators that routinely scan the internet legitimately (search
engines, CDN health checks, etc.). Any RIOT-flagged IP returns composite score 0 regardless
of AbuseIPDB or OTX data, since the scanning behaviour is expected and does not represent
a threat to the network owner.

### `is_known_bad_actor` vs `threat_level`

`threat_level` is derived purely from the composite score. `is_known_bad_actor` applies an
additional outbound-specific check: for `direction=out` traffic, even a moderately low score
(composite > 30) is enough to flag the IP if it's not RIOT-designated — because outbound
connections to moderately suspicious IPs warrant investigation even when the score wouldn't
reach "medium" (25) on the inbound scale.

---

## Grafana Infinity Datasource — Architecture and Gotchas

### How Infinity v3 works internally

Infinity v3 is a two-layer plugin:

1. **Go backend** (`/api/ds/query` path): Receives the panel query, fetches the URL via HTTP,
   stores the raw JSON response in `meta.custom.data`, and returns `fields: []`. When debugging
   via `POST /api/ds/query`, seeing `fields: []` with data in `meta.custom.data` is **normal**
   and does not indicate an error.

2. **TypeScript frontend** (browser): Reads `meta.custom.data`, applies the column definitions
   and parser options, and builds the final Grafana DataFrame displayed in the panel.

This split means some options only work at one layer. Knowing which layer processes what
prevents a class of configuration bugs.

### Gotcha 1: Always use absolute URLs

**Problem**: Panel target `"url": "/api/infinity/summary"` → error `http: no Host in request URL`.

**Why**: The Go backend passes the `url` field directly to Go's HTTP client, which requires
a complete URL with scheme and host. The `base_url` setting in the datasource YAML does not
auto-prefix relative URLs.

**Fix**: Use `http://threat-intel:8000/api/infinity/summary` in every panel target. The
datasource provisioning YAML also requires all three fields:
```yaml
url: "http://threat-intel:8000"
jsonData:
  base_url: "http://threat-intel:8000"
  allowedHosts:
    - "http://threat-intel:8000"
```

### Gotcha 2: JSON objects don't work — wrap everything in arrays

**Problem**: A panel pointing at a JSON object (`{"risk_level": "critical", ...}`) returns
no data regardless of `root_selector` settings.

**Why**: Infinity's data model is array-first. Every result is treated as an array of rows
to iterate over. A plain JSON object is not iterable in this model.

**`root_is_not_array` limitation**: This option only runs in the TypeScript layer. The Go
backend still returns `fields: []` for objects, and some panel types (stat, gauge) use the
backend result directly.

**Fix**: Return `[{...}]` — a one-element array — from all single-object API endpoints. A
1-element array works cleanly at both layers with no special options.

### Gotcha 3: Nested dot-notation selectors are literal key lookups

**Problem**: Column selector `"selector": "intel.country"` returns empty values.

**Why**: The Go backend treats selectors as flat key names. `intel.country` is looked up as
a key literally named `"intel.country"` in the JSON object, not as a path traversal.

**Fix**: Return flat objects from all API endpoints. Instead of
`{"ip": "1.2.3.4", "intel": {"country": "US"}}`, return `{"ip": "1.2.3.4", "country": "US"}`.

### Gotcha 4: Boolean filter values must match JSON types

**Problem**: Dashboard filter `{field: "is_known_bad_actor", operator: "equals", value: "true"}`
shows no rows.

**Why**: The filter value `"true"` is a string. The JSON field value `true` is a boolean.
Strict equality `true !== "true"`.

**Fix**: Pre-filter server-side in the API endpoint. `/api/infinity/outbound_suspicious`
only returns rows where `is_known_bad_actor is True` in Python. No client-side filter needed.

### Gotcha 5: `text` is the DataFrame field name, not `selector`

**Problem**: Stat panels show "No Data" even though the Infinity query inspector shows correct
data in `meta.custom.data`.

**Why**: Infinity uses the column `text` property as the **field name** in the Grafana DataFrame
it constructs — not `selector`. A stat panel's `reduceOptions.fields` regex must match the
`text` value exactly. If `text` is `"Risk Level"` and the regex is `/^overall_risk_level$/`,
no field is found. This is completely silent — the query reports `status: ok` throughout.

**Fix**: Set `text` equal to `selector` for all stat/gauge/timeseries panel column definitions:
```json
{"selector": "overall_risk_level", "text": "overall_risk_level", "type": "string"}
```
For human-readable panel labels, use `fieldConfig.overrides[].properties[displayName]` — that
layer is applied after field selection, not before it.

### Gotcha 6: Grafana `type: text` panels ignore datasource targets

**Problem**: A Text panel with a datasource target configured shows only the static string
from `options.content`.

**Why**: The Grafana Text panel is a pure static renderer. Its `targets` array is parsed at
schema validation time but never executed at query time.

**Fix**: Use `type: table` with `showHeader: false` and `wrap: true` for narrative text fields.
A single-column wrapped table is visually equivalent and actually executes the datasource query.

---

## Development and Debugging

### Running the service locally (without Docker)

```bash
cd services/threat-intel
pip install -r requirements.txt

# Set env vars (or create .env in the services/threat-intel directory)
export REDIS_URL=redis://localhost:6379/0
export VICTORIAMETRICS_URL=http://localhost:8428
export LOKI_URL=http://localhost:3100
export ANTHROPIC_API_KEY=sk-ant-...

# Start with auto-reload
uvicorn app.main:app --reload --port 8000
```

The scheduler fires immediately on startup. If VictoriaMetrics or Loki are unavailable,
the enrichment job logs warnings and completes with empty results — it does not crash.

### Checking enrichment without waiting for the scheduler

The enrichment job runs immediately in a background thread on startup. After the service
starts, watch the logs:

```bash
docker logs convergence-threat-intel -f 2>&1 | grep -E "Enrichment|ERROR|WARNING"
```

A successful cycle ends with:
```
Enrichment complete: 50 blocked IPs, 20 outbound IPs, risk=critical
```

### Inspecting Redis cache state

```bash
# Count cached IPs
docker exec convergence-redis redis-cli KEYS 'threat-intel:ip:*' | wc -l

# Inspect a specific IP's cached record
docker exec convergence-redis redis-cli GET 'threat-intel:ip:1.2.3.4' | python3 -m json.tool

# Check today's AbuseIPDB budget usage
docker exec convergence-redis redis-cli GET "threat-intel:budget:abuseipdb:$(date +%Y-%m-%d)"

# Flush the IP cache (forces full re-enrichment on next cycle)
docker exec convergence-redis redis-cli KEYS 'threat-intel:ip:*' | xargs docker exec -i convergence-redis redis-cli DEL
```

### Enabling debug logging

Set the log level via the standard Python logging config. In the container, set the env var:
```bash
PYTHONUNBUFFERED=1  # already set in Dockerfile; ensures logs flush immediately
```

The `claude_client.py` logger emits a `DEBUG` line with the first 200 chars of Claude's raw
response — useful for diagnosing fence-wrapping or truncation issues. Enable with:
```python
import logging; logging.getLogger("app.analysis.claude_client").setLevel(logging.DEBUG)
```

### Testing the Loki port query directly

```bash
# Check what labels actually exist (critical before writing any LogQL)
curl http://localhost:3100/loki/api/v1/labels | python3 -m json.tool

# Test the port query manually
curl -sG http://localhost:3100/loki/api/v1/query \
  --data-urlencode 'query=sum by (dst_port) (count_over_time({job="syslog"} |~ "filterlog" |~ ",block," | regexp `,(?:tcp|udp),\d+,[^,]+,[^,]+,\d+,(?P<dst_port>\d+),`[1h]))' \
  | python3 -c "
import sys,json
r=json.load(sys.stdin)
for m in r['data']['result'][:10]:
    print(m['metric'].get('dst_port'), m['value'][1])"
```

### Checking Prometheus metrics output

```bash
curl -s http://localhost:8001/metrics | grep threat_intel | head -30
```

Expected output after a successful enrichment includes series for `threat_intel_ip_score`,
`threat_intel_known_bad_actor`, `threat_intel_port_event_count`, and the service-level gauges.
