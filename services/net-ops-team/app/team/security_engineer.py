import httpx
import anthropic

from ..config import settings
from ..models import AgentRole, Finding, Severity
from ..tools import loki as loki_tools
from ..tools import victoriametrics as vm_tools

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
            "Query NetFlow v5 records from pfSense via Loki. Attributes per record: "
            "source.address, source.port, destination.address, destination.port, "
            "network.transport, flow.io.bytes, flow.io.packets. "
            "Use to investigate suspicious IPs, large transfers, or C2 beaconing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip_filter": {
                    "type": "string",
                    "description": "Optional IP address to filter on. Empty = all flows.",
                    "default": "",
                },
                "since": {
                    "type": "string",
                    "description": "Time range like '5m', '15m', '1h'",
                    "default": "15m",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return",
                    "default": 100,
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
    {
        "name": "get_threat_intel",
        "description": "Retrieve the current threat intelligence summary including known bad IPs and active threat feeds.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_pending_blocks",
        "description": "Retrieve pending firewall block actions from the automation agent queue.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

_SYSTEM_PROMPT = """You are a Network Security Engineer. Your job is to monitor the firewall, \
analyse threat intelligence, and identify security incidents.

Infrastructure you protect:
- pfSense-FW01 (192.168.100.1) - Netgate firewall — WAN, LAN (192.168.1.0/24), DMZ
- HomeSwitch01/02 (192.168.3.2-3) - internal switching
- Threat Intel service — feeds of known malicious IPs and domains

Your job each cycle:
1. Query firewall block rates and recent filterlog entries in Loki
2. Retrieve threat intel summary — cross-reference any hits in logs
3. Check pending automation-agent block actions
4. Use NetFlow to hunt for: C2 beaconing, data exfiltration, lateral movement
   NetFlow record attributes: source.address, destination.address, destination.port,
   network.transport, flow.io.bytes, flow.io.packets (all in OTLP JSON format)
Report WARNING for suspicious patterns, CRITICAL for confirmed intrusion indicators or active attacks."""


async def run_security_check() -> list:
    """
    Security Engineer: analyses firewall logs and threat intel, returns findings.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_message = (
        "Run your security check cycle. Review firewall block rates, recent filterlog entries, "
        "threat intelligence hits, and any pending automated block actions."
    )

    messages = [{"role": "user", "content": user_message}]
    findings = []

    while True:
        response = await client.messages.create(
            model=settings.model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await _handle_tool_call(block.name, block.input, findings)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        }
                    )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return findings


async def _get_threat_intel() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.threat_intel_url}/api/v1/threats/summary")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e), "source": "threat-intel"}


async def _get_pending_blocks() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.automation_agent_url}/api/v1/actions/pending"
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e), "source": "automation-agent"}


async def _handle_tool_call(name: str, inputs: dict, findings: list):
    if name == "query_metrics":
        return await vm_tools.query_instant(inputs["metric"], inputs.get("time_range", "5m"))
    elif name == "query_logs":
        return await loki_tools.query_logs(
            inputs["logql"], inputs.get("limit", 50), inputs.get("since", "5m")
        )
    elif name == "get_threat_intel":
        return await _get_threat_intel()
    elif name == "get_pending_blocks":
        return await _get_pending_blocks()
    elif name == "query_netflow":
        return await loki_tools.query_netflow(
            inputs.get("ip_filter", ""), inputs.get("since", "15m"), inputs.get("limit", 100)
        )
    elif name == "report_finding":
        finding = Finding(
            role=AgentRole.SECURITY_ENGINEER,
            severity=Severity[inputs["severity"]],
            device=inputs["device"],
            summary=inputs["summary"],
            details=inputs["details"],
        )
        findings.append(finding)
        return {"status": "recorded", "finding_id": len(findings)}
    return {"error": f"Unknown tool: {name}"}
