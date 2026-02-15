# Convergence

**Network Observability Platform with Nautobot Integration**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/deployment-docker-2496ED.svg)](https://www.docker.com/)
[![Status](https://img.shields.io/badge/status-operational-success.svg)](docs/PROJECT_STATUS.md)

Convergence is a general-purpose observability platform that can be adapted to different monitoring use cases. Built on OpenTelemetry Collector, VictoriaMetrics, and Grafana, it provides a foundation for collecting, storing, and visualizing telemetry data from network devices and other sources. The platform features automatic device discovery from Nautobot and supports multiple telemetry protocols.

---

## ✨ Features

- **Automatic Device Discovery**: GraphQL-based integration with Nautobot for device inventory
- **Rich Metadata**: Every metric tagged with device hostname, IP, vendor, model, role, and site
- **Multiple Telemetry Sources**: SNMP, syslog (RFC 3164), with support for NETCONF, gNMI, and others
- **Pre-built Dashboards**: Ready-to-use Grafana dashboards for network monitoring
- **Time-Series Storage**: VictoriaMetrics with configurable retention (default: 1 year)
- **Log Aggregation**: Loki for centralized log storage and analysis
- **Self-signed SSL Support**: Development-friendly with certificate verification toggle
- **Extensible Architecture**: Add new receivers, processors, and exporters as needed

**Current Implementation**: ✅ **Operational** - Monitoring 2 Cisco switches via SNMP + pfSense firewall via syslog (example use case demonstrating log-to-metrics conversion and GeoIP visualization)

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
   # Edit .env with your Nautobot URL, API token, and SNMP community
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
   - Dashboards are pre-loaded and ready to use

### Validation

```bash
# Check stack health
docker compose ps

# Verify metrics in VictoriaMetrics
curl http://localhost:8428/api/v1/label/device_name/values

# Check interface count
curl 'http://localhost:8428/api/v1/query?query=count(interface_in_octets_bytes_total)'
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
│         pfSense, switches (Syslog enabled)                   │
└──────────────────────────┬───────────────────────────────────┘
                           │ SNMP polling (60s intervals)
                           │ Syslog (port 514 UDP/TCP)
                           v
┌─────────────────────────────────────────────────────────────┐
│              OpenTelemetry Collector                          │
│    • SNMP receivers (per device)                             │
│    • Syslog receiver (RFC 3164)                              │
│    • Attributes processors (Nautobot metadata)               │
│    • Transform processors (log parsing)                      │
│    • Count connector (logs → metrics)                        │
│    • Prometheus Remote Write exporter                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           v
┌─────────────────────────────────────────────────────────────┐
│                    VictoriaMetrics                            │
│              Time-Series Database (1yr retention)            │
└──────────────────────────┬───────────────────────────────────┘
                           │ Prometheus-compatible API
                           v
┌─────────────────────────────────────────────────────────────┐
│                        Grafana                                │
│    • Interface Utilization Dashboard                         │
│    • Interface Errors Dashboard                              │
│    • Network Overview Dashboard                              │
│    • Platform Health Dashboard                               │
│    • pfSense Security Dashboard (example)                    │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Principles:**
- **Nautobot as Source of Truth**: All device metadata comes from Nautobot
- **Device-Specific Pipelines**: Each device has its own OTEL pipeline for clean metadata tagging
- **GraphQL for Efficiency**: Single API call retrieves all device data and relationships
- **Real Interface Names**: Uses SNMP ifDescr OID for actual interface names (not index numbers)
- **Extensible Architecture**: Easy to add new receivers and processors for different use cases

---

## 📁 Project Structure

```
convergence/
├── config/
│   ├── otel-collector/
│   │   ├── config.yaml              # Main OTEL Collector configuration
│   │   └── receivers/
│   │       └── home-lab.yaml        # Device-specific receivers
│   ├── victoriametrics/
│   │   └── prometheus.yml           # Scrape configuration
│   ├── loki/
│   │   └── local-config.yaml        # Loki configuration
│   └── grafana/
│       └── provisioning/            # Datasource and dashboard provisioning
│
├── dashboards/
│   ├── unified/
│   │   ├── interface-utilization.json
│   │   ├── interface-errors.json
│   │   ├── network-overview.json
│   │   └── platform-health.json
│   └── pfsense-firewall-security.json  # Example security dashboard
│
├── scripts/
│   ├── nautobot_device_discovery.py # Device discovery and config generation
│   └── setup-geoip.sh               # GeoIP database installer (for map viz)
│
├── docs/
│   ├── PROJECT_STATUS.md            # Detailed project status and history
│   ├── FIREWALL-SECURITY-DASHBOARD.md  # Example: pfSense integration
│   ├── NAUTOBOT_ENRICHMENT.md       # Nautobot integration guide
│   └── quickstart/                  # Additional guides
│
├── data/
│   └── geoip/                       # Optional: MaxMind GeoLite2 for geo visualization
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
| OTEL Collector Health | http://localhost:13133 | N/A |
| OTEL Collector Metrics | http://localhost:8888 | N/A |
| Redis | localhost:6379 | N/A (future use) |

---

## 📈 Available Dashboards

1. **Interface Utilization**
   - Traffic rates in bps (bits per second)
   - Top interfaces by traffic
   - Per-interface in/out traffic graphs
   - Total interfaces monitored

2. **Interface Errors**
   - Error rates and accumulation
   - Top interfaces by errors
   - Interfaces with active errors
   - Historical error trends

3. **Network Overview**
   - Device count and status
   - Total interface count
   - Platform-wide metrics
   - Quick health summary

4. **Platform Health**
   - OTEL Collector metrics
   - VictoriaMetrics performance
   - System resource usage
   - Service health status

5. **pfSense Firewall Security** *(Example Use Case)*
   - Real-time firewall event monitoring
   - Geographic visualization of blocked IPs (GeoIP)
   - Traffic destination mapping
   - Attack analysis and protocol distribution
   - Demonstrates: syslog ingestion, log parsing, log-to-metrics conversion, GeoIP enrichment

---

## 📖 Documentation

For detailed information, see the [docs](docs/) folder:

- **[Project Status](docs/PROJECT_STATUS.md)**: Current capabilities, recent improvements, lessons learned, and roadmap
- **[Nautobot Integration](docs/NAUTOBOT_ENRICHMENT.md)**: Setup guide for Nautobot API integration
- **[Firewall Dashboard Example](docs/FIREWALL-SECURITY-DASHBOARD.md)**: pfSense integration guide (demonstrates syslog capabilities)
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

# MaxMind GeoIP (optional, for geographic visualization)
MAXMIND_ACCOUNT_ID=your_account_id
MAXMIND_LICENSE_KEY=your_license_key

# VictoriaMetrics
VM_RETENTION_PERIOD=1y

# Grafana
GRAFANA_ADMIN_USERNAME=admin
GRAFANA_ADMIN_PASSWORD=admin
```

See [.env.example](.env.example) for all available options.

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
   - Add generated receivers and processors to `config/otel-collector/config.yaml`
   - Add new pipelines to service section

4. **Restart collector:**
   ```bash
   docker compose restart otel-collector
   ```

5. **Verify in Grafana:**
   - Check Network Overview dashboard
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
curl 'http://localhost:8428/api/v1/query?query=count(interface_in_octets_bytes_total)'
```

---

## 🎯 Current Status

### ✅ Working Features
- Automatic device discovery from Nautobot (GraphQL)
- SNMP monitoring of 2 Cisco switches
- Full device metadata enrichment (name, IP, vendor, model, role, site)
- Real interface names (e.g., "GigabitEthernet1/0/1")
- 4 functional Grafana dashboards
- 1-year metrics retention in VictoriaMetrics
- Health validation scripts
- **Example Implementation**: pfSense syslog ingestion with log-to-metrics conversion and GeoIP visualization

### 🎯 Next Steps
- Add more interface metrics (discards, utilization percentage)
- Implement automated config refresh (cron job or webhook)
- SNMPv3 support
- Basic alerting rules
- Additional protocols (NETCONF, gNMI)

See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for detailed roadmap.

---

## 💡 Example Use Cases

The platform can be adapted for various observability scenarios:

1. **Network Device Monitoring** *(Current Primary Use)*
   - SNMP polling of switches, routers, firewalls
   - Interface utilization and error tracking
   - Device health monitoring

2. **Firewall/Security Monitoring** *(Implemented Example)*
   - Syslog ingestion from pfSense/firewalls
   - Log parsing and metric conversion
   - Geographic threat visualization with GeoIP
   - Attack analysis and blocked IP tracking

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

---

**Need Help?** Check the [documentation](docs/) or [project status](docs/PROJECT_STATUS.md) for detailed information.
