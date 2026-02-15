# pfSense Firewall Integration Guide

**Last Updated:** 2026-02-14

This guide covers integrating pfSense firewall monitoring into the Convergence platform for both interface statistics (SNMP) and security event tracking (syslog).

---

## Overview

pfSense integration provides:
- **Interface Monitoring**: Traffic, errors, and utilization via SNMP
- **Security Events**: Firewall blocks/allows, attacking IPs via syslog
- **System Metrics**: CPU, memory, states, gateway status
- **Real-time Visibility**: Live dashboard of firewall activity

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              pfSense Firewall (192.168.100.1)           │
│                                                          │
│  SNMP Agent (UDP 161)    Syslog (UDP 514)              │
│       │                         │                        │
│       │ Interface Stats         │ Firewall Logs         │
│       │ System Metrics          │ (blocks, allows)      │
└───────┼─────────────────────────┼──────────────────────┘
        │                         │
        v                         v
┌─────────────────────────────────────────────────────────┐
│           OpenTelemetry Collector                        │
│                                                          │
│  SNMP Receiver          Syslog Receiver                 │
│  • ifDescr names        • Parse filterlog               │
│  • Interface metrics    • Extract IPs/ports             │
│  • System uptime        • Action (block/pass)           │
│                                                          │
│  Attributes Processor   Log Transform Processor         │
│  • device.name          • Extract src_ip                │
│  • device.role          • Extract dst_ip                │
│  • device.site          • Extract protocol              │
│  • device.vendor        • Extract dst_port              │
└───────────────────┬─────────────────────────────────────┘
                    │
                    v
┌─────────────────────────────────────────────────────────┐
│              VictoriaMetrics                             │
│                                                          │
│  Metrics:                    Logs → Metrics:            │
│  • interface_in_octets       • pfsense_blocks_total     │
│  • interface_out_octets      • pfsense_allows_total     │
│  • interface_errors          • by src_ip, dst_port      │
│  • system_uptime             • by protocol              │
└───────────────────┬─────────────────────────────────────┘
                    │
                    v
┌─────────────────────────────────────────────────────────┐
│                  Grafana Dashboards                      │
│                                                          │
│  1. pfSense Interface Dashboard                         │
│     • WAN/LAN/OPT traffic                               │
│     • Interface errors                                   │
│     • Top interfaces                                     │
│                                                          │
│  2. pfSense Security Dashboard                          │
│     • Blocked connections                                │
│     • Top attacking IPs                                  │
│     • Top blocked ports                                  │
│     • Block/allow ratio                                  │
│     • Recent blocks table                                │
└─────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- pfSense 2.5+ (tested with 2.7)
- Network access from Docker host to pfSense (SNMP: 161, Syslog: 514)
- Nautobot with API access
- Convergence platform deployed and operational

---

## Part 1: pfSense Configuration

### Step 1: Enable SNMP on pfSense

1. **Navigate to Services → SNMP**

2. **Configure SNMP Daemon:**
   ```
   [✓] Enable SNMP daemon

   SNMP Modules:
   [✓] All modules

   Polling Port: 161

   System Location: Your Location
   System Contact: admin@example.com

   Read Community String: public
   (or use your custom SNMP_COMMUNITY from .env)

   [✓] Enable interface array (ifIndex)
   ```

3. **Click Save**

4. **Verify SNMP is running:**
   ```bash
   # From your Docker host
   snmpwalk -v2c -c public 192.168.100.1 system
   ```

### Step 2: Configure Syslog on pfSense

1. **Navigate to Status → System Logs → Settings**

2. **Scroll to Remote Logging Options:**
   ```
   [✓] Send log messages to remote syslog server

   Remote Log Servers:
   <YOUR_DOCKER_HOST_IP>:514

   (e.g., 192.168.100.10:514 if that's your Docker host)

   Remote Syslog Contents:
   [✓] System Events
   [✓] Firewall Events  ← CRITICAL for security monitoring
   [✓] DHCP Events
   [✓] Gateway Events
   [✓] Routing Events
   [✓] Wireless Events
   [✓] OpenVPN Events (if using VPN)
   ```

3. **Click Save**

### Step 3: Firewall Rules (if needed)

Ensure pfSense can reach your Docker host:

1. **Navigate to Firewall → Rules → LAN** (or appropriate interface)

2. **Add rule allowing SNMP and Syslog:**
   - Action: Pass
   - Protocol: UDP
   - Source: LAN net (or pfSense host address)
   - Destination: <Docker host IP>
   - Destination Port Range: 161, 514

---

## Part 2: Nautobot Configuration

### Add pfSense Device to Nautobot

1. **Login to Nautobot**: https://192.168.100.36

2. **Navigate to Devices → Add Device**

