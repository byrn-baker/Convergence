---
name: convergence-noc-watch
description: "Convergence NOC watch — scheduled health monitoring for HomeSwitch01, HomeSwitch02, pfSense-FW01, and Synology NAS devices. Checks device reachability, interface utilization, error rates, firewall block rate baselines, and critical syslog events. Use when running a NOC health check cycle or investigating device health."
user-invocable: true
metadata:
  { "openclaw": { "requires": { "env": ["PROMETHEUS_URL", "GRAFANA_URL", "GRAFANA_SERVICE_ACCOUNT_TOKEN"] } } }
---

# Convergence NOC Watch

Replaces the NOC Officer and Network Engineer agents. This is an L1/L2 health monitoring procedure for the Convergence home network.

## Network Inventory

| Device | IP | Model | Notes |
|--------|----|-------|-------|
| HomeSwitch01 | 192.168.3.2 | Cisco WS-C3850-48P | 48x 1G access, 4x 10G uplinks |
| HomeSwitch02 | 192.168.3.3 | Cisco WS-C3850-48P | 48x 1G access, 4x 10G uplinks |
| pfSense-FW01 | 192.168.100.1 | Netgate | WAN + LAN + DMZ |
| SynologyNAS01 | 192.168.100.22 | Synology | NAS |
| SynologyNAS02 | 192.168.100.23 | Synology | NAS |

## MCP Servers Used

| Server | Tools Used |
|--------|-----------|
| prometheus-mcp | `execute_query` for PromQL against VictoriaMetrics |
| grafana-mcp | `query_loki_logs` for syslog, `query_prometheus` as alternative |
| nautobot-mcp | `search_ip_addresses`, `get_ip_addresses` for port description lookups |
| pfsense-mcp | `pfsense_get_gateway_status`, `pfsense_get_system_info`, `pfsense_get_interfaces` |

## Health Check Procedure

Run all steps in order. Produce a summary table at the end.

### Step 1: Device Reachability (SNMP Uptime)

Query the uptime metric for each SNMP-monitored device:

```
execute_query(query="system_uptime_seconds")
```

For each device in the result:
- Extract `device_name` label and timestamp
- If the metric timestamp is >6 minutes old → device may be unreachable
- If the metric is missing entirely → check Loki for syslog from that device before declaring outage

**Thresholds:**
- Gap < 6 min → HEALTHY
- Gap 6–10 min → WARNING: possible SNMP timeout
- Gap > 10 min → CRITICAL: device unreachable (confirm with syslog check)

**Empty results ≠ outage.** If a metric returns no data, report INFO only. The metric may not be configured.

### Step 2: Interface Utilization

For each switch, query inbound and outbound octet rates:

```
execute_query(query="rate(interface_in_octets_bytes_total{device_name=\"HomeSwitch01\"}[5m]) * 8")
execute_query(query="rate(interface_out_octets_bytes_total{device_name=\"HomeSwitch01\"}[5m]) * 8")
```

Repeat for HomeSwitch02.

**Calculate utilization:**

| Interface prefix | Speed |
|-----------------|-------|
| GigabitEthernet / Gi | 1,000,000,000 bps (1G) |
| TenGigabitEthernet / Te | 10,000,000,000 bps (10G) |
| FastEthernet / Fa | 100,000,000 bps (100M) |
| Port-channel | 1,000,000,000 bps (assume 1G per member) |

`utilization_pct = bps / speed * 100`

**Thresholds — only report if exceeded:**
- \> 70% sustained → WARNING
- \> 90% sustained → CRITICAL

Do NOT report interfaces below these thresholds. A port at 14 Mbps on a 10G link is 0.14% — not a finding.

**If a threshold IS exceeded**, look up the port in Nautobot before reporting:

```
search_ip_addresses(query="HomeSwitch01")
```

Or use the nautobot-sot skill to identify what is connected to the port. Include the port description in the finding.

**Finding format:**
- Bad: "Te1/1/3 at 14 Mbps — top consumer"
- Good: "HomeSwitch01 Gi1/0/47 [HDHomeRun Tuner]: 847 Mbps IN / 112 Mbps OUT — 84.7% utilization on 1G port"

