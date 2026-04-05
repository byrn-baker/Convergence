import json

import httpx

from ..config import settings
from ..models import AgentRole, Finding, Severity
from ..tools import loki as loki_tools
from ..tools import victoriametrics as vm_tools
from ..tools import pfsense as pfsense_tools
from ..tools import nautobot
from ..llm_client import run_agentic_loop, run_agentic_question

_TOOLS = [
    {
        "name": "query_metrics",
        "description": "Query VictoriaMetrics for a specific metric using PromQL. Returns current values.",
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
        "name": "get_firewall_block_rate",
        "description": "Get the current firewall block rate (events/second) over the last 15 minutes.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_top_blocked_ips",
        "description": "Get the top 10 source IPs generating firewall block events over the last 15 minutes.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_threat_intel",
        "description": "Retrieve the full current threat intelligence report from the threat-intel service.",
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
    {
        "name": "query_netflow",
        "description": (
            "Query NetFlow v5 records from pfSense via Loki. Each record is a raw OTLP JSON line "
            "with attributes: source.address, source.port, destination.address, destination.port, "
            "network.transport, flow.io.bytes, flow.io.packets, flow.start, flow.end. "
            "Use this for: data exfiltration hunting (large flows to unknown external IPs), "
            "C2 beaconing (regular small flows to same external IP), port scanning (one src hitting "
            "many dst ports), lateral movement (internal-to-internal unexpected flows)."
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
        "name": "get_firewall_logs",
        "description": "Query Loki for recent pfSense filterlog entries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "Time range like '5m', '15m', '1h'",
                    "default": "15m",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max log lines",
                    "default": 100,
                },
            },
            "required": [],
        },
    },
    {
        "name": "submit_block_action",
        "description": (
            "Submit an IP address to the automation agent for blocking on pfSense. "
            "This goes through the full automation pipeline: dedup, rate limiting, "
            "LLM action proposal, human approval (if score < auto-approve threshold), "
            "and GAIT audit trail. Use this instead of recommend_action when you have "
            "high-confidence threat intel (composite_score >= 80, is_known_bad_actor=true) "
            "and want the IP actually blocked, not just recommended."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP address to block (e.g. 1.2.3.4)"},
                "reason": {"type": "string", "description": "Why this IP should be blocked"},
                "score": {"type": "integer", "description": "Composite threat score (0-100)"},
                "direction": {
                    "type": "string",
                    "description": "Traffic direction: inbound or outbound",
                    "default": "inbound",
                },
                "intel": {
                    "type": "object",
                    "description": "Threat intel data (abuse_confidence_score, org, country, etc.)",
                },
            },
            "required": ["ip", "reason", "score"],
        },
    },
    {
        "name": "investigate_host",
        "description": (
            "Investigate a suspicious internal host by querying pfSense DHCP leases, "
            "ARP table, and Nautobot device inventory. Returns the host's MAC address, "
            "hostname, which switch port it's connected to, and its Nautobot record. "
            "Use this when you find suspicious outbound traffic from an internal IP "
            "and need to identify what device it is and where it's physically connected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Internal IP address to investigate"},
            },
            "required": ["ip"],
        },
    },
    {
        "name": "recommend_action",
        "description": (
            "Record a security recommendation as a finding. This does NOT auto-execute anything — "
            "it records expert advice about what action to take and why, like filing a ticket."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title of the recommendation"},
                "action": {"type": "string", "description": "Exactly what should be done"},
                "rationale": {"type": "string", "description": "Why this action is needed"},
                "priority": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                "device": {"type": "string", "description": "Target device or 'all'"},
            },
            "required": ["title", "action", "rationale", "priority", "device"],
        },
    },
    {
        "name": "report_finding",
        "description": "Report a security finding or incident.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"]},
                "device": {
                    "type": "string",
                    "description": "Device name or 'all' for network-wide",
                },
                "summary": {"type": "string", "description": "One-line summary of the finding"},
                "details": {"type": "string", "description": "Detailed explanation and remediation steps"},
            },
            "required": ["severity", "device", "summary", "details"],
        },
    },
]

