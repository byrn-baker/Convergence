# pfSense Firewall Security Dashboard

## Overview

The pfSense Firewall Security Dashboard provides comprehensive visibility into your firewall traffic with the following features:

### Dashboard Panels

1. **Blocked Events Rate Gauge** - Real-time rate of blocked events per second
2. **Firewall Actions Over Time** - Time series showing pass vs block actions
3. **Top 10 Blocked Source IPs** - Table of most frequently blocked source IPs
4. **Blocked Traffic by Protocol** - Pie chart showing protocol distribution
5. **Traffic by Interface** - Bar chart of traffic volume by interface
6. **Geographic Map** - World map showing blocked source IPs (requires GeoIP setup)
7. **Top Blocked Destination IPs** - Time series of blocked destinations
8. **Recent Firewall Events Summary** - Detailed table of recent events

## Accessing the Dashboard

1. Open Grafana: `http://localhost:3000`
2. Login with credentials:
   - Username: `admin`
   - Password: (check `.env` file for `GRAFANA_ADMIN_PASSWORD`)
3. Navigate to: **Dashboards** → **pfSense Firewall Security**

## Data Flow Architecture

```
pfSense/Cisco Switches (port 514 UDP/TCP)
  ↓
OTEL Collector (RFC 3164 syslog receiver)
  ↓
Parse pfSense filterlog format
  ↓
Extract: src_ip, dst_ip, action, direction, interface, protocol
  ↓
Enrich with Nautobot metadata (device.name, device.vendor, device.role, device.site)
  ↓
Convert logs to metrics (count connector)
  ↓
VictoriaMetrics (firewall_events metric)
  ↓
Grafana Dashboards
```

## Firewall Metrics

The `firewall_events` metric includes the following labels:
- `action` - pass or block
- `direction` - in or out
- `interface` - network interface name
- `proto_name` - protocol (tcp, udp, icmp, etc.)
- `src_ip` - source IP address
- `dst_ip` - destination IP address
- `device.name` - device name from Nautobot
- `device.vendor` - device vendor
- `device.role` - device role (firewall, switch, etc.)
- `device.site` - device site location

## Setting Up GeoIP for Geographic Visualization

To enable the geographic map showing where blocked traffic originates:

### Option 1: Grafana Cloud (Easiest)

If using Grafana Cloud, GeoIP lookups are built-in and automatic.

### Option 2: Self-Hosted with MaxMind GeoLite2

1. **Sign up for MaxMind GeoLite2** (free):
   - Visit: https://www.maxmind.com/en/geolite2/signup
   - Create an account and generate a license key

2. **Download GeoLite2 Database**:
   ```bash
   cd /home/ubuntu/Convergence
   mkdir -p data/geoip

   # Download GeoLite2-City database
   wget -O data/geoip/GeoLite2-City.mmdb.tar.gz \
     "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=YOUR_LICENSE_KEY&suffix=tar.gz"

   tar -xzf data/geoip/GeoLite2-City.mmdb.tar.gz -C data/geoip/ --strip-components=1
   ```

3. **Configure Grafana to use GeoIP**:

   Edit `config/grafana/grafana.ini` or add environment variable:
   ```ini
   [geomap]
   default_baselayer_config = {
     "type": "osm-standard"
   }

   [database]
   geoip_data_path = /var/lib/grafana/geoip/GeoLite2-City.mmdb
   ```

4. **Mount GeoIP database in docker-compose.yml**:
   ```yaml
   grafana:
     volumes:
       - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
       - ./dashboards:/var/lib/grafana/dashboards:ro
       - ./data/geoip:/var/lib/grafana/geoip:ro  # Add this line
       - grafana-data:/var/lib/grafana
   ```

5. **Restart Grafana**:
   ```bash
   docker-compose restart grafana
   ```

### Option 3: Use External GeoIP API

For real-time GeoIP enrichment at the OTEL Collector level, you can add a processor that calls an external API like:
- ipapi.co
- ip-api.com
- ipgeolocation.io

This would require custom OTEL Collector configuration with transform processors.

## Example Queries

### Top 10 Blocked IPs
```promql
topk(10, sum by (src_ip) (rate(firewall_events{action="block"}[5m])))
```

### Block Rate by Interface
```promql
sum by (interface) (rate(firewall_events{action="block"}[5m]))
```

### Protocol Distribution
```promql
sum by (proto_name) (rate(firewall_events[5m]))
```

### External vs Internal Blocked Traffic
```promql
# External (public IPs trying to get in)
sum(rate(firewall_events{action="block", direction="in", src_ip!~"^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.).*"}[5m]))

# Internal (private IPs blocked outbound)
sum(rate(firewall_events{action="block", direction="out", src_ip=~"^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.).*"}[5m]))
```

## Nautobot Integration

Device metadata is automatically enriched from Nautobot based on the syslog source. The enrichment adds:
- `device.name` - Friendly device name
- `device.vendor` - Manufacturer (e.g., Netgate, Cisco)
- `device.role` - Device role (firewall, switch, router)
- `device.site` - Physical location

To update device metadata:
1. Edit `/home/ubuntu/Convergence/config/otel-collector/config.yaml`
2. Update the `transform/syslog_enrichment` processor
3. Restart OTEL Collector: `docker restart convergence-otel-collector`

## Alerting Ideas

Set up Grafana alerts for:
1. **High Block Rate** - Alert when blocked events exceed threshold
2. **Suspicious Source IPs** - Alert on repeated blocks from same IP
3. **Port Scanning Detection** - Alert on high diversity of destination ports from single source
4. **Geographic Anomalies** - Alert on traffic from unexpected countries

## Troubleshooting

### No data showing in dashboard

1. Check if firewall metrics exist:
   ```bash
   curl "http://localhost:8428/api/v1/label/__name__/values" | jq '.data[] | select(. | contains("firewall"))'
   ```

2. Verify OTEL Collector is receiving syslogs:
   ```bash
   docker logs --tail 100 convergence-otel-collector | grep filterlog
   ```

3. Check if pfSense is sending syslogs:
   - pfSense: Status → System Logs → Settings
   - Verify remote logging is enabled to the correct IP/port

### IPs not showing on map

1. Ensure GeoIP database is configured (see setup instructions above)
2. Private IPs (192.168.x.x, 10.x.x.x) won't show on map - only public IPs
3. Check Grafana logs for GeoIP errors:
   ```bash
   docker logs convergence-grafana | grep -i geoip
   ```

## Performance Considerations

- The dashboard uses 30-second auto-refresh by default
- For high-traffic networks, consider:
  - Increasing aggregation intervals (5m → 15m)
  - Limiting topk() results
  - Adding recording rules in VictoriaMetrics for pre-aggregation

## Next Steps

1. **Set up Alerting** - Create alert rules for security events
2. **Add More Devices** - Configure Cisco switches to send syslogs
3. **Custom Enrichment** - Add threat intelligence feeds for known bad IPs
4. **Log Retention** - Configure Loki retention policies for historical analysis
5. **Advanced Analytics** - Use Loki LogQL for deep log analysis

## Related Documentation

- [OTEL Collector Configuration](../config/otel-collector/config.yaml)
- [Nautobot Device Discovery](../scripts/nautobot_device_discovery.py)
- [Grafana Provisioning](../config/grafana/provisioning/)
