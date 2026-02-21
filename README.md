# Convergence

**Network Observability Platform with Nautobot Integration**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/deployment-docker-2496ED.svg)](https://www.docker.com/)
[![Status](https://img.shields.io/badge/status-operational-success.svg)](docs/PROJECT_STATUS.md)

Convergence is a general-purpose observability platform that can be adapted to different monitoring use cases. Built on OpenTelemetry Collector, VictoriaMetrics, Grafana, Loki, and Alertmanager, it provides a foundation for collecting, storing, visualizing, and alerting on telemetry data from network devices and other sources. The platform features automatic device discovery from Nautobot, GeoIP enrichment for geographic threat visualization, and intelligent alerting via Discord.

---

## ✨ Features

- **Automatic Device Discovery**: GraphQL-based integration with Nautobot for device inventory
- **Rich Metadata**: Every metric tagged with device hostname, IP, vendor, model, role, and site
- **Multiple Telemetry Sources**: SNMP, syslog (RFC 3164), with support for NETCONF, gNMI, and others
- **GeoIP Enrichment**: Source IP geolocation (lat/lon/country) for firewall events
- **Geo-Visualization**: Grafana Geomap panels showing real-time attack origins on a world map
- **Pre-built Dashboards**: 7 Grafana dashboards organized into Network and Security folders
- **Intelligent Alerting**: Provisioned alert rules with Discord notifications via Alertmanager
- **Loki Ruler**: LogQL-based recording rules and spike detection for firewall events
- **Time-Series Storage**: VictoriaMetrics with configurable retention (default: 90 days)
- **Log Aggregation**: Loki + Promtail for structured log storage with label extraction
- **Self-signed SSL Support**: Development-friendly with certificate verification toggle
- **Extensible Architecture**: Add new receivers, processors, and exporters as needed

**Current Implementation**: ✅ **Operational** - Monitoring 2 Cisco switches + pfSense firewall via SNMP and syslog, with GeoIP threat visualization and Discord alerting.

---

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Nautobot instance with API access (optional, for automatic device discovery)
- Network devices with SNMP/syslog enabled
- Python 3.12+ (for device discovery script)

### Installation

1. **Clone and configure:**
   ```bash
   git clone https://github.com/byrn-baker/convergence.git
   cd convergence

   # Copy and edit environment variables
   cp .env.example .env
   # Edit .env with your Nautobot URL, API token, SNMP community, and Discord webhook
   ```

2. **Start the stack:**
   ```bash
   docker compose up -d
   ```

3. **Discover devices from Nautobot (optional):**
   ```bash
   # List devices
   python3 scripts/nautobot_device_discovery.py --list-devices

   # Generate OTEL Collector configuration
   python3 scripts/nautobot_device_discovery.py --generate-config
   ```

4. **Update OTEL configuration:**
   - Copy the generated receivers and processors to `config/otel-collector/config.yaml`
   - Restart OTEL Collector: `docker compose restart otel-collector`

5. **Access Grafana:**
   - URL: http://localhost:3000
   - Default credentials: admin / admin
   - Dashboards are pre-loaded in the Network and Security folders

### Validation

```bash
# Check stack health
docker compose ps

# Verify metrics in VictoriaMetrics
curl http://localhost:8428/api/v1/label/device_name/values

# Check interface count
curl 'http://localhost:8428/api/v1/query?query=count(interface_in_octets_bytes_total)'

# Check Loki alerting rules
curl http://localhost:3100/loki/api/v1/rules

# Verify Alertmanager is healthy
curl http://localhost:9093/-/healthy
```

---

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Nautobot (External)                       │
│              Source of Truth for Inventory                   │
└──────────────────────────┬───────────────────────────────────┘
                           │ GraphQL API
                           v
                  ┌─────────────────┐
                  │ Device Discovery│
                  │     Script      │
                  └────────┬─────────┘
                           │ Auto-generates config
                           v
┌─────────────────────────────────────────────────────────────┐
│                     Network Devices                          │
│         Cisco, Juniper, Arista (SNMP enabled)               │
│         pfSense (Syslog + SNMP enabled)                      │
└──────────────────────────┬───────────────────────────────────┘
                           │ SNMP polling (60s)
                           │ Syslog (port 514 UDP/TCP)
                           v
┌─────────────────────────────────────────────────────────────┐
│              OpenTelemetry Collector                          │
│    • SNMP receivers (per device)                             │
│    • Syslog receiver (RFC 3164)                              │
│    • Filterlog regex parser (pfSense firewall events)        │
│    • GeoIP processor (src/dst lat, lon, country)             │
│    • Attributes processors (device metadata)                 │
│    • Count/firewall connector (logs → metrics)               │
│    • Prometheus Remote Write exporter → VictoriaMetrics      │
│    • File exporter → /data/syslog/syslog.jsonl               │
└───────────────┬──────────────────────┬───────────────────────┘
                │                      │
                v                      v
┌──────────────────────┐   ┌──────────────────────────────────┐
│    VictoriaMetrics    │   │           Promtail               │
│  firewall_events_total│   │  Regex extracts Loki labels from │
│  system_uptime_seconds│   │  OTLP JSON: action, log_type,    │
│  interface_in/out_*   │   │  src_country, interface          │
│  (90d retention)      │   └──────────────┬───────────────────┘
└──────────┬────────────┘                  │
           │                              v
           │                  ┌──────────────────────┐
           │                  │         Loki          │
           │                  │  Log storage + Ruler  │
           │                  │  Recording rules:     │
           │                  │  blocks_by_country    │
           │                  │  Alert rules → AM     │
           │                  └──────────┬────────────┘
           │                             │
           │                             v
           │                  ┌──────────────────────┐
           │                  │     Alertmanager      │
           │                  │  Routes: critical/    │
           │                  │  security/network     │
           │                  │  → Discord webhook    │
           │                  └──────────────────────┘
           │
           v
┌─────────────────────────────────────────────────────────────┐
│                    Grafana (port 3000)                        │
│                                                               │
│  Network/                      Security/                     │
│  ├─ Interface Utilization       ├─ pfSense Firewall Security  │
│  ├─ Interface Errors            │   ├─ Geomap: WAN Threats   │
│  ├─ Network Overview            │   └─ Attack analysis        │
│  ├─ Platform Health             └─ Threat Analysis            │
│  └─ Network Device Health           ├─ Top countries          │
│      ├─ Uptime stats                ├─ Protocol distribution  │
│      ├─ Error rates                 └─ Attack timeseries      │
│      └─ Bandwidth per device                                  │
│                                                               │
│  Unified Alerting → Discord (5 provisioned rules)            │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
convergence/
├── config/
│   ├── otel-collector/
│   │   ├── config.yaml              # Main OTEL Collector configuration
│   │   └── receivers/
│   │       └── home-lab.yaml        # Device-specific SNMP receivers + processors
│   ├── victoriametrics/
│   │   └── prometheus.yml           # Scrape configuration
│   ├── loki/
│   │   ├── local-config.yaml        # Loki configuration (ruler enabled)
│   │   └── rules/
│   │       └── fake/
│   │           └── firewall_alerts.yaml  # LogQL recording + alerting rules
│   ├── promtail/
│   │   └── config.yaml              # Promtail log shipping + label extraction
│   ├── alertmanager/
│   │   └── alertmanager.yml         # Alert routing configuration
│   └── grafana/
│       └── provisioning/
│           ├── datasources/         # VictoriaMetrics + Loki data sources
│           ├── dashboards/          # Dashboard folder providers
│           └── alerting/
│               ├── alert_rules.yaml          # 5 provisioned alert rules
│               ├── contact_points.yaml       # Discord, Webhook, Email, Do Nothing
│               └── notification_policies.yaml # Routing tree → Discord
│
├── dashboards/
│   ├── network/
│   │   ├── interface-utilization.json
│   │   ├── interface-errors.json
│   │   ├── network-overview.json
│   │   ├── platform-health.json
│   │   └── device-health.json       # Uptime, error rates, bandwidth per device
│   ├── security/
│   │   ├── pfsense-firewall-security.json   # Geomap + firewall event analysis
│   │   └── threat-analysis.json             # Country breakdown, attack trends
│   ├── cisco/                       # Reserved for vendor-specific dashboards
│   ├── juniper/
│   └── arista/
│
├── scripts/
│   ├── nautobot_device_discovery.py # Device discovery and config generation
│   └── setup-geoip.sh               # GeoIP database installer
│
├── docs/
│   ├── PROJECT_STATUS.md            # Detailed project status and history
│   ├── PHASE3_ALERTING.md           # Phase 3: alerting, geo-viz, dashboard guide
│   ├── FIREWALL-SECURITY-DASHBOARD.md
│   ├── NAUTOBOT_ENRICHMENT.md
│   └── quickstart/
│
├── data/
│   ├── geoip/                       # MaxMind GeoLite2-City.mmdb
│   └── otelcol/                     # OTEL file exporter output (syslog.jsonl)
│
├── docker-compose.yml               # Docker services orchestration
├── .env.example                     # Environment variables template
├── validate_stack.sh                # Stack health validation
└── validate_nautobot.sh             # Nautobot integration validation
```

---

## 🔌 Service Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| VictoriaMetrics API | http://localhost:8428 | N/A |
| Loki API | http://localhost:3100 | N/A |
| Alertmanager | http://localhost:9093 | N/A |
| Promtail Metrics | http://localhost:9080 | N/A |
| OTEL Collector Health | http://localhost:13133 | N/A |
| OTEL Collector Metrics | http://localhost:8888 | N/A |
| Redis | localhost:6379 | N/A (future use) |

---

## 📈 Available Dashboards

### Network Folder

1. **Interface Utilization** — Traffic rates in bps, top interfaces, per-interface in/out graphs
2. **Interface Errors** — Error rates, top interfaces by errors, historical trends
3. **Network Overview** — Device count, total interfaces, platform-wide metrics
4. **Platform Health** — OTEL Collector, VictoriaMetrics, and service health metrics
5. **Network Device Health** *(new)*
   - Per-device uptime stats with colour thresholds (green ≥1d, orange ≥10m, red <10m)
   - Uptime history timeseries — drops to near-zero indicate reboots
   - Interface error rates (table + timeseries, only shows interfaces with active errors)
   - Total bandwidth per device (IN + OUT in bps)

### Security Folder

6. **pfSense Firewall Security**
   - Geomap: WAN threats — blocked IPs plotted by source lat/lon, sized by block count
   - Geomap: Traffic destinations
   - Top 100 blocked source IPs table
   - Firewall actions over time (pass vs block)
   - Protocol and interface distribution

7. **Threat Analysis** *(new)*
   - Stats: total blocks (24h), attacking countries, current block rate (blocks/min)
   - Top 10 attacking countries (horizontal bar chart)
   - Protocol distribution (donut chart)
   - Attack rate by country over time (top 7, 15m rolling rate)
   - Blocks by interface (stacked timeseries)
   - Full sortable country breakdown table

---

## 🔔 Alerting

Five provisioned alert rules evaluate every 1–2 minutes:

### Security Alerts
| Rule | Condition |
|------|-----------|
| High Block Rate From Country (1h) | >1000 blocks from one country in 1h |
| Firewall Block Rate Spike (5m) | >500 total blocks in 5m |

### Network Health Alerts
| Rule | Condition |
|------|-----------|
| Network Switch Rebooted | Uptime counter drops (negative delta) |
| Network Switch Low Uptime | Any switch uptime <10 minutes |
| Network Device SNMP Unreachable | No SNMP data for >5 minutes |

All alerts route to **Discord** by default. Set `DISCORD_WEBHOOK_URL` in `.env` and run:
```bash
docker compose up -d --force-recreate grafana
```

Test the Discord contact point:
```bash
curl -s -u admin:admin \
  -X POST http://localhost:3000/api/v1/provisioning/contact-points/convergence-discord/test \
  -H "Content-Type: application/json" -d '{}'
```

See [docs/PHASE3_ALERTING.md](docs/PHASE3_ALERTING.md) for full alerting documentation.

---

## 📖 Documentation

For detailed information, see the [docs](docs/) folder:

- **[Project Status](docs/PROJECT_STATUS.md)**: Current capabilities, recent improvements, lessons learned, and roadmap
- **[Phase 3 Alerting Guide](docs/PHASE3_ALERTING.md)**: Alerting pipeline, geo-visualization, dashboard organization, and troubleshooting
- **[Nautobot Integration](docs/NAUTOBOT_ENRICHMENT.md)**: Setup guide for Nautobot API integration
- **[Firewall Dashboard Example](docs/FIREWALL-SECURITY-DASHBOARD.md)**: pfSense integration guide
- **[Quick Start Guide](docs/quickstart/)**: Step-by-step deployment instructions

---

## 🛠️ Configuration

### Environment Variables

Key variables in `.env`:

```bash
# Nautobot Configuration (optional)
NAUTOBOT_URL=https://your-nautobot-instance
NAUTOBOT_TOKEN=your-api-token-here
NAUTOBOT_VERIFY_SSL=false  # For self-signed certificates

# SNMP Configuration
SNMP_COMMUNITY=public

# MaxMind GeoIP (required for geographic threat visualization)
# Run scripts/setup-geoip.sh to download the database
MAXMIND_ACCOUNT_ID=your_account_id
MAXMIND_LICENSE_KEY=your_license_key

# VictoriaMetrics
VM_RETENTION_PERIOD=90d

# Grafana
GRAFANA_ADMIN_PASSWORD=admin

# Alerting — Discord webhook for alert notifications
# Server Settings → Integrations → Webhooks → New Webhook → Copy URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN

# Generic webhook (Slack, n8n, custom endpoint)
# ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...
```

See [.env.example](.env.example) for all available options.

### Important: Applying Environment Variable Changes

`docker compose restart` does **not** apply env var changes. Use `--force-recreate`:
```bash
docker compose up -d --force-recreate grafana
```

---

## 🔄 Workflow: Adding New Devices

1. **Add device to Nautobot:**
   - Create device with primary IPv4 address
   - Set device type, manufacturer, role, and location
   - Ensure status is "Active"

2. **Generate configuration:**
   ```bash
   python3 scripts/nautobot_device_discovery.py --generate-config
   ```

3. **Update OTEL Collector:**
   - Add generated receivers and processors to `config/otel-collector/receivers/home-lab.yaml`
   - The pipeline in `config.yaml` already includes new receivers automatically

4. **Restart collector:**
   ```bash
   docker compose restart otel-collector
   ```

5. **Verify in Grafana:**
   - Check Network Overview and Network Device Health dashboards
   - Confirm device appears with correct metadata

---

## 🧪 Testing & Validation

```bash
# Full stack validation
./validate_stack.sh

# Nautobot connectivity test
./validate_nautobot.sh

# Check discovered devices
python3 scripts/nautobot_device_discovery.py --list-devices

# Query VictoriaMetrics
curl 'http://localhost:8428/api/v1/label/device_name/values'
curl 'http://localhost:8428/api/v1/query?query=system_uptime_seconds'

# Check Loki ruler rules
curl http://localhost:3100/loki/api/v1/rules

# List Grafana alert rules
curl -s -u admin:admin http://localhost:3000/api/v1/provisioning/alert-rules | \
  python3 -c "import sys,json; [print(r['uid'],'-',r['title']) for r in json.load(sys.stdin)]"

# Verify Discord contact point loaded
curl -s -u admin:admin http://localhost:3000/api/v1/provisioning/contact-points | \
  python3 -c "import sys,json; [print(f['name'],'-',f['type']) for f in json.load(sys.stdin)]"
```

---

## 🎯 Current Status

### ✅ Working Features
- Automatic device discovery from Nautobot (GraphQL)
- SNMP monitoring: 2 Cisco switches + pfSense firewall (uptime, interfaces, bandwidth, errors)
- Full device metadata enrichment (name, IP, vendor, model, role, site)
- Real interface names (e.g., "GigabitEthernet1/0/1")
- pfSense syslog ingestion with filterlog parsing and GeoIP enrichment
- `firewall_events_total` metric with geo labels (src_lat, src_lon, src_country)
- 7 Grafana dashboards in organized Network/Security folders
- Loki ruler: LogQL recording rules and spike detection alerting
- 5 provisioned Grafana alert rules (security + network health)
- Discord alerting via Alertmanager and Grafana Unified Alerting
- 90-day metrics retention in VictoriaMetrics

### 🎯 Next Steps (Phase 4)
- Automated pfSense response: add block rules via API when under attack
- Dynamic baselines: MetricsQL `outlier_iqr_over_time()` to replace fixed thresholds
- AI integration: LLM-powered natural language security summaries
- Multi-site: extend Alertmanager routing for multiple pfSense instances
- Additional protocols: NETCONF, gNMI

See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for detailed roadmap.

---

## 💡 Example Use Cases

The platform can be adapted for various observability scenarios:

1. **Network Device Monitoring** *(Current Primary Use)*
   - SNMP polling of switches, routers, firewalls
   - Interface utilization and error tracking
   - Device health and uptime monitoring with reboot detection

2. **Firewall/Security Monitoring** *(Implemented)*
   - Syslog ingestion from pfSense
   - Log parsing, GeoIP enrichment, log-to-metrics conversion
   - Geographic threat visualization with real-time Geomap panels
   - Country-based attack analysis and spike alerting to Discord

3. **Application Monitoring** *(Potential)*
   - OTLP metrics from applications
   - Log aggregation from services
   - Custom metric collection

4. **Infrastructure Monitoring** *(Potential)*
   - System metrics from servers
   - Container metrics from Docker/Kubernetes
   - Cloud resource monitoring

---

## 🤝 Contributing

Contributions welcome! If you encounter issues or have improvements:

1. Check [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for known limitations
2. Document your environment and steps to reproduce
3. Include relevant logs and error messages
4. Submit detailed bug reports or pull requests

---

## 📝 License

MIT License - See [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Built with [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- Powered by [VictoriaMetrics](https://victoriametrics.com/)
- Visualized with [Grafana](https://grafana.com/)
- Integrated with [Nautobot](https://nautobot.com/)
- Log aggregation with [Grafana Loki](https://grafana.com/oss/loki/)
- Alert routing with [Prometheus Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)

---

**Need Help?** Check the [documentation](docs/) or [PHASE3_ALERTING.md](docs/PHASE3_ALERTING.md) for detailed troubleshooting guides.
