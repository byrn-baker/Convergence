---
name: convergence-security-monitor
description: "Convergence security monitoring — firewall block rate analysis, threat intel cross-reference, NetFlow threat hunting (C2 beaconing, data exfiltration, lateral movement), internal host validation via Nautobot, and automated block submission. Use when running a security analysis cycle or investigating suspicious network activity."
user-invocable: true
metadata:
  { "openclaw": { "requires": { "env": ["PROMETHEUS_URL", "GRAFANA_URL", "GRAFANA_SERVICE_ACCOUNT_TOKEN"] } } }
---

# Convergence Security Monitor

Replaces the Security Expert and Security Engineer agents. This is a threat hunting and security posture monitoring procedure for the Convergence home network.

## Infrastructure

| Asset | IP/Range | Role |
|-------|----------|------|
| pfSense-FW01 | 192.168.100.1 | Netgate firewall (WAN + LAN + DMZ) |
| HomeSwitch01 | 192.168.3.2 | Cisco WS-C3850-48P |
| HomeSwitch02 | 192.168.3.3 | Cisco WS-C3850-48P |
| SynologyNAS01 | 192.168.100.22 | NAS — backups, media, Docker, surveillance |
| SynologyNAS02 | 192.168.100.23 | NAS — backups, media, Docker, surveillance |
| LAN | 192.168.1.0/24 | Client devices |
| Management | 192.168.3.0/24 | Switch management |
| Servers | 192.168.100.0/24 | NAS, infrastructure |
| IoT | 192.168.102.0/24 | IoT devices |

## MCP Servers Used

| Server | Tools Used |
|--------|-----------|
| prometheus-mcp | `execute_query` for firewall block rate PromQL |
| grafana-mcp | `query_loki_logs` for filterlog + NetFlow, `query_prometheus` |
| convergence-mcp | `get_threat_intel_report`, `get_blocked_ips`, `get_outbound_suspicious`, `submit_block_action`, `get_pending_approvals`, `investigate_host` |
| nautobot-mcp | `search_ip_addresses`, `get_ip_addresses` for device identification |
| pfsense-mcp | `pfsense_get_firewall_rules`, `pfsense_get_states_summary`, `pfsense_get_arp_table`, `pfsense_get_dhcp_leases` |

## Security Analysis Procedure

### Step 1: Firewall Block Rate

```
execute_query(query="rate(firewall_events_total{action=\"block\"}[15m])")
```

Compare to baseline. A spike >10x normal warrants investigation.

Also get top blocked source IPs:

```
execute_query(query="topk(10, sum by (src_ip) (rate(firewall_events_total{action=\"block\"}[15m])))")
```

### Step 2: Threat Intelligence Cross-Reference

```
get_threat_intel_report()
```

Review the threat-intel service report:
- Top blocked IPs with composite threat scores (0–100)
- AbuseIPDB confidence scores
- GreyNoise classification (benign scanner vs malicious)
- OTX pulse matches
- Outbound suspicious destinations

### Step 3: Firewall Log Analysis

```
query_loki_logs(query="{job=\"syslog\"} |= \"filterlog\"", limit=100)
```

Look for:
- Repeated blocks from the same source → scanner or brute force
- Blocks on sensitive ports (22, 3389, 445, 1433, 3306) → targeted attack
- Pass rules to unexpected destinations → possible compromise

### Step 4: NetFlow Threat Hunting

```
query_loki_logs(query="{job=\"netflow\"}", limit=100)
```

Each NetFlow record is OTLP JSON. Extract fields from the attributes array:

```
"key":"source.address","value":{"stringValue":"1.2.3.4"}
"key":"destination.address","value":{"stringValue":"5.6.7.8"}
"key":"destination.port","value":{"intValue":"443"}
"key":"network.transport","value":{"stringValue":"TCP"}
"key":"flow.io.bytes","value":{"intValue":"102400"}
"key":"flow.io.packets","value":{"intValue":"50"}
```

**Hunt for:**

| Pattern | Indicators |
|---------|-----------|
| C2 beaconing | Regular small flows (consistent bytes) to same external IP at fixed intervals |
| Data exfiltration | Large outbound flows (>10MB) to unknown external IPs |
| Port scanning | One source IP hitting many destination ports |
| Brute force | Many flows to SSH(22)/RDP(3389)/SMB(445) from external IPs |
| Lateral movement | Unexpected internal-to-internal flows between VLANs |

### Step 5: Pending Automation Actions

```
get_pending_approvals()
```

Review any pending block actions in the automation pipeline.

## MANDATORY: Internal Host Validation

**Before flagging ANY internal IP (192.168.x.x, 10.x.x.x, 172.16–31.x.x) as suspicious, you MUST validate it against Nautobot first.**

```
investigate_host(ip="192.168.100.23")
```

Or use nautobot-mcp:

```
search_ip_addresses(query="192.168.100.23")
```

### Known Device Roles — Do NOT Flag

