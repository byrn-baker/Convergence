# pfSense Log Monitoring Setup Guide

## Overview

This guide shows you how to configure pfSense to send logs to the Convergence monitoring platform and view them in Grafana.

## ✅ What's Already Configured

The Convergence platform now includes:

- **Loki**: Log aggregation and storage system (port 3100)
- **Promtail**: Purpose-built log collector listening on UDP/TCP port 514
- **Grafana**: Loki datasource configured and ready to query logs
- **OTELCOL**: Handles metrics (SNMP) with Nautobot enrichment

## 📋 pfSense Configuration

### Step 1: Configure Syslog Remote Logging

1. Login to pfSense web interface (https://192.168.100.1)

2. Navigate to: **Status → System Logs → Settings**

3. Scroll to **Remote Logging Options**

4. Configure the following:
   ```
   ☑ Enable Remote Logging

   Source Address: (leave default - any)

   IP Protocol: IPv4

   Remote log servers:
      Server 1: <YOUR_DOCKER_HOST_IP>:514
      Server 2: (optional backup)

   Remote Syslog Contents:
      ☑ Everything
   ```

5. Click **Save** at the bottom of the page

### Step 2: Configure Firewall Log Settings

1. Still in **Status → System Logs → Settings**

2. In the **General Logging Options** section:
   ```
   ☑ Log packets matched from the default block rules in the ruleset
   ☑ Log packets matched from the default pass rules put in the ruleset
   ☑ Log packets blocked by 'Block Bogon Networks' rules
   ☑ Log packets blocked by 'Block Private Networks' rules
   ```

3. Set **Log Message Format** to: **syslog (RFC 5424, with RFC 3339 microsecond-precision timestamps)**

4. Click **Save**

### Step 3: Find Your Docker Host IP

On your Docker host machine, run:
```bash
hostname -I | awk '{print $1}'
```

Use this IP address in the pfSense remote logging configuration above.

## 🔍 Viewing Logs in Grafana

### Method 1: Explore View

1. Open Grafana: http://localhost:3000
2. Click **Explore** (compass icon) in the left sidebar
3. Select **Loki** as the datasource (top dropdown)
4. Use LogQL queries:

   **All pfSense logs:**
   ```
   {job="syslog"}
   ```

   **Filter by severity:**
   ```
   {job="syslog"} |= "error"
   ```

   **Firewall blocks only:**
   ```
   {job="syslog"} |= "block"
   ```

   **Show attacking IPs:**
   ```
   {job="syslog"} |= "block" | regexp "SRC=(?P<src_ip>[\\d.]+)"
   ```

### Method 2: Create a Dashboard

1. In Grafana, click **+** → **Dashboard**
2. Add a new panel
3. Select **Loki** as datasource
4. Choose visualization: **Logs** or **Time series**

**Example Panel Queries:**

**Firewall Blocks Over Time:**
```
sum(count_over_time({job="syslog"} |= "block" [1m]))
```

**Top Blocked Source IPs:**
```
topk(10, sum by (src_ip) (count_over_time({job="syslog"} |= "block" | regexp "SRC=(?P<src_ip>[\\d.]+)" [5m])))
```

**Failed SSH Attempts:**
```
{job="syslog"} |= "sshd" |= "Failed"
```

## 🧪 Testing the Setup

### 1. Send a Test Syslog Message

From your Docker host:
```bash
echo "<134>1 2026-02-14T10:30:00Z pfsense-test filterlog - - - TEST: Firewall test message" | nc -u localhost 514
```

### 2. Verify in Grafana Explore

1. Go to Grafana → Explore → Loki
2. Query: `{job="syslog"} |= "TEST"`
3. You should see your test message appear within 5-10 seconds

### 3. Generate Real pfSense Logs

From pfSense shell (Diagnostics → Command Prompt):
```bash
# Generate a test log entry
logger -p local0.info "TEST: Manual syslog test from pfSense"

# Or trigger a firewall block (if you have block rules)
ping -c 1 1.1.1.1  # If blocked, will generate log entry
```

## 📊 Useful Log Queries

### Security Monitoring

**All Blocked Connections:**
```
{job="syslog"} |= "filterlog" |= "block"
```

**Port Scans (multiple blocks from same IP):**
```
sum by (src_ip) (count_over_time({job="syslog"} |= "block" | regexp "SRC=(?P<src_ip>[\\d.]+)" [1m])) > 10
```

**Geo-location Context (requires GeoIP):**
```
{job="syslog"} |= "block" | regexp "SRC=(?P<src_ip>[\\d.]+)" | line_format "{{.src_ip}}"
```

### System Monitoring

**pfSense Service Restarts:**
```
{job="syslog"} |= "starting" or "stopping"
```

**DHCP Leases:**
```
{job="syslog"} |= "dhcpd" |= "DHCPACK" or "DHCPREQUEST"
```

**VPN Connections:**
```
{job="syslog"} |= "openvpn" or "ipsec"
```

## 🐛 Troubleshooting

### Logs Not Appearing in Loki

1. **Check Promtail is receiving syslogs:**
   ```bash
   docker logs convergence-promtail --tail 50 | grep -i error
   curl http://localhost:9080/metrics | grep promtail_sent_entries_total
   ```

2. **Verify Loki is healthy:**
   ```bash
   curl http://localhost:3100/ready
   ```

3. **Check pfSense can reach Docker host:**
   - From pfSense: **Diagnostics → Ping**
   - Enter your Docker host IP
   - Should show successful pings

4. **Verify firewall rules:**
   - pfSense needs to be able to reach Docker host on port 514/UDP
   - Check if any firewall rules on Docker host block UDP 514

5. **Check Promtail syslog receiver is listening:**
   ```bash
   docker port convergence-promtail
   ss -tulnp | grep :514
   ```

### Logs Delayed or Missing

- Loki batches logs for efficiency - expect 5-10 second delay
- Check OTEL Collector batch settings in config
- Verify time synchronization between pfSense and Docker host (NTP)

### LogQL Query Returns No Results

- Use broader queries first: `{job="syslog"}`
- Check time range selector in Grafana (top right)
- Verify Loki datasource is selected
- Check logs exist: `curl -G 'http://localhost:3100/loki/api/v1/label/__name__/values'`

## 📚 Additional Resources

- **LogQL Documentation**: https://grafana.com/docs/loki/latest/logql/
- **pfSense Logging**: https://docs.netgate.com/pfsense/en/latest/monitoring/logs/
- **Promtail Syslog**: https://grafana.com/docs/loki/latest/send-data/promtail/scraping/#syslog-receiver

## 🔐 Security Best Practices

1. **Restrict log sources**: Configure OTEL Collector to only accept syslogs from known IPs
2. **Use TLS**: For production, configure encrypted syslog transmission
3. **Log retention**: Configure Loki retention policies based on your requirements
4. **Access control**: Restrict Grafana access with proper authentication
5. **Sensitive data**: Be cautious about logging sensitive information

## ⏭️ Next Steps

- Create alerting rules for security events
- Set up log-based metrics for dashboard visualization
- Configure log retention policies
- Add correlation between logs and metrics
- Create role-based dashboard access