_SYSTEM_PROMPT = """You are a Senior Network Security Engineer / Blue Team specialist. You have deep expertise in pfSense, firewall policy, threat hunting, and incident response.

YOU HAVE THE POWER TO ACT, NOT JUST RECOMMEND.

Your job:
1) Analyze firewall block rates and trends — is the block rate normal or spiking?
2) Identify top attacking IPs and cross-reference with threat intel
3) Hunt for threats using both firewall logs AND NetFlow data:
   - Port scans: one src IP hitting many destination ports in NetFlow
   - Brute force: many flows to SSH(22)/RDP(3389)/SMB(445) from external IPs
   - C2 beaconing: regular small flows (consistent flow.io.bytes) to same external IP at fixed intervals
   - Data exfiltration: large outbound flows (flow.io.bytes > 10MB) to unknown external destinations
   - Lateral movement: unexpected internal-to-internal flows between VLANs
4) For each finding, provide SPECIFIC remediation: exact pfSense rule changes, IP ranges to block, services to harden.
5) Monitor the overall security posture. Be methodical and thorough.

ACTION PROTOCOL — when you find a threat, DO NOT just recommend blocking. Take action:
- For high-risk IPs (composite_score >= 80, is_known_bad_actor=true): use submit_block_action
  to send the IP directly to the automation agent. It will go through the approval pipeline
  (dedup, rate limit, GAIT audit trail, Discord approval if needed).
- For suspicious internal hosts: use investigate_host to identify the device (MAC, hostname,
  switch port, Nautobot record) before reporting. Include the investigation results in your finding.
- Use recommend_action ONLY for things that cannot be automated: policy changes, service hardening,
  manual forensic analysis, or actions that require human judgment.

NetFlow attribute format — each record is OTLP JSON, extract values like:
  "key":"source.address","value":{"stringValue":"1.2.3.4"}
  "key":"flow.io.bytes","value":{"intValue":"102400"}
  "key":"destination.port","value":{"intValue":"443"}

Infrastructure you protect:
- pfSense-FW01 (192.168.100.1) — Netgate firewall, WAN + LAN (192.168.1.0/24) + DMZ
- HomeSwitch01 (192.168.3.2), HomeSwitch02 (192.168.3.3) — internal switching
- Internal subnets: 192.168.1.0/24 (LAN), 192.168.3.0/24 (mgmt), 192.168.100.0/24 (servers), 192.168.102.0/24
- Threat Intel service — feeds of known malicious IPs and domains
- Automation Agent — can execute pfSense block actions via submit_block_action tool"""


async def run_security_check() -> list:
    """
    Security Expert: deep-dive security analysis, returns findings.
    """
    return await run_agentic_loop(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        user_message=(
            "Run a full security analysis cycle. Check firewall block rates, top attacking IPs, "
            "threat intelligence, pending blocks, and recent firewall logs. Hunt for port scans, "
            "brute force, C2 beaconing, and data exfiltration. Report all findings with specific "
            "remediation steps."
        ),
        handle_tool_call=_handle_tool_call,
        caller="security_expert",
        findings=[],
    )


async def answer_question(question: str) -> str:
    """Run an agentic loop to answer a Discord user's security question."""
    return await run_agentic_question(
        system=_SYSTEM_PROMPT,
        tools=_TOOLS,
        question=question,
        handle_tool_call=_handle_tool_call,
        caller="security_expert",
    )


async def _get_threat_intel() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.threat_intel_url}/api/report")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e), "source": "threat-intel"}


async def _get_pending_blocks() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.automation_agent_url}/api/automation/pending")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e), "source": "automation-agent"}


async def _get_top_blocked_ips() -> dict:
    query = 'topk(10, sum by (src_ip) (rate(firewall_events_total{action="block"}[15m])))'
    result = await vm_tools.query_instant(query)
    if "error" in result:
        return result
    data = result.get("data", {}).get("result", [])
    top_ips = [
        {
            "src_ip": item.get("metric", {}).get("src_ip", "unknown"),
            "rate_per_sec": float(item["value"][1]) if item.get("value") else 0,
        }
        for item in data
    ]
    return {"top_blocked_ips": top_ips}


