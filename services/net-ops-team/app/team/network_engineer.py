from ..config import settings
from ..models import AgentRole, Finding, Severity
from ..tools import loki as loki_tools
from ..tools import victoriametrics as vm_tools
from ..tools import nautobot
from ..llm_client import run_agentic_loop, run_agentic_question

_TOOLS = [
    {
        "name": "query_metrics",
        "description": "Query VictoriaMetrics for a specific metric. Returns current values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "PromQL query string"},
                "time_range": {
                    "type": "string",
                    "description": "Time range like '5m', '1h'",
                    "default": "5m",
                },
            },
            "required": ["metric"],
        },
    },
    {
        "name": "query_logs",
        "description": "Query Loki for recent logs using LogQL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "logql": {"type": "string", "description": "LogQL query string"},
                "since": {
                    "type": "string",
                    "description": "Time range like '5m', '10m'",
                    "default": "5m",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max log lines to return",
                    "default": 50,
                },
            },
            "required": ["logql"],
        },
    },
    {
        "name": "report_finding",
        "description": "Report a network finding or issue that requires attention.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"]},
                "device": {
                    "type": "string",
                    "description": "Device name or 'all' for network-wide",
                },
                "summary": {"type": "string", "description": "One-line summary of the finding"},
                "details": {"type": "string", "description": "Detailed explanation"},
            },
            "required": ["severity", "device", "summary", "details"],
        },
    },
    {
        "name": "check_interface_utilization",
        "description": (
            "Query both inbound and outbound octet rates for a device and calculate "
            "interface utilization percentages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "The device hostname to check",
                },
                "time_range": {
                    "type": "string",
                    "description": "Rate window like '5m', '10m'",
                    "default": "5m",
                },
            },
            "required": ["device_name"],
        },
    },
    {
        "name": "check_snmp_reachability",
        "description": (
            "Check which SNMP-monitored devices are currently reachable. "
            "Queries the 'up' metric for all SNMP jobs and looks for gaps in system_uptime. "
            "Returns a list of devices with their reachability status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "lookup_port_description",
        "description": (
            "Look up what is documented in Nautobot for a specific switch interface — "
            "returns the description (what's plugged in), enabled state, and status. "
            "Use this before reporting any bandwidth finding to understand what the port is."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "Switch hostname, e.g. HomeSwitch01"},
                "interface_name": {"type": "string", "description": "Interface name, e.g. TenGigabitEthernet1/1/3"},
            },
            "required": ["device_name", "interface_name"],
        },
    },
    {
        "name": "diagnose_snmp_failure",
        "description": (
            "Given a device name and IP, find the last known SNMP data timestamp and diagnose "
            "why it may have stopped reporting. Returns device, last_seen, gap_minutes, likely_cause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "The device hostname to diagnose",
                },
                "ip": {
                    "type": "string",
                    "description": "The device IP address",
                },
            },
            "required": ["device_name", "ip"],
        },
    },
]

