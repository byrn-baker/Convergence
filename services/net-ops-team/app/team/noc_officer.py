from ..config import settings
from ..models import AgentRole, Finding, Severity
from ..tools import loki as loki_tools
from ..tools import victoriametrics as vm_tools
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
        "name": "query_netflow",
        "description": (
            "Query NetFlow records from Loki. Returns flow records with source/destination IPs, "
            "ports, protocol, bytes, and packets. Each log line is a raw OTLP JSON record — "
            "parse source.address, destination.address, destination.port, network.transport, "
            "flow.io.bytes, flow.io.packets from the attributes array. "
            "Use this to identify top talkers, unusual connections, or unexpected external traffic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip_filter": {
                    "type": "string",
                    "description": "Optional IP address to filter on (matches src or dst). Empty = all flows.",
                    "default": "",
                },
                "since": {
                    "type": "string",
                    "description": "Time range like '5m', '15m', '1h'",
                    "default": "5m",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return",
                    "default": 50,
                },
            },
            "required": [],
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
]

_SYSTEM_PROMPT = """You are the NOC Watch Officer for a home network. Your role is L1 monitoring — triage and escalate, not deep analysis.

Network devices:
- HomeSwitch01 (192.168.3.2) - Cisco WS-C3850-48P (1G access ports, 10G uplinks)
- HomeSwitch02 (192.168.3.3) - Cisco WS-C3850-48P (1G access ports, 10G uplinks)
- pfSense-FW01 (192.168.100.1) - Netgate firewall
- SynologyNAS01 (192.168.100.22) / SynologyNAS02 (192.168.100.23) - Synology NAS

EXACT metric names (use ONLY these):
- system_uptime_seconds{device_name="HomeSwitch01"} — uptime
- interface_in_errors_total{device_name="HomeSwitch01"} — error counts
- firewall_events_total{action="block"} — block events

NetFlow data is available via query_netflow. Each record is a raw OTLP JSON line.
To extract fields from the attributes array, look for patterns like:
  "key":"source.address","value":{"stringValue":"1.2.3.4"}
  "key":"destination.port","value":{"intValue":"443"}
  "key":"flow.io.bytes","value":{"intValue":"1024"}
Use NetFlow to identify: unexpected external destinations, large data transfers, unusual protocols.

ALERT RULES — only report WARNING/CRITICAL if:
- Device unreachable (uptime metric missing AND confirmed by checking logs)
- Interface errors > 100 in last 5 minutes
- Firewall block rate dramatically higher than baseline (>10x normal)
- CRITICAL log entries in syslog
- Large unexpected data exfiltration visible in NetFlow (>100MB to unknown external IPs)

Do NOT report: empty metric results as outages, normal firewall blocks, low bandwidth as issues.
Empty results = metric not available, report INFO only.

Be brief. One finding per device. If everything is healthy, one INFO finding for "all clear"."""


async def run_noc_watch() -> list:
    """
    NOC Watch Officer: polls all metrics and logs, returns findings.
    """
    return await run_agentic_loop(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        user_message=(
            "Run your NOC watch cycle. Check all devices for health, interface errors, "
            "and any anomalies in the last 5 minutes."
        ),
        handle_tool_call=_handle_tool_call,
        findings=[],
        caller="noc_officer",
    )


async def answer_question(question: str) -> str:
    """Run an agentic loop to answer a Discord user's NOC question."""
    return await run_agentic_question(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        question=question,
        handle_tool_call=_handle_tool_call,
        caller="noc_officer",
    )


async def _handle_tool_call(name: str, inputs: dict, findings: list):
    if name == "query_metrics":
        return await vm_tools.query_instant(inputs["metric"], inputs.get("time_range", "5m"))
    elif name == "query_logs":
        return await loki_tools.query_logs(
            inputs["logql"], inputs.get("limit", 50), inputs.get("since", "5m")
        )
    elif name == "query_netflow":
        return await loki_tools.query_netflow(
            inputs.get("ip_filter", ""), inputs.get("since", "5m"), inputs.get("limit", 50)
        )
    elif name == "report_finding":
        finding = Finding(
            role=AgentRole.NOC_OFFICER,
            severity=Severity[inputs["severity"]],
            device=inputs["device"],
            summary=inputs["summary"],
            details=inputs["details"],
        )
        findings.append(finding)
        return {"status": "recorded", "finding_id": len(findings)}
    return {"error": f"Unknown tool: {name}"}
