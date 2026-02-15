# Log Ingestion Diagnosis - February 15, 2026

## Problem Statement
Metrics with Nautobot enrichment ARE working in Grafana dashboards, but NO LOGS are appearing in Loki.

## Root Cause Analysis

### What We Discovered:
1. ✅ **Loki is healthy and functional** - Manual OTLP log test succeeded
2. ✅ **OTELCOL syslog receiver starts** - Listening on ports 514 UDP/TCP
3. ✅ **Metrics pipeline works perfectly** - SNMP data with Nautobot metadata flowing
4. ❌ **No Loki exporter exists in OTELCOL** - The `loki` exporter is NOT available in `otel/opentelemetry-collector-contrib`
5. ❌ **OTLP exporter incompatible with Loki's path** - Loki uses `/otlp/v1/logs` but OTLP exporter expects standard `/v1/logs`

### Key Findings:
- Loki OTLP endpoint: `http://loki:3100/otlp/v1/logs` ✅ WORKS (tested manually)
- OTELCOL OTLP exporter: Cannot use custom paths, only `host:port` format
- Attempted `otlp/loki` with `endpoint: "http://loki:3100/otlp"` → ERROR: "invalid port '3100/otlp'"
- No native Loki exporter available in OTELCOL contrib build

## Solution Options

### Option 1: Add Promtail (RECOMMENDED)
**Promtail** is Grafana's official log collector, designed specifically for Loki.

**Architecture:**
```
Network Devices → Syslog (514) → OTELCOL → ❌ (no Loki exporter)

BETTER:
Network Devices → Syslog (515) → Promtail → Loki Push API → Loki ✅
```

**Advantages:**
- Purpose-built for Loki ingestion
- Handles syslog natively (RFC 3164, RFC 5424)
- Built-in label extraction and parsing
- Lightweight and battle-tested
- Can scrape files, journal, and receive syslogs

### Option 2: Use Loki Docker Driver
Configure OTELCOL to output to stdout, use Loki Docker logging driver.

### Option 3: Direct to Loki
Configure devices to send logs directly to Loki's push API (port 3100), bypassing OTELCOL.

### Option 4: Fluentd/Fluent Bit
Use Fluentd/Fluent Bit as intermediary with Loki output plugin.

## Recommended Next Steps

1. **Add Promtail service** to docker-compose.yml
2. **Configure Promtail** to:
   - Listen for syslog on port 515 (or move from 514)
   - Forward to Loki's `/loki/api/v1/push`
   - Add labels for device identification
3. **Update pfSense/devices** to send logs to Promtail port
4. **Keep OTELCOL for metrics** - It's working perfectly for SNMP/telemetry

## Configuration Reference

### Promtail Syslog Config Example:
```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: syslog
    syslog:
      listen_address: 0.0.0.0:515
      labels:
        job: "syslog"
    relabel_configs:
      - source_labels: ['__syslog_message_hostname']
        target_label: 'host'
```

## Files Modified During Diagnosis
- `config/otel-collector/config.yaml` - Multiple exporter attempts
- `config/loki/local-config.yaml` - Tested OTLP distributor config (reverted)

## Commit Status
✅ Major refactoring committed: "Refactor to monitoring-first architecture with OTELCOL"
