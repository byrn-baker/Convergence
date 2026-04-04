from ..config import settings
from ..models import AgentRole, Finding, Severity
from ..tools import victoriametrics as vm_tools
from ..tools import nautobot
from ..tools import pfsense as pfsense_tools
from ..tools import switch_ssh
from ..llm_client import run_agentic_loop, run_agentic_question

_SWITCHES = [
    {"name": "HomeSwitch01", "ip": "192.168.3.2"},
    {"name": "HomeSwitch02", "ip": "192.168.3.3"},
]

_TOOLS = [
    {
        "name": "get_snmp_interfaces",
        "description": (
            "Get all interfaces currently reporting SNMP metrics for a given switch. "
            "These represent real, active interfaces as seen by the monitoring stack."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Switch hostname, e.g. HomeSwitch01",
                },
            },
            "required": ["device_name"],
        },
    },
    {
        "name": "get_nautobot_interfaces",
        "description": (
            "Get all interfaces recorded in Nautobot for a given switch. "
            "Returns id, name, enabled (admin state), description, mac_address, "
            "status, and untagged_vlan (access VLAN if set)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Switch hostname as stored in Nautobot",
                },
            },
            "required": ["device_name"],
        },
    },
    {
        "name": "get_switch_mac_table",
        "description": (
            "SSH to a switch and run 'show mac address-table dynamic'. "
            "Returns list of {vlan, mac, port} entries showing which MAC addresses "
            "are learned on each port and which VLAN they are in. "
            "MAC is in colon-notation (aa:bb:cc:dd:ee:ff). "
            "Port is the full interface name (GigabitEthernet1/0/1)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "Switch hostname"},
                "ip": {"type": "string", "description": "Switch management IP"},
            },
            "required": ["device_name", "ip"],
        },
    },
    {
        "name": "get_switch_interface_status",
        "description": (
            "SSH to a switch and run 'show interfaces status'. "
            "Returns dict of {interface_name: {vlan, status, connected, admin_up}}. "
            "status values: connected, notconnect, disabled (=admin-down), err-disabled. "
            "admin_up is False only when status is 'disabled'. "
            "Use this to detect admin state mismatches with Nautobot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "Switch hostname"},
                "ip": {"type": "string", "description": "Switch management IP"},
            },
            "required": ["device_name", "ip"],
        },
    },
    {
        "name": "get_dhcp_leases",
        "description": (
            "Get all active DHCP leases from pfSense firewall. "
            "Returns IP, MAC, hostname, and interface for each lease. "
            "Use this to identify what device is at a given MAC address."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_arp_table",
        "description": (
            "Get the ARP table from pfSense. Returns IP → MAC mappings with interface. "
            "Fallback for devices with static IPs or expired DHCP leases."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "push_interface_description",
        "description": (
            "Write an interface description to BOTH the switch (via SSH) AND Nautobot. "
            "Description format: 'VLAN{vid} | {hostname} | {ip}' "
            "e.g. 'VLAN10 | mylaptop | 192.168.3.42'. "
            "If no DHCP match found, use 'VLAN{vid} | (unidentified)'. "
            "If VLAN is unknown, omit the VLAN prefix. "
            "This writes to the switch running-config and saves to NVRAM. "
            "Also PATCHes the Nautobot interface description field."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "Switch hostname"},
                "ip": {"type": "string", "description": "Switch management IP"},
                "interface_name": {
                    "type": "string",
                    "description": "Full interface name, e.g. GigabitEthernet1/0/1",
                },
                "nautobot_interface_id": {
                    "type": "string",
                    "description": "Nautobot UUID of the interface",
                },
                "description": {
                    "type": "string",
                    "description": "Description to write (format: VLAN10 | hostname | ip)",
                },
            },
            "required": ["device_name", "ip", "interface_name", "nautobot_interface_id", "description"],
        },
    },
    {
        "name": "sync_admin_state",
        "description": (
            "Sync the admin state of an interface from Nautobot → switch. "
            "Nautobot is the authoritative source for admin state. "
            "If Nautobot enabled=true and switch is admin-down: push 'no shutdown'. "
            "If Nautobot enabled=false and switch is admin-up: push 'shutdown'. "
            "Also updates Nautobot enabled field if the switch state was changed. "
            "Always call this when admin_up on the switch does NOT match Nautobot enabled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "Switch hostname"},
                "ip": {"type": "string", "description": "Switch management IP"},
                "interface_name": {
                    "type": "string",
                    "description": "Full interface name, e.g. GigabitEthernet1/0/1",
                },
                "nautobot_interface_id": {
                    "type": "string",
                    "description": "Nautobot UUID of the interface",
                },
                "nautobot_enabled": {
                    "type": "boolean",
                    "description": "The enabled value from Nautobot (authoritative)",
                },
            },
            "required": ["device_name", "ip", "interface_name", "nautobot_interface_id", "nautobot_enabled"],
        },
    },
    {
        "name": "update_nautobot_interface",
        "description": "Update fields on an existing Nautobot interface by ID (PATCH).",
        "input_schema": {
            "type": "object",
            "properties": {
                "interface_id": {
                    "type": "string",
                    "description": "Nautobot interface UUID",
                },
                "fields": {
                    "type": "object",
                    "description": "Key/value pairs to update (e.g. description, enabled)",
                },
            },
            "required": ["interface_id", "fields"],
        },
    },
    {
        "name": "create_nautobot_interface",
        "description": "Create a missing interface in Nautobot for a given device.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Switch hostname in Nautobot",
                },
                "interface_name": {
                    "type": "string",
                    "description": "Interface name, e.g. GigabitEthernet1/0/1",
                },
                "description": {
                    "type": "string",
                    "description": "Optional description",
                    "default": "",
                },
            },
            "required": ["device_name", "interface_name"],
        },
    },
    {
        "name": "report_finding",
        "description": "Report a reconciliation finding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"]},
                "device": {"type": "string", "description": "Device name or 'all'"},
                "summary": {"type": "string", "description": "One-line summary"},
                "details": {"type": "string", "description": "Detailed explanation"},
            },
            "required": ["severity", "device", "summary", "details"],
        },
    },
]