3. **Create pfSense Device:**
   ```
   Name: pfSense-FW01
   Device Type:
     - Create new: "pfSense Firewall"
     - Or select existing
   Manufacturer:
     - Create new: "Netgate" or "pfSense"
   Device Role: firewall
   Site: Your site (e.g., "House")
   Status: Active
   Primary IPv4: 192.168.100.1/32
   ```

4. **Save**

5. **Verify in Discovery Script:**
   ```bash
   python3 scripts/nautobot_device_discovery.py --list-devices
   ```

   Should show:
   ```
   • pfSense-FW01
     IP: 192.168.100.1
     Vendor: Netgate (or pfSense)
     Role: firewall
     Site: House
     Status: Active
   ```

---

## Part 3: Generate OTEL Configuration

### Generate pfSense SNMP Configuration

```bash
# Generate configuration for all devices including pfSense
python3 scripts/nautobot_device_discovery.py --generate-config > /tmp/pfsense_otel.yaml

# Extract just the pfSense sections
grep -A100 "pfsense" /tmp/pfsense_otel.yaml
```

This will generate:
- SNMP receiver for pfSense (snmp/pfsense-fw01)
- Attributes processor with Nautobot metadata (attributes/pfsense-fw01)
- Pipeline configuration (metrics/pfsense-fw01)

---

## Part 4: OTEL Collector Configuration

### Add pfSense SNMP Receiver

Add to `config/otel-collector/config.yaml` in the receivers section:

```yaml
receivers:
  # ... existing receivers ...

  # pfSense-FW01 - 192.168.100.1
  snmp/pfsense-fw01:
    collection_interval: 60s
    endpoint: "udp://192.168.100.1:161"
    version: v2c
    community: ${env:SNMP_COMMUNITY}
    attributes:
      interface.name:
        oid: "1.3.6.1.2.1.2.2.1.2"  # ifDescr
        indexed_value_prefix: ""
      interface.description:
        oid: "1.3.6.1.2.1.31.1.1.1.18"  # ifAlias
        indexed_value_prefix: ""
    metrics:
      system.uptime:
        unit: "s"
        gauge:
          value_type: int
        scalar_oids:
          - oid: "1.3.6.1.2.1.1.3.0"

      interface.in.octets:
        unit: "By"
        sum:
          aggregation: cumulative
          monotonic: true
          value_type: int
        column_oids:
          - oid: "1.3.6.1.2.1.2.2.1.10"  # ifInOctets
            attributes:
              - name: interface.name

      interface.out.octets:
        unit: "By"
        sum:
          aggregation: cumulative
          monotonic: true
          value_type: int
        column_oids:
          - oid: "1.3.6.1.2.1.2.2.1.16"  # ifOutOctets
            attributes:
              - name: interface.name

      interface.in.errors:
        unit: "1"
        sum:
          aggregation: cumulative
          monotonic: true
          value_type: int
        column_oids:
          - oid: "1.3.6.1.2.1.2.2.1.14"  # ifInErrors
            attributes:
              - name: interface.name

      interface.out.errors:
        unit: "1"
        sum:
          aggregation: cumulative
          monotonic: true
          value_type: int
        column_oids:
          - oid: "1.3.6.1.2.1.2.2.1.20"  # ifOutErrors
            attributes:
              - name: interface.name

      # pfSense-specific: number of states
      pfsense.states:
        unit: "1"
        gauge:
          value_type: int
        scalar_oids:
          - oid: "1.3.6.1.4.1.12325.1.200.1.3.1.0"  # pfStateTableCount
```

### Add pfSense Attributes Processor

Add to processors section:

```yaml
processors:
  # ... existing processors ...

  # pfSense-FW01 metadata
  attributes/pfsense-fw01:
    actions:
      - key: device.name
        value: "pfSense-FW01"
        action: insert
      - key: device.ip
        value: "192.168.100.1"
        action: insert
      - key: device.vendor
        value: "Netgate"  # or "pfSense"
        action: insert
      - key: device.model
        value: "pfSense"  # Update with actual model from Nautobot
        action: insert
      - key: device.role
        value: "firewall"
        action: insert
      - key: device.site
        value: "House"
        action: insert
```

### Add pfSense Log Processing (for Security Events)

Add to processors section:

