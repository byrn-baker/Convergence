# Convergence Platform - Project Status

**Last Updated:** 2026-02-14
**Current Phase:** Phase 2 - Monitoring Foundation Complete

---

## Overview

The Convergence platform is a network monitoring and automation system that integrates OpenTelemetry Collector (OTELCOL), Nautobot as the source of truth, VictoriaMetrics for time-series data, and Grafana for visualization. The platform currently monitors network devices via SNMP with automatic device discovery from Nautobot.

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