_SYSTEM_PROMPT = """You are an Interface Reconciliation Agent. Your job is to:
1. Ensure Nautobot is an accurate source of truth for switch interface inventory
2. Enrich every active port with a description showing VLAN, hostname, and IP
3. Write those descriptions to BOTH the switch (via SSH) AND Nautobot
4. Keep Nautobot admin state (enabled field) deployed to the switch

Switches you manage:
- HomeSwitch01 (192.168.3.2) — Cisco WS-C3850-48P
- HomeSwitch02 (192.168.3.3) — Cisco WS-C3850-48P

---

## Description Enrichment (run for every switch, every cycle)

For each switch:
1. Call get_switch_mac_table — get {vlan, mac, port} for all learned MACs
2. Call get_dhcp_leases and get_arp_table (once total, not per-switch)
3. Build a lookup: mac → {hostname, ip} from DHCP (preferred) or ARP
4. For each active access port (GigabitEthernet1/0/x):
   a. Find its MAC(s) in the MAC table
   b. Look up the MAC in the DHCP/ARP data
   c. Get the VLAN from the MAC table entry
   d. Build description: "VLAN{vid} | {hostname} | {ip}"
      - If multiple MACs on port (hub/AP): list the primary one
      - If no DHCP/ARP match: "VLAN{vid} | (unidentified)"
      - If no MAC at all (port is up but idle): skip — do not overwrite existing description
   e. Call push_interface_description to write to switch + Nautobot
      ONLY if the current Nautobot description differs from the new one
      (avoid pointless write cycles)

Description format (exactly):
  "VLAN10 | mylaptop | 192.168.3.42"
  "VLAN10 | (unidentified)"
  "VLAN1 | hdhr-tuner | 192.168.100.223"

Uplink/trunk ports (Gi1/1/x, Te1/1/x, Port-channel):
  Do NOT overwrite with device enrichment — leave existing descriptions alone.
  These are switch-to-switch or router links, not end-device ports.

---

## Admin State Sync (Nautobot → Switch)

Nautobot is the AUTHORITATIVE source for admin state. If Nautobot says a port should be
shut, it should be shut on the switch. If Nautobot says it should be up, it should be up.

For each switch:
1. Call get_nautobot_interfaces — get enabled (bool) for each interface
2. Call get_switch_interface_status — get admin_up (bool) for each interface
3. Compare: if Nautobot enabled != switch admin_up:
   → Call sync_admin_state to push the Nautobot value to the switch
   → This writes "shutdown" or "no shutdown" to the switch and saves the config

This means: if you shut a port in Nautobot (set enabled=false), the next reconciler cycle
will push "shutdown" to the switch automatically. If you re-enable it in Nautobot, the next
cycle pushes "no shutdown".

---

## Inventory Reconciliation

For each switch:
1. Get SNMP interfaces (from VictoriaMetrics) — these are physically real
2. Get Nautobot interfaces
3. Diff:
   - In SNMP but NOT in Nautobot → create in Nautobot (skip: Null0, StackPort1, StackPort2)
   - In Nautobot but NOT in SNMP → report WARNING (may be stale)
4. Report INFO if everything is aligned

---

## What NOT to do
- Do NOT skip the admin state sync — it is required every cycle
- Do NOT skip description writes for ports with active MACs
- Do NOT overwrite trunk/uplink port descriptions with device enrichment
- Do NOT report CRITICAL for a port that is admin-down in both Nautobot and the switch
- Do NOT touch Gi1/1/1-4 if Te1/1/1-4 are active (combo uplinks — normal behavior)

DHCP enrichment is best-effort — if pfSense is unavailable, skip DHCP/ARP steps and note it."""