```yaml
processors:
  # ... existing processors ...

  # Parse pfSense filterlog format
  transform/pfsense_logs:
    log_statements:
      - context: log
        statements:
          # Extract firewall action from filterlog
          - set(attributes["firewall.action"], "unknown")
          - set(attributes["firewall.action"], "block") where IsMatch(body, "filterlog.*block")
          - set(attributes["firewall.action"], "pass") where IsMatch(body, "filterlog.*pass")

          # Extract source IP using regex
          - set(attributes["source.ip"], "0.0.0.0")
          - replace_pattern(attributes["source.ip"], ".*SRC=([0-9.]+).*", "$$1") where IsMatch(body, "SRC=")

          # Extract destination IP
          - set(attributes["destination.ip"], "0.0.0.0")
          - replace_pattern(attributes["destination.ip"], ".*DST=([0-9.]+).*", "$$1") where IsMatch(body, "DST=")

          # Extract protocol
          - set(attributes["network.protocol"], "unknown")
          - replace_pattern(attributes["network.protocol"], ".*PROTO=([A-Z]+).*", "$$1") where IsMatch(body, "PROTO=")

          # Extract destination port
          - set(attributes["destination.port"], "0")
          - replace_pattern(attributes["destination.port"], ".*DPT=([0-9]+).*", "$$1") where IsMatch(body, "DPT=")

          # Add device context
          - set(resource.attributes["device.name"], "pfSense-FW01")
          - set(resource.attributes["device.role"], "firewall")

  # Convert logs to metrics for counting
  metrics/pfsense_events:
    resource_attributes:
      - key: device.name
        value: pfSense-FW01
```

### Add pfSense Pipeline

Add to service.pipelines section:

```yaml
service:
  pipelines:
    # ... existing pipelines ...

    # Metrics pipeline - pfSense
    metrics/pfsense-fw01:
      receivers: [snmp/pfsense-fw01]
      processors: [memory_limiter, attributes/pfsense-fw01, resource, batch]
      exporters: [prometheusremotewrite, debug]

    # Logs pipeline - pfSense Security Events
    logs/pfsense:
      receivers: [syslog]
      processors: [memory_limiter, transform/pfsense_logs, batch]
      exporters: [debug]
```

---

## Part 5: Apply Configuration

### Restart OTEL Collector

```bash
# Validate configuration first
docker exec convergence-otel-collector otelcol-contrib validate --config=/etc/otelcol/config.yaml

# If valid, restart
docker restart convergence-otel-collector

# Check logs
docker logs -f convergence-otel-collector | grep -i pfsense
```

### Verify Data Collection

```bash
# Check if pfSense metrics are in VictoriaMetrics
curl -s 'http://localhost:8428/api/v1/label/device_name/values' | grep -i pfsense

# Check interface metrics
curl -s 'http://localhost:8428/api/v1/query?query=interface_in_octets_bytes_total{device_name="pfSense-FW01"}'

# Check for firewall event logs
docker logs convergence-otel-collector | grep "firewall.action"
```

---

## Part 6: Grafana Dashboards

### Dashboard 1: pfSense Interface Monitoring

**File**: `dashboards/pfsense/interface-monitoring.json`

**Panels to include:**

1. **WAN Interface Traffic (bits/sec)**
   ```promql
   rate(interface_in_octets_bytes_total{device_name="pfSense-FW01",interface_name=~".*wan.*|.*WAN.*"}[5m]) * 8
   ```

2. **LAN Interface Traffic**
   ```promql
   rate(interface_in_octets_bytes_total{device_name="pfSense-FW01",interface_name=~".*lan.*|.*LAN.*"}[5m]) * 8
   ```

3. **All Interfaces Table**
   ```promql
   sum by (interface_name) (rate(interface_in_octets_bytes_total{device_name="pfSense-FW01"}[5m]) * 8)
   ```

4. **Interface Errors**
   ```promql
   rate(interface_in_errors_total{device_name="pfSense-FW01"}[5m])
   ```

5. **System Uptime**
   ```promql
   system_uptime{device_name="pfSense-FW01"}
   ```

### Dashboard 2: pfSense Security Events

**File**: `dashboards/pfsense/security-monitoring.json`

**Panels to include:**

1. **Blocked Connections (24h)**
   ```promql
   sum(increase(pfsense_firewall_blocks_total[24h]))
   ```

2. **Top 20 Attacking IPs**
   ```promql
   topk(20, sum by (source_ip) (increase(pfsense_firewall_blocks_total[1h])))
   ```

3. **Top Blocked Destination Ports**
   ```promql
   topk(10, sum by (destination_port) (increase(pfsense_firewall_blocks_total[1h])))
   ```

4. **Blocks by Protocol**
   ```promql
   sum by (network_protocol) (rate(pfsense_firewall_blocks_total[5m]))
   ```

5. **Block Rate (per second)**
   ```promql
   rate(pfsense_firewall_blocks_total[5m])
   ```

6. **Recent Blocks Table**
   - Query: Recent log entries with firewall.action="block"
   - Columns: Timestamp, Source IP, Destination IP, Port, Protocol

---

## Common pfSense Interface Names

pfSense uses these typical interface naming conventions:

