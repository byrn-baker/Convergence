import asyncio
from datetime import datetime, timezone

import anthropic

from ..config import settings
from ..models import ShiftReport
from . import noc_officer, network_engineer, security_expert, nas_engineer, interface_reconciler


async def run_team_cycle() -> ShiftReport:
    """Run all agents concurrently and build a shift report."""
    results = await asyncio.gather(
        noc_officer.run_noc_watch(),
        network_engineer.run_analysis(),
        security_expert.run_security_check(),
        nas_engineer.run_nas_check(),
        interface_reconciler.run_reconciliation(),
        return_exceptions=True,
    )

    all_findings = []
    for result in results:
        if isinstance(result, Exception):
            # Log but don't crash
            continue
        if isinstance(result, list):
            all_findings.extend(result)

    criticals = [f for f in all_findings if f.severity.value == "CRITICAL"]

    return ShiftReport(
        timestamp=datetime.now(timezone.utc),
        findings=all_findings,
        open_issues=len([f for f in all_findings if f.severity.value != "INFO"]),
        escalations=len(criticals),
    )


async def route_question(question: str, user_name: str = "user") -> str:
    """Route a question from Discord to the appropriate agent and return text response."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Step 1: Route to the right agent
    router = await client.messages.create(
        model=settings.model,
        max_tokens=50,
        system="""You are a dispatcher for a network operations team. Given a user question, reply with ONLY one of these exact words:
SECURITY - for firewall, threats, security incidents, blocks, pfSense
INTERFACES - for interface inventory, Nautobot, SNMP reconciliation, port status
NETWORK - for SNMP issues, switch problems, bandwidth, routing, connectivity
NAS - for Synology NAS, storage, disks, RAID
NOC - for general status, uptime, multi-device health overview
Reply with ONLY the single word.""",
        messages=[{"role": "user", "content": question}],
    )
    agent_key = router.content[0].text.strip().upper()

    # Step 2: Dispatch
    try:
        if agent_key == "SECURITY":
            return await security_expert.answer_question(question)
        elif agent_key == "INTERFACES":
            return await interface_reconciler.answer_question(question)
        elif agent_key == "NETWORK":
            return await network_engineer.answer_question(question)
        elif agent_key == "NAS":
            return await nas_engineer.answer_question(question)
        else:
            return await noc_officer.answer_question(question)
    except Exception as e:
        return f"Error from {agent_key} agent: {e}"
