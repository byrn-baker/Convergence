---
name: convergence-interface-reconciler
description: "Convergence interface reconciliation — syncs Nautobot source-of-truth with switch interface state. Enriches port descriptions with VLAN/hostname/IP from MAC+DHCP correlation, syncs admin state (Nautobot authoritative), and diffs SNMP inventory against Nautobot. Use when reconciling switch interfaces or auditing Nautobot accuracy."
user-invocable: true
metadata:
  { "openclaw": { "requires": { "env": ["PYATS_TESTBED_PATH", "PROMETHEUS_URL"] } } }
---

# Convergence Interface Reconciler

Replaces the Interface Reconciler agent. Ensures Nautobot is an accurate source of truth for switch interface inventory, enriches port descriptions, and syncs admin state.

## Switches Managed

| Device | IP | Model |
|--------|----|-------|
| HomeSwitch01 | 192.168.3.2 | Cisco WS-C3850-48P |
| HomeSwitch02 | 192.168.3.3 | Cisco WS-C3850-48P |

## MCP Servers / Skills Used

| Server/Skill | Tools Used |
|-------------|-----------|
| pyats-network | `pyats_run_show_command` for `show mac address-table dynamic`, `show interfaces status` |
| pyats-config-mgmt | `pyats_configure_device` for interface description + shutdown/no shutdown |
| nautobot-mcp | `search_ip_addresses`, `get_ip_addresses` for interface lookups |
| pfsense-mcp | `pfsense_get_dhcp_leases`, `pfsense_get_arp_table` for MAC→hostname resolution |
| prometheus-mcp | `execute_query` for SNMP interface inventory |

## Reconciliation Procedure

Run all three phases for each switch.

### Phase 1: Description Enrichment

**Goal:** Every active access port gets a description showing what's plugged in.

**Format (exactly):**
```
VLAN10 | mylaptop | 192.168.3.42
VLAN10 | (unidentified)
VLAN1 | hdhr-tuner | 192.168.100.223
```

**Workflow:**

1. Get the MAC address table from the switch:

```
pyats_run_show_command(device_name="HomeSwitch01", command="show mac address-table dynamic")
```

This returns `{vlan, mac, port}` entries.

2. Get DHCP leases and ARP table from pfSense (once total, not per-switch):

```
pfsense_get_dhcp_leases()
pfsense_get_arp_table()
```

3. Build a lookup: `mac → {hostname, ip}` from DHCP (preferred) or ARP (fallback).

4. For each active access port (GigabitEthernet1/0/x):
   - Find its MAC(s) in the MAC table
   - Look up the MAC in the DHCP/ARP data
   - Get the VLAN from the MAC table entry
   - Build description: `VLAN{vid} | {hostname} | {ip}`
   - If multiple MACs on port (hub/AP): use the primary one
   - If no DHCP/ARP match: `VLAN{vid} | (unidentified)`
   - If no MAC at all (port up but idle): **skip** — do not overwrite existing description

5. Write the description to the switch AND Nautobot, but **only if the current description differs** from the new one (avoid pointless write cycles).

Write to switch:
```
pyats_configure_device(device_name="HomeSwitch01", configuration="interface GigabitEthernet1/0/1\n description VLAN10 | mylaptop | 192.168.3.42")
```

Update Nautobot via nautobot-mcp or REST API.

**Skip rules for description enrichment:**
- **Uplink/trunk ports** (Gi1/1/x, Te1/1/x, Port-channel): Do NOT overwrite. These are switch-to-switch or router links.
- **Combo uplinks**: Do NOT touch Gi1/1/1–4 if Te1/1/1–4 are active. The Gi ports are automatically disabled by IOS when SFP+ is inserted — this is normal hardware behavior.

### Phase 2: Admin State Sync (Nautobot → Switch)

**Nautobot is the AUTHORITATIVE source for admin state.**

1. Get Nautobot interfaces with their `enabled` field (via nautobot-mcp or GraphQL).

2. Get switch interface status:

```
pyats_run_show_command(device_name="HomeSwitch01", command="show interfaces status")
```

Status values: `connected`, `notconnect`, `disabled` (= admin-down), `err-disabled`.
`admin_up = false` only when status is `disabled`.

3. Compare: if Nautobot `enabled` ≠ switch `admin_up`:
   - Nautobot enabled=true, switch admin-down → push `no shutdown`
   - Nautobot enabled=false, switch admin-up → push `shutdown`

```
pyats_configure_device(device_name="HomeSwitch01", configuration="interface GigabitEthernet1/0/5\n no shutdown")
```

This means: shutting a port in Nautobot (enabled=false) will cause the next reconciler cycle to push `shutdown` to the switch. Re-enabling in Nautobot pushes `no shutdown`.

### Phase 3: Inventory Reconciliation

1. Get SNMP interfaces (physically real, from VictoriaMetrics):

```
execute_query(query="interface_in_octets_bytes_total{device_name=\"HomeSwitch01\"}")
```

Extract unique `interface_name` labels.

2. Get Nautobot interfaces for the same device.

3. Diff:
   - **In SNMP but NOT in Nautobot** → create in Nautobot
     - Skip: `Null0`, `StackPort1`, `StackPort2` — these are virtual/internal
   - **In Nautobot but NOT in SNMP** → report WARNING (may be stale data)

4. Report INFO if everything is aligned.

## What NOT to Do

- Do NOT skip admin state sync — it runs every cycle
- Do NOT skip description writes for ports with active MACs
- Do NOT overwrite trunk/uplink port descriptions with device enrichment
- Do NOT report CRITICAL for a port that is admin-down in both Nautobot and the switch — that's consistent
- Do NOT touch Gi1/1/1–4 if Te1/1/1–4 are active (combo uplinks)
- Do NOT create Nautobot entries for Null0, StackPort1, StackPort2

DHCP enrichment is best-effort. If pfSense is unavailable, skip DHCP/ARP steps and note it in the report.

## Output Format

```
Interface Reconciler — [timestamp]

HomeSwitch01:
  Descriptions updated: 12 (of 48 access ports)
  Admin state synced: 0 mismatches
  Inventory: 52 SNMP / 52 Nautobot — aligned

HomeSwitch02:
  Descriptions updated: 8 (of 48 access ports)
  Admin state synced: 1 (Gi1/0/23 → shutdown per Nautobot)
  Inventory: 52 SNMP / 51 Nautobot — 1 missing (Gi1/0/48 created)

Overall: 20 descriptions enriched, 1 admin state sync, 1 interface created
```

## Integration with Other Skills

| Skill | When to Use |
|-------|------------|
| convergence-noc-watch | Cross-reference if interface errors correlate with reconciliation changes |
| nautobot-sot | IPAM lookups for IP address validation |
| pyats-topology | Full device topology discovery |
| pfsense-firewall-ops | DHCP/ARP data for device identification |