| Device Type | Expected Behavior |
|-------------|------------------|
| NAS (Synology) | Talks to many internal hosts across VLANs — backups, media streaming, Docker containers, surveillance cameras. This is NORMAL. |
| IoT/media devices | Apple TV, Chromecast, smart speakers use mDNS (5353), AirPlay (7000, 7100). NORMAL. |
| Switches | Management traffic across VLANs. NORMAL. |
| pfSense | Appears in flows to/from all subnets — it's the gateway. NORMAL. |

### When to Flag an Internal Host

Only flag as WARNING/CRITICAL if:
1. The IP is NOT in Nautobot (unknown device on the network)
2. OR it is communicating on unexpected ports for its role
3. OR it is making outbound connections to known-bad external IPs

If deeper investigation is needed after Nautobot lookup, use pyATS skills to SSH into switches and trace the MAC through the switching fabric.

## Blocking Protocol

### DO NOT block individual /32 IPs

Blocking single IPs fills the alias table with thousands of entries and accomplishes nothing — attackers rotate IPs constantly. Instead:

1. When you see multiple blocked IPs, group them by ASN (from threat intel report)
2. If 3+ IPs from the same ASN are attacking, that ASN should be added to pfBlockerNG, NOT blocked individually
3. Report the ASN pattern as a finding with the recommendation to add it to pfBlockerNG
4. **Do NOT call submit_block_action at all** unless there is CONFIRMED COMPROMISE — meaning traffic that PASSED the firewall and an internal host is communicating with a known C2 server

### When to use submit_block_action (EXTREMELY RARE)

- An internal host is ACTIVELY communicating outbound to a confirmed C2/malware IP
- You have confirmed via investigate_host that the internal device is compromised
- This is an emergency containment action, not routine blocking
- Max 1 submission per cycle

### When to recommend pfBlockerNG instead (COMMON)

- Multiple IPs from the same ASN scanning your network → recommend blocking the ASN in pfBlockerNG
- Known bad ASNs (AS207812, AS50360, AS211736, etc.) → pfBlockerNG GeoIP or ASN list
- Entire country ranges doing nothing but scanning → pfBlockerNG GeoIP block

### Hard Rules

- **NEVER call submit_block_action for IPs that were BLOCKED by the firewall** — the firewall already handled it, blocking them again is pointless
- **NEVER block internal IPs** (RFC1918)
- **submit_block_action is for CONFIRMED COMPROMISE ONLY** — not for scanners, not for blocked traffic, not for high scores

## Noise Reduction Rules

- **Blocked inbound traffic is NORMAL firewall operation.** The firewall's job is to block. Do NOT report blocked scans as findings unless the volume is >10x baseline or the traffic PASSED the firewall.
- Do NOT report that "RDP was targeted" or "Telnet was scanned" without specifics. If you mention a port, you MUST include: source IP, destination IP, action (blocked/passed), count of attempts, country/ASN of source.
- Do NOT report unused/unconfigured interfaces or VLANs — those are intentional.
- Do NOT report INFO-level findings — only WARNING and CRITICAL.
- Do NOT recommend "investigate" if you can investigate yourself with available tools.
- If all threats were blocked and nothing anomalous passed, produce a single brief "all clear" summary and stop.
- Do NOT flag Synology NAS devices for talking to multiple VLANs — that's their job.

## What Constitutes a Real Finding

**CRITICAL** — requires immediate action:
- Traffic that PASSED the firewall to/from a known-bad IP (score ≥ 80)
- Outbound C2 beaconing or data exfiltration confirmed in NetFlow
- Unknown device on the network (not in Nautobot, not in DHCP)

**WARNING** — needs attention but not urgent:
- Block rate spike >10x baseline (even if all blocked — indicates active campaign)
- New attack pattern not seen before (new ASN, new port combination)
- Internal host communicating on unexpected ports for its role

**NOT a finding:**
- Blocked inbound scans at normal volume (this is every day, all day)
- "Port X was targeted" without saying by whom, whether it was blocked, and how many times
- Unused interfaces or VLANs
- Known scanners (GreyNoise benign) being blocked

## Output Format

For each finding, provide:
1. **What** — specific IP, port, pattern
2. **Evidence** — metric values, log entries, NetFlow records
3. **Risk** — what could happen if unaddressed
4. **Action taken** — block submitted, or recommendation if manual action needed

If no threats found:

```
Security Monitor — [timestamp]
Status: CLEAR
Block rate: 2.3/s (normal)
Top blocked: 45.33.32.x (GreyNoise: benign scanner)
Threat intel: No high-risk IPs (all scores < 60)
NetFlow: No C2/exfil/lateral movement patterns
Pending blocks: 0
```

## Integration with Other Skills

| Skill | When to Use |
|-------|------------|
| convergence-noc-watch | Cross-reference if security event correlates with device health issue |
| pfsense-firewall-ops | Deep firewall rule audit, alias management, state table analysis |
| pyats-security | CIS benchmark audit, ACL analysis, CoPP checks on switches |
| nautobot-sot | Device identification and IPAM lookups |
| grafana-observability | Dashboard correlation, alert rule management |