_SYSTEM_PROMPT = """You are a L2/L3 Network Engineer with 10 years of experience on Cisco IOS/IOS-XE.

Network devices:
- HomeSwitch01 (192.168.3.2) - Cisco WS-C3850-48P
- HomeSwitch02 (192.168.3.3) - Cisco WS-C3850-48P

Interface speeds (WS-C3850-48P):
- GigabitEthernet*: 1,000,000,000 bps (1 Gbps)
- TenGigabitEthernet*: 10,000,000,000 bps (10 Gbps)
- Port-channel*: treat as 1 Gbps per member unless description says otherwise

WS-C3850-48P uplink module (IMPORTANT):
- Gi1/1/1 through Gi1/1/4 are COMBO ports shared with Te1/1/1-Te1/1/4.
- When an SFP+ is inserted and Te1/1/x is active, the corresponding Gi1/1/x is
  automatically disabled by IOS — it will show as down with no traffic.
- Do NOT report Gi1/1/1-4 as errors or missing if Te1/1/1-4 are active.
  This is expected and correct hardware behavior, not a fault.
- The 48 access ports (Gi1/0/1-48) are independent and unaffected.

ALERT THRESHOLDS — only report if these are exceeded:
- WARNING: >70% utilization sustained (700 Mbps on 1G, 7 Gbps on 10G)
- CRITICAL: >90% utilization sustained (900 Mbps on 1G, 9 Gbps on 10G)
- WARNING: >100 errors/s on any interface
- CRITICAL: >1000 errors/s or error rate is rising

DO NOT report bandwidth findings below these thresholds regardless of whether it is the "top consumer".
A port at 14 Mbps on a 10G link is 0.14% utilization — do NOT report this.

WORKFLOW for any interface with traffic:
1. Use check_interface_utilization to get bps for all interfaces
2. Compute utilization % = bps / interface_speed * 100
3. ONLY if utilization exceeds thresholds above: use lookup_port_description to find what is plugged in
4. Include the port description in your finding — "what is it" is as important as "how busy is it"
5. Report a finding only if utilization exceeds thresholds AND include: port description, utilization %, absolute Mbps, whether it is trending up

FINDING FORMAT — must answer: What port? What's plugged in? What % utilization? Is it a problem?
Bad: "Te1/1/3 at 14 Mbps — top consumer"
Good: (only if >70%) "HomeSwitch01 Gi1/0/47 [HDHomeRun Tuner]: 847 Mbps IN / 112 Mbps OUT — 84.7% utilization on 1G port, approaching saturation"

Also check:
- Interface errors (use check_snmp_reachability, report CRITICAL only if gap >10 min)
- Interface flapping in syslog
- SNMP reachability"""


async def run_analysis() -> list:
    """
    Network Engineer: analyses interface utilization and errors, returns findings.
    """
    return await run_agentic_loop(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        user_message=(
            "Run your network engineering analysis. Check interface utilization, error rates, "
            "and discards on all switches. Identify any bandwidth hogs or degraded interfaces."
        ),
        handle_tool_call=_handle_tool_call,
        caller="network_engineer",
        findings=[],
    )


async def answer_question(question: str) -> str:
    """Run an agentic loop to answer a Discord user's network engineering question."""
    return await run_agentic_question(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        question=question,
        handle_tool_call=_handle_tool_call,
        caller="network_engineer",
    )


def _interface_speed_bps(name: str) -> int:
    """Return the line-rate capacity in bps based on interface name."""
    n = name.lower()
    if n.startswith("ten") or n.startswith("te"):
        return 10_000_000_000
    if n.startswith("gigabit") or n.startswith("gi"):
        return 1_000_000_000
    if n.startswith("fastethernet") or n.startswith("fa"):
        return 100_000_000
    # Port-channels: assume 1G default (agent can override with context)
    return 1_000_000_000


async def _check_interface_utilization(device_name: str, time_range: str = "5m") -> dict:
    """Query in/out octet rates and compute utilization % for all interfaces on a device."""
    in_query = f'rate(interface_in_octets_bytes_total{{device_name="{device_name}"}}[{time_range}]) * 8'
    out_query = f'rate(interface_out_octets_bytes_total{{device_name="{device_name}"}}[{time_range}]) * 8'

    in_result = await vm_tools.query_instant(in_query)
    out_result = await vm_tools.query_instant(out_query)

    utilization: dict = {}
    for direction, result in [("in_bps", in_result), ("out_bps", out_result)]:
        for item in result.get("data", {}).get("result", []):
            iface = item.get("metric", {}).get("interface_name", "unknown")
            bps = float(item["value"][1])
            if iface not in utilization:
                speed = _interface_speed_bps(iface)
                utilization[iface] = {
                    "interface": iface,
                    "speed_bps": speed,
                    "speed_label": f"{speed // 1_000_000_000}G" if speed >= 1_000_000_000 else f"{speed // 1_000_000}M",
                }
            utilization[iface][direction] = round(bps, 0)
            speed = utilization[iface]["speed_bps"]
            pct_key = "in_pct" if direction == "in_bps" else "out_pct"
            utilization[iface][pct_key] = round(bps / speed * 100, 2) if speed > 0 else 0

    # Only return interfaces with any traffic, sorted by max utilization descending
    active = [v for v in utilization.values() if v.get("in_bps", 0) + v.get("out_bps", 0) > 0]
    active.sort(key=lambda x: max(x.get("in_pct", 0), x.get("out_pct", 0)), reverse=True)

    return {"device": device_name, "interfaces": active,
            "warning_threshold_pct": 70, "critical_threshold_pct": 90}


