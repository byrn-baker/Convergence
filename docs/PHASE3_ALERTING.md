# Phase 3: Advanced Data Enrichment and Alerting

**Last Updated:** 2026-02-21 (updated: Loki ruler path fix, dashboard reorganization, new panels, Discord alerting, alert rule datasource UID fix, uptime metric name fix)
**Status:** Implemented

---

## Overview

Phase 3 builds on the geo-enriched firewall logs introduced in Phase 2 to deliver:

1. **LogQL Spike Detection** — Loki ruler evaluates LogQL queries on a schedule and fires alerts when attack patterns from specific regions exceed thresholds.
2. **Grafana Geo-Visualization** — The existing Geomap panels on the pfSense Security Dashboard now have richer Loki label support for LogQL-based exploration alongside the VictoriaMetrics metric data.
3. **Intelligent Alerting** — Provisioned Grafana alert rules cover country-based block spikes, overall firewall volume spikes, and switch uptime/reachability events. Alerts route to Alertmanager, then to webhooks or email.
4. **Dashboard Reorganization and New Panels** — Dashboards are split into `Network` and `Security` Grafana folders. Two new dashboards added: Threat Analysis (country breakdown, attack trends) and Network Device Health (uptime, error rates, bandwidth).

---

## Architecture

```
pfSense Firewall (filterlog syslog)
        │
        ▼
OpenTelemetry Collector
  ├─ Parse filterlog: extract src_ip, dst_ip, action, interface, proto_name
  ├─ GeoIP enrich: add src_lat, src_lon, src_country, src_city
  ├─ count/firewall connector → firewall_events_total metric (with geo labels)
  └─ file/syslog → /data/syslog/syslog.jsonl (OTLP JSON)
        │                         │
        ▼                         ▼
VictoriaMetrics              Promtail
(firewall_events_total        ├─ Regex extract labels from OTLP JSON:
 with src_lat, src_lon,       │   action, log_type, src_country,
 src_country labels)          │   src_country_code, interface
        │                     └─ Push structured logs to Loki
        │                               │
        ▼                               ▼
Grafana Unified Alerting           Loki Ruler
  ├─ Alert: Country block spike     ├─ Recording rules → pre-agg metrics
  ├─ Alert: Total block spike       └─ Alert rules → Alertmanager
  ├─ Alert: Switch rebooted                  │
  └─ Alert: Switch SNMP down                 ▼
        │                            Alertmanager
        │                            ├─ Route: critical → Discord (1h repeat)
        │                            ├─ Route: team=security → Discord (4h repeat)
        │                            └─ Route: team=network → Discord (6h repeat)
        ▼
Grafana Dashboards
  ├─ Security/ folder
  │   ├─ pfSense Security Dashboard
  │   │   ├─ Geomap: WAN Threats (firewall_events_total + src_lat/lon)
  │   │   ├─ Geomap: Traffic Destinations
  │   │   ├─ Top Blocked IPs table
  │   │   └─ Firewall Actions timeseries
  │   └─ Threat Analysis Dashboard
  │       ├─ Stats: total blocks / attacking countries / block rate
  │       ├─ Top 10 countries (horizontal bar)
  │       ├─ Protocol distribution (donut)
  │       ├─ Attack rate by country (timeseries)
  │       ├─ Blocks by interface (stacked timeseries)
  │       └─ All attacking countries table
  └─ Network/ folder
      ├─ Interface Utilization
      ├─ Interface Errors
      ├─ Network Overview
      ├─ Platform Health
      └─ Network Device Health Dashboard
          ├─ Per-device uptime stats
          ├─ Uptime history (reboot detection)
          ├─ Interface error rates (table + timeseries)
          └─ Total bandwidth per device
```

---

## Part A: Real-Time Threat Mapping with IP Data

### How the Geomap Works