async def _handle_tool_call(name: str, inputs: dict, findings: list):
    if name == "query_metrics":
        return await vm_tools.query_instant(inputs["metric"], inputs.get("time_range", "5m"))

    elif name == "query_logs":
        return await loki_tools.query_logs(
            inputs["logql"], inputs.get("limit", 50), inputs.get("since", "5m")
        )

    elif name == "get_firewall_block_rate":
        rate = await vm_tools.get_firewall_block_rate(minutes=15)
        return {"block_rate_per_sec": rate, "window_minutes": 15}

    elif name == "get_top_blocked_ips":
        return await _get_top_blocked_ips()

    elif name == "get_threat_intel":
        return await _get_threat_intel()

    elif name == "get_pending_blocks":
        return await _get_pending_blocks()

    elif name == "query_netflow":
        return await loki_tools.query_netflow(
            inputs.get("ip_filter", ""), inputs.get("since", "15m"), inputs.get("limit", 100)
        )

    elif name == "get_firewall_logs":
        logql = '{job="syslog"} |= "filterlog"'
        return await loki_tools.query_logs(
            logql,
            limit=inputs.get("limit", 100),
            since=inputs.get("since", "15m"),
        )

    elif name == "submit_block_action":
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{settings.automation_agent_url}/api/automation/submit",
                    json={
                        "ip": inputs["ip"],
                        "reason": inputs.get("reason", ""),
                        "score": inputs.get("score", 0),
                        "direction": inputs.get("direction", "inbound"),
                        "intel": inputs.get("intel", {}),
                        "submitted_by": "security_expert",
                    },
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            return {"error": str(e), "source": "automation-agent"}

    elif name == "investigate_host":
        ip = inputs["ip"]
        result = {"ip": ip}
        try:
            leases = await pfsense_tools.get_dhcp_leases()
            for lease in leases:
                if isinstance(lease, dict) and lease.get("ip") == ip:
                    result["dhcp"] = lease
                    break
            arp = await pfsense_tools.get_arp_table()
            for entry in arp:
                if isinstance(entry, dict) and entry.get("ip") == ip:
                    result["arp"] = entry
                    break
            mac = result.get("dhcp", result.get("arp", {})).get("mac", "")
            if mac:
                result["mac"] = mac
                for device_name in ["HomeSwitch01", "HomeSwitch02"]:
                    ifaces = await nautobot.get_interfaces(device_name)
                    for iface in ifaces:
                        if isinstance(iface, dict) and iface.get("mac_address", "").lower() == mac.lower():
                            result["switch_port"] = {
                                "device": device_name,
                                "interface": iface.get("name"),
                                "description": iface.get("description"),
                                "enabled": iface.get("enabled"),
                            }
                            break
        except Exception as e:
            result["error"] = str(e)
        return result

    elif name == "recommend_action":
        finding = Finding(
            role=AgentRole.SECURITY_EXPERT,
            severity=Severity["CRITICAL" if inputs["priority"] == "CRITICAL" else
                              "WARNING" if inputs["priority"] in ("HIGH", "MEDIUM") else "INFO"],
            device=inputs["device"],
            summary=f"[RECOMMENDATION] {inputs['title']}",
            details=f"Action: {inputs['action']}\n\nRationale: {inputs['rationale']}\n\nPriority: {inputs['priority']}",
        )
        findings.append(finding)
        return {"status": "recorded", "recommendation": inputs["title"]}

    elif name == "report_finding":
        finding = Finding(
            role=AgentRole.SECURITY_EXPERT,
            severity=Severity[inputs["severity"]],
            device=inputs["device"],
            summary=inputs["summary"],
            details=inputs["details"],
        )
        findings.append(finding)
        return {"status": "recorded", "finding_id": len(findings)}

    return {"error": f"Unknown tool: {name}"}