async def run_reconciliation() -> list:
    """
    Interface Reconciler: enriches port descriptions, syncs admin state, diffs Nautobot vs SNMP.
    """
    return await run_agentic_loop(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        user_message=(
            "Run a full interface reconciliation on HomeSwitch01 and HomeSwitch02. "
            "For each switch: "
            "(1) Get the MAC address table and DHCP/ARP data, then write enriched descriptions "
            "(VLAN | hostname | IP) to every active access port on both the switch and Nautobot. "
            "(2) Compare Nautobot enabled state with the switch admin state and sync any mismatches "
            "by pushing shutdown/no shutdown to the switch. "
            "(3) Diff SNMP interfaces against Nautobot inventory and fix gaps. "
            "Report all findings."
        ),
        handle_tool_call=_handle_tool_call,
        caller="interface_reconciler",
        findings=[],
        max_tokens=8192,
    )


async def answer_question(question: str) -> str:
    """Run an agentic loop to answer a Discord user's question about interface reconciliation."""
    return await run_agentic_question(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        question=question,
        handle_tool_call=_handle_tool_call,
        caller="interface_reconciler",
    )


async def _get_snmp_interfaces(device_name: str) -> list[str]:
    """Query VictoriaMetrics for all interfaces reporting metrics for a device."""
    query = f'interface_in_octets_bytes_total{{device_name="{device_name}"}}'
    result = await vm_tools.query_instant(query)
    if "error" in result:
        return [f"error: {result['error']}"]
    data = result.get("data", {}).get("result", [])
    names = set()
    for item in data:
        labels = item.get("metric", {})
        iface = labels.get("interface_name", "")
        if iface:
            names.add(iface)
    return sorted(names)


async def _handle_tool_call(name: str, inputs: dict, findings: list):
    if name == "get_snmp_interfaces":
        return await _get_snmp_interfaces(inputs["device_name"])

    elif name == "get_nautobot_interfaces":
        return await nautobot.get_interfaces(inputs["device_name"])

    elif name == "get_switch_mac_table":
        return await switch_ssh.get_mac_address_table(inputs["ip"])

    elif name == "get_switch_interface_status":
        return await switch_ssh.get_interface_status(inputs["ip"])

    elif name == "get_dhcp_leases":
        return await pfsense_tools.get_dhcp_leases()

    elif name == "get_arp_table":
        return await pfsense_tools.get_arp_table()

    elif name == "push_interface_description":
        device_name = inputs["device_name"]
        ip = inputs["ip"]
        iface = inputs["interface_name"]
        nb_id = inputs["nautobot_interface_id"]
        desc = inputs["description"]

        # Push to switch via SSH
        ssh_result = await switch_ssh.push_interface_description(ip, iface, desc)
        # Update Nautobot
        nb_result = await nautobot.update_interface(nb_id, description=desc)

        return {
            "switch": ssh_result,
            "nautobot": "ok" if "error" not in nb_result else nb_result.get("error"),
        }

    elif name == "sync_admin_state":
        device_name = inputs["device_name"]
        ip = inputs["ip"]
        iface = inputs["interface_name"]
        nb_id = inputs["nautobot_interface_id"]
        nb_enabled = inputs["nautobot_enabled"]

        # Push Nautobot value to switch
        ssh_result = await switch_ssh.push_interface_admin_state(ip, iface, nb_enabled)
        return {
            "action": "no shutdown" if nb_enabled else "shutdown",
            "interface": iface,
            "switch": ssh_result,
        }

    elif name == "update_nautobot_interface":
        return await nautobot.update_interface(inputs["interface_id"], **inputs.get("fields", {}))

    elif name == "create_nautobot_interface":
        device_name = inputs["device_name"]
        device = await nautobot.get_device(device_name)
        if not device or "error" in device:
            return {"error": f"Could not find device {device_name} in Nautobot: {device}"}
        device_id = device.get("id")
        return await nautobot.create_interface(
            device_id=device_id,
            name=inputs["interface_name"],
            description=inputs.get("description", "Added by Interface Reconciler"),
        )

    elif name == "report_finding":
        finding = Finding(
            role=AgentRole.INTERFACE_RECONCILER,
            severity=Severity[inputs["severity"]],
            device=inputs["device"],
            summary=inputs["summary"],
            details=inputs["details"],
        )
        findings.append(finding)
        return {"status": "recorded", "finding_id": len(findings)}

    return {"error": f"Unknown tool: {name}"}
