# Phase 10: Open Issues — Next Session

**Date:** 2026-04-06
**Priority:** High — reconciler agent non-functional, Nautobot integration incomplete

---

## Issue 1: Interface Reconciler Timeout

The `reconciler` agent consistently times out during execution. The skill requires multiple sequential operations per switch (MAC table → DHCP/ARP lookup → description enrichment → admin state sync → inventory diff), each involving tool calls through MCP servers. With the 480B cloud model, each LLM round-trip takes 10-30 seconds. A full reconciliation of 2 switches with 48+ ports each requires dozens of tool calls — easily exceeding the 600s timeout.

### Symptoms

```
The interface reconciliation task for both HomeSwitch01 and HomeSwitch02 has been
initiated but timed out during execution.

No critical errors were reported, but the following summary could not be fully generated
due to the timeout:
- Port descriptions that would have been enriched
- Admin state synchronization results
- Inventory diff outcomes
```

### Root Cause

The reconciler skill is the most tool-intensive of the three skills. For each switch it needs to:
1. `pyats_run_show_command` — show mac address-table dynamic (1 call)
2. `pfsense_get_dhcp_leases` — DHCP leases (1 call)
3. `pfsense_get_arp_table` — ARP table (1 call)
4. For each active port with a MAC: look up hostname, build description, write to switch + Nautobot
5. `pyats_run_show_command` — show interfaces status (1 call)
6. Compare admin state with Nautobot, push changes
7. `execute_query` — SNMP interfaces from VictoriaMetrics (1 call)
8. Compare with Nautobot interfaces, create missing

Steps 1-3 are fast. Step 4 is the killer — it's N tool calls where N is the number of active ports. With 48 ports per switch and 2 switches, that's potentially 96+ tool calls just for description enrichment, each requiring an LLM round-trip through Ollama Cloud.

### Possible Solutions

1. **Break the skill into sub-tasks**: Instead of one monolithic reconciliation, split into:
   - `convergence-reconciler-describe` — description enrichment only
   - `convergence-reconciler-admin-sync` — admin state sync only
   - `convergence-reconciler-inventory` — inventory diff only
   - Run each as a separate agent call with its own timeout

2. **Batch operations in the skill**: Rewrite the skill to instruct the agent to collect ALL data first (MAC table, DHCP, ARP, Nautobot interfaces) in bulk, then process locally instead of making per-port tool calls

3. **Increase timeout**: Bump to 1200-1800s. Simple but means the reconciler agent is occupied for 20-30 minutes per cycle

4. **Reduce frequency**: Run reconciler hourly instead of every 10 minutes. Port descriptions don't change that fast

5. **Move reconciliation to a deterministic script**: This task is highly procedural — it might not need an LLM at all. A Python script that runs `show mac address-table`, correlates with DHCP/ARP, and writes descriptions would be faster and more reliable than an AI agent doing it through tool calls

### Recommendation

Option 5 is probably the right answer long-term. The reconciler doesn't need AI judgment — it's a deterministic workflow: get MAC table, look up hostname, write description. The LLM adds latency and token cost without adding value. But if we want to keep it as a NetClaw skill for consistency, option 2 (batch collection) combined with option 4 (hourly frequency) is the pragmatic fix.

---

## Issue 2: Nautobot Integration Depth

Currently Nautobot is used for:
- Port description lookups (noc-watch skill, before reporting bandwidth findings)
- Internal host validation (security-monitor skill, before flagging RFC1918 IPs)
- Interface inventory diff (reconciler skill)
- Device identification via `investigate_host` in convergence-mcp

### What's Missing

**Nautobot as the authoritative network model:**
- The skills hardcode device IPs, VLAN layouts, and subnet ranges in the SKILL.md files
- These should come from Nautobot dynamically — query devices, prefixes, VLANs at the start of each cycle
- If a new device is added to Nautobot, the skills should automatically discover and monitor it

**Nautobot-driven alert context:**
- When the security monitor finds suspicious traffic, it should pull the full device context from Nautobot: role, site, tenant, connected interfaces, IP assignments
- The noc-watch skill should know which interfaces are expected to be up/down based on Nautobot's `enabled` field, not hardcoded assumptions about "always-down" interfaces

**Nautobot change tracking:**
- When the reconciler writes descriptions or syncs admin state, those changes should be tracked in Nautobot's changelog
- The GAIT audit trail records AI decisions, but Nautobot should record the infrastructure changes

**Nautobot as the skill configuration source:**
- Instead of hardcoding `HomeSwitch01 (192.168.3.2)` in the skill, query Nautobot for all devices with role=switch
- Instead of hardcoding VLAN ranges, query Nautobot for all prefixes
- This makes the skills portable — deploy on a different network, point at a different Nautobot, same skills work

### Integration Plan (Next Session)

1. **Create a `nautobot-context` tool or startup step** that queries Nautobot for:
   - All active devices (name, IP, role, model)
   - All prefixes/VLANs
   - All interfaces with expected state (enabled/disabled)
   - Feed this as context to each skill run

2. **Update skills to reference Nautobot data** instead of hardcoded values:
   - noc-watch: "Check all devices returned by Nautobot" instead of "Check HomeSwitch01, HomeSwitch02"
   - security-monitor: "Internal subnets are [from Nautobot prefixes]" instead of hardcoded 192.168.x.x ranges
   - reconciler: "Switches to reconcile are [from Nautobot devices with role=switch]"

3. **Add Nautobot webhook or polling** to detect inventory changes:
   - New device added → automatically included in next poll cycle
   - Interface disabled in Nautobot → reconciler pushes shutdown to switch
   - This already partially works but relies on the reconciler running, which is currently timing out

4. **Evaluate nautobot-mcp capabilities** — the current MCP server (`aiopnet/mcp-nautobot`) is read-only with IPAM focus. We may need:
   - DCIM device queries (not just IPAM)
   - Interface state queries with enabled/disabled
   - Write operations for description updates (currently done via REST in convergence-mcp)

---

## Issue 3: Scheduler Poll Overlap

The scheduler runs every 10 minutes. A full poll cycle with 3 concurrent skills takes 5-8 minutes (noc + security) to 10+ minutes (if reconciler doesn't timeout). If a cycle takes longer than 10 minutes, the next cycle starts while the previous one is still running.

APScheduler's `max_instances=1` would prevent overlap, but we're using `asyncio.create_task` for the initial run and interval jobs. Need to add a guard:

```python
_poll_running = False

async def _run_poll_cycle():
    global _poll_running
    if _poll_running:
        logger.info("Poll cycle already running — skipping")
        return
    _poll_running = True
    try:
        ...
    finally:
        _poll_running = False
```

Or increase the poll interval to 15-20 minutes to give the cloud model enough headroom.

---

## Summary for Next Session

| Priority | Issue | Quick Fix | Proper Fix |
|----------|-------|-----------|------------|
| High | Reconciler timeout | Increase timeout + reduce frequency | Deterministic script or batched skill |
| High | Nautobot hardcoded values | Works for now | Dynamic Nautobot context injection |
| Medium | Poll overlap | Add running guard | Increase interval or event-driven |
| Low | Nautobot write tracking | Works via REST | Nautobot changelog integration |
