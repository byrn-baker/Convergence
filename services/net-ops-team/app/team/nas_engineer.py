import anthropic

from ..config import settings
from ..models import AgentRole, Finding, Severity
from ..tools import victoriametrics as vm_tools

_NAS_DEVICES = [
    {"name": "SynologyNAS01", "ip": "192.168.100.22"},
    {"name": "SynologyNAS02", "ip": "192.168.100.23"},
]

_TOOLS = [
    {
        "name": "query_nas_metric",
        "description": "Query a Synology NAS metric from VictoriaMetrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "PromQL metric query"},
                "device_name": {"type": "string", "description": "NAS device name filter (SynologyNAS01 or SynologyNAS02)"},
            },
            "required": ["metric"],
        },
    },
    {
        "name": "report_finding",
        "description": "Report a NAS health finding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"]},
                "device": {"type": "string", "description": "NAS device name"},
                "summary": {"type": "string", "description": "One-line summary"},
                "details": {"type": "string", "description": "Full details of the finding"},
            },
            "required": ["severity", "device", "summary", "details"],
        },
    },
]

_SYSTEM_PROMPT = """You are the NAS Engineer for a home network. You monitor two Synology NAS devices.

Devices:
- SynologyNAS01 (192.168.100.22)
- SynologyNAS02 (192.168.100.23)

Metrics available in VictoriaMetrics (all tagged with device_name label):
NOTE: OTEL appends unit suffixes — use these EXACT names:
- nas_system_temperature_celsius — chassis temperature. WARNING >45, CRITICAL >55
- nas_power_status_ratio — 1=Normal, 2=Failed. CRITICAL if not 1
- nas_disk_status_ratio — per disk (disk_id label): 1=Normal, 5=Crashed. CRITICAL if not 1
- nas_disk_temperature_celsius — per disk temperature. WARNING >45, CRITICAL >55
- nas_raid_status_ratio — per volume (raid_name label): 1=Normal, 11=Degrade, 12=Crashed. CRITICAL if not 1
- nas_raid_free_bytes — free bytes per RAID volume
- nas_raid_total_bytes — total bytes per RAID volume
- system_uptime_seconds{device_name="SynologyNAS01"} — uptime in seconds
- interface_in_octets_bytes_total / interface_out_octets_bytes_total — per NIC traffic

IMPORTANT — Storage Pool vs Volume semantics:
- "Storage Pool" entries in nas_raid_free_bytes showing 0 free is NORMAL and expected.
  It means all pool capacity is allocated to Volumes — this is correct Synology behavior.
- Only Volume entries (raid_name=~"Volume.*") reflect actual user-available disk space.
  Report storage warnings based on Volume free space only, never on Storage Pool entries.
- Use this PromQL to get meaningful free space:
  nas_raid_free_bytes{raid_name=~"Volume.*"} / nas_raid_total_bytes{raid_name=~"Volume.*"}

IMPORTANT: If a metric query returns empty results (no data), this means SNMP is not yet configured on that NAS device — report a single INFO finding per device stating SNMP monitoring is not yet active, and stop checking further metrics for that device. Do NOT report CRITICAL when metrics are simply absent.

Check both NAS devices. Report CRITICAL for any disk crash, RAID degrade/crash, power failure, or temp over 55°C.
Report WARNING for temps 45-55°C, RAID repairing/syncing, or uptime under 5 minutes (recent reboot).
Report INFO with a health summary if everything looks normal, or if SNMP data is not yet available."""


async def run_nas_check() -> list:
    """NAS Engineer: checks both Synology NAS devices for health issues."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    messages = [
        {
            "role": "user",
            "content": (
                "Run your NAS health check. Check both SynologyNAS01 and SynologyNAS02. "
                "Check system temperature, power status, all disk statuses, disk temperatures, "
                "and RAID volume status and usage."
            ),
        }
    ]
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


async def answer_question(question: str) -> str:
    """Run an agentic loop to answer a Discord user's NAS question."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    messages = [{"role": "user", "content": question}]
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
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    return block.text[:1800]
            return "No response generated."

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

    return "No response generated."


async def _handle_tool_call(name: str, inputs: dict, findings: list):
    if name == "query_nas_metric":
        metric = inputs["metric"]
        device = inputs.get("device_name")
        # Only append label filter if metric doesn't already contain a selector
        if device and "{" not in metric:
            query = f'{metric}{{device_name="{device}"}}'
        else:
            query = metric
        return await vm_tools.query_instant(query)

    elif name == "report_finding":
        finding = Finding(
            role=AgentRole.NAS_ENGINEER,
            severity=Severity[inputs["severity"]],
            device=inputs["device"],
            summary=inputs["summary"],
            details=inputs["details"],
        )
        findings.append(finding)
        return {"status": "recorded", "finding_id": len(findings)}

    return {"error": f"Unknown tool: {name}"}