The `firewall_events_total` metric (produced by OTEL's `count/firewall` connector) carries the following labels from every parsed `filterlog` entry:

| Label | Description | Example |
|---|---|---|
| `action` | Firewall decision | `block`, `pass` |
| `src_ip` | Source IP address | `1.2.3.4` |
| `src_lat` | Source latitude (GeoIP) | `39.9042` |
| `src_lon` | Source longitude (GeoIP) | `116.4074` |
| `src_country` | Source country name (GeoIP) | `China` |
| `dst_ip` | Destination IP | `192.168.100.1` |
| `dst_country` | Destination country | `United States` |
| `interface` | pfSense interface | `igc0.201` |
| `proto_name` | Protocol | `tcp`, `udp` |

The Geomap panel uses an instant query with `format=table` to get one row per unique source location:

```promql
topk(100,
  sum by (src_ip, src_lat, src_lon, src_country) (
    increase(firewall_events_total{
      action="block",
      direction="in",
      interface="igc0.201",
      src_ip!~"^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)"
    }[2h])
  )
)
```

Grafana receives this as a table with `src_lat`, `src_lon`, `src_country`, `src_ip`, and `Value` columns. The Geomap layer uses `latitude: "src_lat"` / `longitude: "src_lon"` in `coords` mode, with bubble size proportional to `Value` (block count).

### Useful LogQL Queries for Threat Exploration

Once Promtail is extracting `action`, `src_country`, and `interface` as Loki labels, you can explore raw logs in Grafana's Explore view:

**View all block events from a specific country:**
```logql
{job="syslog", log_type="firewall", action="block", src_country="China"}
```

**Count blocks per country over the last hour:**
```logql
sum by (src_country) (
  count_over_time(
    {job="syslog", log_type="firewall", action="block"}[1h]
  )
)
```

**Detect countries with a sudden spike (last 5 min vs last hour):**
```logql
(
  sum by (src_country) (count_over_time({job="syslog", action="block"}[5m]))
  /
  sum by (src_country) (count_over_time({job="syslog", action="block"}[1h]) / 12)
) > 3
```
This fires when the 5-minute rate is 3× the average 5-minute rate over the past hour — a relative spike detector that adapts to your baseline.

**View raw events with all parsed fields (JSON log exploration):**
```logql
{job="syslog", log_type="firewall", action="block"}
  | json
  | line_format "{{ .src_ip }} → {{ .dst_ip }}:{{ .dst_port }} ({{ .proto_name }}) [{{ .src_country }}]"
```

---

## Part B: Loki Ruler — Recording Rules and Alerting

### How the Ruler Works

The Loki ruler runs LogQL metric queries on a schedule (every 1 minute) and:

1. **Recording rules** write pre-aggregated metric series back into Loki. These series are cheap to query repeatedly and can be used in Grafana dashboards instead of rescanning raw logs.
2. **Alerting rules** send alerts to Alertmanager when an expression exceeds a threshold.

### Recording Rules in Action

The rules in `config/loki/rules/fake/firewall_alerts.yaml` create:

| Metric | Description |
|---|---|
| `firewall:blocks_by_country:rate5m` | Block count per country per 5-min window |
| `firewall:blocks_by_interface:rate5m` | Block count per interface per 5-min window |
| `firewall:blocks_total:rate5m` | Total block count per 5-min window |

Query these in Grafana's Loki datasource using the **Metrics** query type.

### Alerting Rules Deployed

| Alert | Condition | Severity |
|---|---|---|
| `BlockSpikeFromCountry` | >200 blocks from one country in 5m | warning |
| `HighTotalFirewallBlockRate` | >500 total blocks in 5m | warning |
| `WANInterfaceUnderAttack` | >300 blocks on WAN interface in 5m | critical |

> **Tuning thresholds**: Run `sum by (src_country)(count_over_time({job="syslog",action="block"}[5m]))` in Grafana Explore for a few days to understand your baseline before setting alert thresholds.

### Tenant Note

Loki uses `"fake"` as the tenant ID when `auth_enabled: false`. Rules must be placed in `config/loki/rules/fake/`. This is a Loki quirk for single-tenant deployments.

### Volume Path — Why Rules Live Under `/etc/loki`

The `docker-compose.yml` Loki service has two volume mounts:

| Host path | Container path | Type |
|---|---|---|
| `./config/loki` | `/etc/loki` | bind mount (read-only) |
| `loki-data` | `/loki` | Docker named volume |

The named volume owns `/loki` — Loki writes chunks, index, and compactor data there. Rule files placed under `config/loki/rules/` on the host land at `/etc/loki/rules/` inside the container (via the bind mount), **not** at `/loki/rules/`.

The `local-config.yaml` therefore sets:
```yaml
ruler:
  storage:
    type: local
    local:
      directory: /etc/loki/rules   # bind-mounted from ./config/loki/rules
  rule_path: /loki/rules-temp      # scratch space — inside named volume (writable)
```

If `ruler.storage.local.directory` were set to `/loki/rules` instead, Loki would look inside the named volume and return:
```
unable to read rule dir /loki/rules/fake: open /loki/rules/fake: no such file or directory
```

---

## Part C: Intelligent Alerting with Grafana

### Provisioned Alert Rules

Alert rules are provisioned from `config/grafana/provisioning/alerting/alert_rules.yaml`. They are visible in Grafana → Alerting → Alert Rules and evaluated by Grafana's built-in ruler.

#### Security Alerts (folder: Security Alerts)

| Rule | Query | Threshold | For |
|---|---|---|---|
| High Block Rate From Country (1h) | `sum by (src_country)(increase(firewall_events_total{action="block"}[1h]))` | >1000 | 5m |
| Firewall Block Rate Spike (5m) | `sum(increase(firewall_events_total{action="block"}[5m]))` | >500 | 3m |

#### Network Health Alerts (folder: Network Alerts)

| Rule | Query | Condition | For |
|---|---|---|---|
| Network Switch Rebooted | `delta(system_uptime{device_role="home_switch"}[5m])` | < -60s | 0m |
| Network Switch Low Uptime | `min(system_uptime{device_role="home_switch"})` | < 600s | 2m |
| Network Device SNMP Unreachable | `count(system_uptime{device_role="home_switch"})` | no data | 5m |

### Notification Policies

All alerts route to Discord. Policy file: `config/grafana/provisioning/alerting/notification_policies.yaml`

```
All alerts → Discord (default, 4h repeat)
  ├─ severity=critical → Discord (1h repeat, group_wait 10s)
  ├─ team=security     → Discord (4h repeat)
  └─ team=network      → Discord (6h repeat)
```

### Setting Up Discord Notifications

**1. Create a Discord webhook**
1. Open your Discord server → **Server Settings → Integrations → Webhooks**
2. Click **New Webhook**, choose your alerts channel, copy the URL
   (format: `https://discord.com/api/webhooks/ID/TOKEN`)

**2. Set the URL in your `.env`**
```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

**3. Apply — use `up --force-recreate`, not `restart`**
```bash
docker compose up -d --force-recreate grafana
```
> **Important:** `docker compose restart` does **not** apply environment variable changes from `docker-compose.yml`. Always use `--force-recreate` when adding or changing env vars.

**4. Test**

Via API (works even if the contact point isn't visible in the UI):
```bash
curl -s -u admin:admin \
  -X POST "http://localhost:3000/api/v1/provisioning/contact-points/convergence-discord/test" \
  -H "Content-Type: application/json" \
  -d '{}'
```
A successful test returns `{"message":"Alert notifications sent"}` and a Grafana test embed appears in your Discord channel.

### Contact Points

Defined in `config/grafana/provisioning/alerting/contact_points.yaml`:

| Name | Type | Purpose |
|---|---|---|
| Discord | discord | Primary alert destination — reads `${DISCORD_WEBHOOK_URL}` from env |
| Webhook | webhook | Generic HTTP endpoint (Slack, custom scripts, n8n, etc.) |
| Email | email | Email notifications — requires SMTP env vars in `docker-compose.yml` |
| Do Nothing | webhook | Silently drops alerts — useful for testing routing rules |

The `DISCORD_WEBHOOK_URL` env var is passed into the Grafana container via `docker-compose.yml`:
```yaml
- DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL:-https://discord.com/api/webhooks/0/placeholder}
```
The placeholder fallback is required — Grafana validates contact point URLs at startup and **refuses to start** if a Discord contact point has an empty URL.

### Viewing Contact Points in Grafana 12

In Grafana 12, provisioned contact points (from files) appear in **Alerting → Contact Points** with a lock icon and no Edit button. If a contact point isn't visible, use the API to confirm it loaded:

```bash
curl -s -u admin:admin http://localhost:3000/api/v1/provisioning/contact-points | \
  python3 -c "import sys,json; [print(f['name'], '-', f['type']) for f in json.load(sys.stdin)]"
```

### Alertmanager

The Alertmanager service (`http://localhost:9093`) receives alerts from Loki ruler rules and can also receive alerts from Grafana (configure in Grafana → Alerting → Admin → Alertmanager).

To use Alertmanager:
1. Set your webhook URL in `config/alertmanager/alertmanager.yml`
2. Or uncomment the `email_configs` block and configure SMTP settings
3. Apply: `docker compose restart alertmanager`

---

## Part D: Dashboard Organization and New Panels

### Folder Structure

Dashboards are provisioned from two host directories, each mapping to a Grafana folder:

| Host path | Grafana folder | Contents |
|---|---|---|
| `dashboards/network/` | **Network** | SNMP monitoring, interface stats, device health |
| `dashboards/security/` | **Security** | Firewall events, geo-visualization, threat analysis |
| `dashboards/cisco/` | **Vendor - Cisco** | *(reserved for future Cisco-specific dashboards)* |
| `dashboards/juniper/` | **Vendor - Juniper** | *(reserved)* |
| `dashboards/arista/` | **Vendor - Arista** | *(reserved)* |

Provisioning config: `config/grafana/provisioning/dashboards/convergence.yaml`

Alert rule folders (`Security Alerts`, `Network Alerts`) are created automatically by the alerting provisioning in `config/grafana/provisioning/alerting/`.

### Dashboard Inventory

#### Security Folder

**`pfsense-firewall-security.json`** — pfSense Firewall Security

| Panel | Type | Query / Purpose |
|---|---|---|
| Blocked Events Rate | gauge | `sum(rate(firewall_events_total{action="block"}[5m]))` |
| WAN Threats — Internet Attacks | geomap | Block events from public IPs, sized by count, coloured by count |
| Traffic Destinations | geomap | All traffic destinations (red = blocked, green = passed) |
| All Blocked Source IPs | geomap | All block origins across all interfaces |
| Firewall Actions Over Time | timeseries | Pass vs block rate over time |
| Top 100 Blocked Source IPs | table | `topk(100, sum by (src_ip,...))` |
| Blocked Traffic by Protocol | piechart | `sum by (proto_name)` |
| Traffic by Interface | barchart | `sum by (interface)` |
| Top Blocked Destination IPs | timeseries | What internal IPs are being targeted |
| Recent Firewall Events Summary | table | Latest block/pass events |

**`threat-analysis.json`** — Threat Analysis *(new)*

| Panel | Type | Query / Purpose |
|---|---|---|
| Total Blocks (24h) | stat | `sum(increase(firewall_events_total{action="block"}[24h]))` — background colour thresholds |
| Attacking Countries (24h) | stat | `count(sum by (src_country)(...) > 0)` — unique source countries |
| Current Block Rate | stat | `sum(rate(...[5m])) * 60` — blocks per minute |
| Top 10 Attacking Countries | barchart (horizontal) | `sort_desc(topk(10, sum by (src_country)(...[24h])))` |
| Blocked Traffic by Protocol | piechart (donut) | `sum by (proto_name)(...[24h])` |
| Attack Rate by Country Over Time | timeseries | Top 7 countries, 15m rolling rate, blocks/min |
| Blocks by Interface Over Time | timeseries (stacked) | All interfaces, shows which is under load |
| All Attacking Countries | table | Full sortable country breakdown with code and block count |

#### Network Folder

**`interface-utilization.json`** — Convergence - Interface Utilization
**`interface-errors.json`** — Convergence - Interface Errors
**`network-overview.json`** — Convergence - Network Overview
**`platform-health.json`** — Convergence - Platform Health

**`device-health.json`** — Network Device Health *(new)*

| Panel | Type | Query / Purpose |
|---|---|---|
| HomeSwitch01 Uptime | stat | `system_uptime_seconds{device_name="HomeSwitch01"}` — green ≥1d, orange ≥10m, red <10m |
| HomeSwitch02 Uptime | stat | Same for HomeSwitch02 |
| pfSense-FW01 Uptime | stat | Same for pfSense-FW01 (shows "No data" if pfSense doesn't report SNMP uptime) |
| Device Uptime History | timeseries | All devices — a drop to near-zero indicates a reboot |
| Interface Error Rates (table) | table | `rate(interface_in_errors_total[5m])` sorted descending |
| Interface Error Rate Over Time | timeseries | Only interfaces with `> 0` active errors are shown |
| Total Bandwidth per Device | timeseries | `sum by (device_name)(rate(interface_in_octets_bytes_total[5m])) * 8` IN + OUT |

> **sysUpTime unit note:** The OTEL Collector's SNMP receiver converts the raw sysUpTime OID (which is in centiseconds) to seconds before writing the `system_uptime_seconds` metric. The dashboards and alert rules query `system_uptime_seconds` directly with no further conversion needed.

---

## pfSense WAN Block Logging — Important Note

**Context:** Modern pfSense versions (CE 2.7+ / pfSense Plus) removed the *"Log packets matched from the default block rules"* option that previously existed under **System → Advanced → Firewall & NAT**. That option no longer appears in the UI.

**Solution:** Add an explicit logged block rule at the **bottom** of the WAN ruleset:

**Firewall → Rules → WAN → Add** (place at bottom):

| Field | Value |
|---|---|
| Action | Block |
| Interface | WAN |
| Direction | in |
| Protocol | Any |
| Source | Any |
| Destination | Any |
| Log | ✓ checked |
| Description | `Default deny - logged` |

**Why this is safe:** pfSense evaluates the state table before the ruleset. Return traffic for LAN-initiated connections matches an existing state and is allowed before any ruleset rule is consulted. The explicit block rule only fires on new unsolicited inbound connections — exactly the traffic you want to log and visualize.

**Verify:** After saving, check **Status → System Logs → Firewall** — it should immediately start filling with inbound block events from public IPs. The `filterlog` entries flow through OTEL → GeoIP → `firewall_events_total` → Geomap within the next batch cycle.

---

## Deployment Steps

### 1. Apply configuration changes

```bash
cd /path/to/convergence

# Restart services with updated configs
docker compose restart promtail loki alertmanager grafana
```

### 2. Verify Loki labels are being extracted

After restarting Promtail, wait for a few firewall events, then check in Grafana:

1. Go to **Explore → Loki**
2. Run: `{job="syslog"}` — you should see log entries
3. Check the label dropdown — `action`, `src_country`, `interface` should appear
4. Run: `{job="syslog", action="block"}` — only block events

### 3. Verify Loki recording rules

```bash
# Check Loki ruler API for active rules
curl http://localhost:3100/loki/api/v1/rules

# Check for recording rule metrics (after 1-2 minutes)
curl 'http://localhost:3100/loki/api/v1/query?query=firewall:blocks_total:rate5m'
```

### 4. Verify Alertmanager is running

```bash
curl http://localhost:9093/-/healthy
# → Alertmanager is Healthy.

# Check active alerts
curl http://localhost:9093/api/v2/alerts
```

### 5. Configure Discord webhook URL

Set `DISCORD_WEBHOOK_URL` in your `.env` file, then force-recreate Grafana to apply it:
```bash
docker compose up -d --force-recreate grafana
```

### 6. Test alert delivery

```bash
curl -s -u admin:admin \
  -X POST "http://localhost:3000/api/v1/provisioning/contact-points/convergence-discord/test" \
  -H "Content-Type: application/json" \
  -d '{}'
```
A test embed will appear in your Discord channel confirming the full pipeline is working.

---

## Troubleshooting

### No `action` or `src_country` labels in Loki

**Cause:** Regex pipeline stages in Promtail aren't matching the OTEL JSON format.

**Check:**
```bash
# Look at raw log lines from OTEL
docker exec convergence-otel-collector cat /data/syslog/syslog.jsonl | head -1 | python3 -m json.tool

# Check Promtail is processing the file
curl http://localhost:9080/metrics | grep promtail_read_bytes
```

**Fix:** The OTEL file exporter writes OTLP JSON where attributes look like:
```json
{"key":"action","value":{"stringValue":"block"}}
```
The Promtail regex `"key":"action","value":\{"stringValue":"(?P<action>[^"]+)"` must match this format exactly.

### Loki ruler shows no rules

**Cause:** Rules directory not mounted or wrong tenant path.

**Check:**
```bash
# Verify rules are visible inside the container (bind-mounted at /etc/loki/rules)
docker exec convergence-loki ls /etc/loki/rules/
# Should show: fake/

docker exec convergence-loki ls /etc/loki/rules/fake/
# Should show: firewall_alerts.yaml

curl http://localhost:3100/loki/api/v1/rules
# Should return the full rule group YAML
```

**Common error:**
```
unable to read rule dir /loki/rules/fake: open /loki/rules/fake: no such file or directory
```
**Cause:** `ruler.storage.local.directory` points to `/loki/rules` (inside the Docker named volume) instead of `/etc/loki/rules` (the bind mount). See the "Volume Path" note above.
**Fix:** Ensure `local-config.yaml` uses `directory: /etc/loki/rules`, then `docker compose restart loki`.

### Grafana alert rules show "No data"

**Cause:** Metric name or label selector doesn't match what's in VictoriaMetrics.

**Check:**
```bash
# Verify firewall_events_total exists
curl 'http://localhost:8428/api/v1/label/__name__/values' | grep firewall

# Check what labels are on the metric
curl 'http://localhost:8428/api/v1/series?match[]=firewall_events_total' | python3 -m json.tool | head -30
```

### Alert rules show "Error: data source not found"

**Symptom:** Alert fires as `Error` with annotation `failed to build query 'X': data source not found`. The alert is permanently in the `Firing` state even when no threshold is exceeded.

**Cause:** The `datasourceUid` values in `alert_rules.yaml` are placeholder strings (`VictoriaMetrics`, `Loki`) that don't match the actual UIDs Grafana assigned when it provisioned the data sources. Grafana assigns random UIDs (e.g., `P4169E866C3094E38`) and the provisioning YAML must use those exact values.

**Find your actual UIDs:**
```bash
curl -s -u admin:admin http://localhost:3000/api/datasources | \
  python3 -c "import sys,json; [print(f['uid'], '-', f['name']) for f in json.load(sys.stdin)]"
```

**Fix:** Replace all `datasourceUid` values in `alert_rules.yaml` with the UIDs from the command above, then force-recreate Grafana:
```bash
docker compose up -d --force-recreate grafana
```

**Verify rules loaded with correct UIDs:**
```bash
curl -s -u admin:admin http://localhost:3000/api/v1/provisioning/alert-rules | \
  python3 -c "
import sys, json
for r in json.load(sys.stdin):
    for q in r.get('data',[]):
        if q.get('datasourceUid') not in ('__expr__',):
            print(r['uid'], '->', q['datasourceUid'])
            break
"
```

### Network switch alerts show `DatasourceNoData` and are always firing

**Cause:** The rules `net-switch-reboot`, `net-switch-low-uptime`, and `net-device-snmp-down` query `system_uptime{device_role="home_switch"}`. If no SNMP data with that label exists in VictoriaMetrics, they fire as expected — `net-device-snmp-down` is intentionally configured with `noDataState: Alerting` (no data **is** the alert condition).

**Check whether any device_role values exist:**
```bash
curl -s 'http://localhost:8428/api/v1/label/device_role/values'
```

**Options:**
- If the label value doesn't match, update the `device_role` filter in `alert_rules.yaml` to match your actual label values.
- If SNMP polling for switches is not yet configured, silence these rules in Grafana → Alerting → Silences until the data is available.

---

## Next Steps (Phase 4)

- **Automated response**: Trigger pfSense firewall rule additions via API when `WANInterfaceUnderAttack` fires
- **Baseline learning**: Use VictoriaMetrics anomaly detection (MetricsQL `outlier_iqr_over_time()`) to replace fixed thresholds with dynamic baselines
- **AI integration**: Feed Loki/VictoriaMetrics data to an LLM agent for natural language security summaries
- **Multi-site**: Extend Alertmanager routing to handle alerts from multiple pfSense instances at different sites