- **WAN**: `em0`, `igb0`, `re0`, `vtnet0` (physical)
- **LAN**: `em1`, `igb1`, `re1`, `vtnet1` (physical)
- **OPT1/2/3**: Additional physical interfaces
- **VLANs**: `em0.100`, `igb0.200` (VLAN tagging)
- **VPN**: `openvpn`, `tun0`, `ovpns1`
- **PPPoE**: `pppoe0`
- **Bridge**: `bridge0`, `bridge1`

Use these patterns in dashboard queries to filter specific interfaces.

---

## Troubleshooting

### SNMP Not Working

```bash
# Test SNMP from Docker host
docker exec convergence-otel-collector sh -c "apk add net-snmp-tools && snmpwalk -v2c -c public 192.168.100.1 system"

# Check firewall rules on pfSense
# Ensure pfSense → Docker host UDP 161 is allowed

# Verify SNMP is enabled
# Status → Services → check if snmpd is running
```

### Syslog Not Received

```bash
# Check if syslog receiver is listening
docker exec convergence-otel-collector netstat -uln | grep 514

# Test from pfSense shell
logger -h <docker-host-ip> -p local0.info "Test syslog message from pfSense"

# Check OTEL logs
docker logs convergence-otel-collector | grep syslog

# Verify firewall allows UDP 514 from pfSense to Docker host
```

### No Firewall Events in Logs

- Ensure "Firewall Events" is checked in pfSense syslog settings
- Generate test traffic: Try to access blocked site or ping blocked IP
- Check pfSense log: Status → System Logs → Firewall to confirm events exist
- Verify log format matches parser expectations

### Interface Names Not Showing

- Check SNMP receiver has `indexed_value_prefix: ""` (empty string)
- Verify OID 1.3.6.1.2.1.2.2.1.2 returns interface names
- Use `snmpwalk -v2c -c public 192.168.100.1 1.3.6.1.2.1.2.2.1.2` to test

---

## Performance Considerations

### SNMP Polling

- Default: 60 second intervals
- pfSense can handle frequent polling
- Reduce to 30s for more real-time data if needed
- Monitor OTEL Collector CPU usage

### Syslog Volume

- High-traffic firewalls generate significant log volume
- Consider log filtering on pfSense (only log blocks, not passes)
- Use OTEL Collector's tail_sampling processor if volume is too high
- Monitor VictoriaMetrics disk usage

### Recommended Settings

```yaml
# For busy pfSense (>1000 pps)
processors:
  memory_limiter:
    limit_mib: 1024  # Increase if needed
  batch:
    send_batch_size: 2048
    timeout: 5s
```

---

## Advanced: GeoIP Integration

For geographic IP visualization in Grafana:

1. **Add GeoIP Processor to OTEL:**
   ```yaml
   processors:
     geoip:
       context: log
       providers:
         maxmind:
           database_path: /etc/otelcol/GeoLite2-City.mmdb
   ```

2. **Download GeoLite2 Database:**
   ```bash
   # Get free account at maxmind.com
   wget https://download.maxmind.com/app/geoip_download?...
   ```

3. **Add to docker-compose.yml:**
   ```yaml
   volumes:
     - ./config/geoip/GeoLite2-City.mmdb:/etc/otelcol/GeoLite2-City.mmdb:ro
   ```

4. **Use Geomap Panel in Grafana:**
   - Panel type: Geomap
   - Query: Blocks by country
   - Visualization: Heatmap or markers

---

## Security Considerations

1. **SNMP Community String**: Change from "public" to strong community string
2. **Firewall Rules**: Restrict SNMP/Syslog to only your Docker host
3. **Log Sensitive Data**: Be aware logs may contain internal IPs/structure
4. **Data Retention**: Consider compliance requirements for firewall logs
5. **Access Control**: Restrict Grafana access to security dashboards

---

## Next Steps

1. ✅ Add pfSense to Nautobot
2. ✅ Enable SNMP and Syslog on pfSense
3. ✅ Generate and apply OTEL configuration
4. ✅ Verify data collection
5. ⏭️ Create Grafana dashboards
6. ⏭️ Set up alerting for security events
7. ⏭️ Consider adding pfSense Exporter for advanced metrics

---

## References

- [pfSense SNMP Documentation](https://docs.netgate.com/pfsense/en/latest/services/snmp.html)
- [pfSense Syslog Documentation](https://docs.netgate.com/pfsense/en/latest/monitoring/logs/settings.html)
- [pfSense Filter Log Format](https://docs.netgate.com/pfsense/en/latest/monitoring/logs/filter.html)
- [OTEL Log Transform Processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/transformprocessor)

---

**Status**: Ready for Implementation
**Estimated Setup Time**: 30-45 minutes
**Difficulty**: Intermediate