### Step 3: Interface Errors

```
execute_query(query="rate(interface_in_errors_total{device_name=\"HomeSwitch01\"}[5m])")
execute_query(query="rate(interface_in_errors_total{device_name=\"HomeSwitch02\"}[5m])")
```

**Thresholds:**
- \> 100 errors/s → WARNING
- \> 1000 errors/s or rising trend → CRITICAL

### Step 4: Firewall Block Rate

```
execute_query(query="rate(firewall_events_total{action=\"block\"}[15m])")
```

Compare to baseline. Only report if the rate is dramatically higher than normal (>10x typical).

Normal firewall blocks are expected — do NOT report them as findings.

### Step 5: pfSense Health

```
pfsense_get_system_info()
pfsense_get_gateway_status()
pfsense_get_interfaces()
```

Check CPU, memory, disk, and gateway RTT/loss.

**Thresholds:**
- CPU > 80% → WARNING
- Memory > 90% → WARNING
- Gateway loss > 0% → WARNING
- Gateway status ≠ "online" → CRITICAL

**Interface rules:**
- Only report interfaces that are EXPECTED to be up but are down. Check if the interface has an IP address and is actively used.
- Interfaces with no IP, no traffic, and generic names (OPT14, OPT15, etc.) are **unused placeholders — do NOT report them.**
- The LAN interface (igc1) may be intentionally unused if traffic routes through VLANs instead. Check if any VLAN interfaces are carrying traffic before flagging LAN as down.
- Only report an interface as CRITICAL if it was previously up and carrying traffic, or if it's the WAN interface.

### Step 6: Critical Syslog Events

```
query_loki_logs(query="{job=\"syslog\"} |~ \"CRITICAL|ERROR|CRASH|MALLOCFAIL|CPUHOG|Traceback\"", limit=20)
```

Scan for patterns indicating real problems:
- `%SYS-*-RELOAD` — unexpected reload
- `%LINEPROTO-5-UPDOWN` — interface flap
- `%SYS-2-MALLOCFAIL` — memory failure (CRITICAL)
- `%SYS-3-CPUHOG` — CPU hog (WARNING)
- `Traceback` — software bug (CRITICAL)

## WS-C3850-48P Combo Uplink Rule (IMPORTANT)

The WS-C3850-48P has combo uplink ports: Gi1/1/1–4 share physical slots with Te1/1/1–4.

When an SFP+ is inserted and Te1/1/x is active, the corresponding Gi1/1/x is **automatically disabled by IOS**. It will show as down with no traffic.

**Do NOT report Gi1/1/1–4 as errors or down if Te1/1/1–4 are active.** This is expected hardware behavior.

## Output Format

Produce a summary table:

```
Convergence NOC Watch — [timestamp]

┌──────────────────┬──────────┬─────────────────────────┐
│ Check            │ Status   │ Details                 │
├──────────────────┼──────────┼─────────────────────────┤
│ HomeSwitch01     │ HEALTHY  │ SNMP reporting, 0 errors│
│ HomeSwitch02     │ HEALTHY  │ SNMP reporting, 0 errors│
│ pfSense-FW01     │ HEALTHY  │ CPU 12%, GW online 3ms  │
│ Interface Util   │ HEALTHY  │ All ports < 70%         │
│ Firewall Blocks  │ HEALTHY  │ 2.3/s (normal baseline) │
│ Syslog           │ HEALTHY  │ No critical events      │
└──────────────────┴──────────┴─────────────────────────┘

Overall: HEALTHY — no issues detected
```

Severity order: CRITICAL > WARNING > HEALTHY. Overall = worst individual status.

If everything is healthy, produce the table and a single INFO-level summary. Do NOT generate WARNING/CRITICAL findings for normal operation.

## Integration with Other Skills

| Skill | When to Use |
|-------|------------|
| convergence-security-monitor | Escalate if syslog shows security events |
| convergence-interface-reconciler | Escalate if interface inventory drift detected |
| synology-nas-monitor | Delegate NAS-specific health checks |
| pyats-health-check | Deep device health (CPU processes, memory consumers, NTP) |
| pfsense-firewall-ops | Deep pfSense analysis (rules, aliases, state table) |