async def _check_snmp_reachability() -> dict:
    """Check which SNMP devices are currently reporting metrics."""
    import time

    uptime_result = await vm_tools.query_instant("system_uptime_seconds")
    devices_reporting = {}
    for item in uptime_result.get("data", {}).get("result", []):
        labels = item.get("metric", {})
        device = labels.get("device_name", "unknown")
        ts = item["value"][0] if item.get("value") else 0
        now = time.time()
        gap_minutes = round((now - ts) / 60, 1)
        devices_reporting[device] = {
            "last_seen_ts": ts,
            "gap_minutes": gap_minutes,
            "reporting": gap_minutes < 6,
        }

    return {"devices": devices_reporting}


async def _diagnose_snmp_failure(device_name: str, ip: str) -> dict:
    """Diagnose why a device may have stopped reporting SNMP metrics."""
    import time

    query = f'system_uptime_seconds{{device_name="{device_name}"}}'
    result = await vm_tools.query_instant(query)
    data_points = result.get("data", {}).get("result", [])

    if not data_points:
        last_seen = None
        gap_minutes = None
        likely_cause = (
            "No uptime data found at all. Possible causes: device never configured for SNMP, "
            "wrong community string, or device has been offline for an extended period."
        )
    else:
        ts = data_points[0]["value"][0]
        now = time.time()
        gap_minutes = round((now - ts) / 60, 1)
        last_seen = ts

        if gap_minutes < 5:
            likely_cause = "Device appears to be reporting normally."
        elif gap_minutes < 10:
            likely_cause = (
                "Short gap detected. Could be a transient SNMP timeout or scrape interval issue. "
                "Check if SNMP poller is running and network path is clear."
            )
        elif gap_minutes < 30:
            likely_cause = (
                "Device has been silent >10 minutes. Likely causes: "
                "1) Device rebooted (check logs), "
                "2) SNMP community string changed, "
                "3) ACL blocking SNMP poller. "
                f"Troubleshooting: ping {ip}, snmpwalk -v2c -c public {ip} sysUpTime."
            )
        else:
            likely_cause = (
                f"Device has been silent >{gap_minutes} minutes — likely offline or unreachable. "
                f"Troubleshooting: ping {ip} from poller host, check switch port status, "
                "verify power/physical connectivity."
            )

    return {
        "device": device_name,
        "ip": ip,
        "last_seen_ts": last_seen,
        "gap_minutes": gap_minutes,
        "likely_cause": likely_cause,
    }


async def _handle_tool_call(name: str, inputs: dict, findings: list):
    if name == "query_metrics":
        return await vm_tools.query_instant(inputs["metric"], inputs.get("time_range", "5m"))
    elif name == "query_logs":
        return await loki_tools.query_logs(
            inputs["logql"], inputs.get("limit", 50), inputs.get("since", "5m")
        )
    elif name == "check_interface_utilization":
        return await _check_interface_utilization(
            inputs["device_name"], inputs.get("time_range", "5m")
        )
    elif name == "lookup_port_description":
        iface = await nautobot.get_interface_by_name(inputs["device_name"], inputs["interface_name"])
        if not iface:
            return {"description": "Not found in Nautobot", "enabled": None, "status": None}
        return {
            "description": iface.get("description", ""),
            "enabled": iface.get("enabled"),
            "status": iface.get("status", {}).get("name"),
            "mac_address": iface.get("mac_address"),
            "type": iface.get("type"),
        }
    elif name == "check_snmp_reachability":
        return await _check_snmp_reachability()
    elif name == "diagnose_snmp_failure":
        return await _diagnose_snmp_failure(inputs["device_name"], inputs["ip"])
    elif name == "report_finding":
        finding = Finding(
            role=AgentRole.NETWORK_ENGINEER,
            severity=Severity[inputs["severity"]],
            device=inputs["device"],
            summary=inputs["summary"],
            details=inputs["details"],
        )
        findings.append(finding)
        return {"status": "recorded", "finding_id": len(findings)}
    return {"error": f"Unknown tool: {name}"}
