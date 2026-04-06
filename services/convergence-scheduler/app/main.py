from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from .config import settings
from .discord import post_finding, post_report, post_skill_result
from .bot import start_bot, stop_bot, set_netclaw_fn

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("convergence-scheduler")

_scheduler = AsyncIOScheduler()
_latest_result: dict = {}

_SKILLS = [
    (
        "noc",
        "convergence-noc-watch",
        "Run the convergence-noc-watch skill. Check device reachability, interface utilization, "
        "errors, firewall block rate, pfSense health, and syslog.\n\n"
        "RULES:\n"
        "- Do NOT report interfaces that have always been down or unused — only report state CHANGES.\n"
        "- Do NOT report unconfigured/unused VLANs — those are intentional placeholders.\n"
        "- Only report interface utilization if it exceeds 70% on the link speed.\n"
        "- If everything is healthy, report a single [INFO] summary and stop.\n"
        "- Prefix each finding with [CRITICAL], [WARNING], or [INFO].\n"
        "- Every finding MUST include specific evidence: metric values, device names, timestamps.",
    ),
    (
        "security",
        "convergence-security-monitor",
        "Run the convergence-security-monitor skill. Analyze firewall blocks, threat intel, "
        "and NetFlow for real threats.\n\n"
        "RULES:\n"
        "- For EVERY blocked port finding, you MUST answer: source IP, destination IP, "
        "was it blocked or passed, how many attempts, from which country/ASN.\n"
        "- Do NOT report that ports like RDP/Telnet were 'targeted' without saying by whom "
        "and whether the traffic was BLOCKED (expected) or PASSED (actual problem).\n"
        "- Blocked inbound scans are NORMAL firewall operation — only report if the volume "
        "is 10x above baseline or if traffic PASSED the firewall.\n"
        "- Do NOT submit_block_action for IPs that were already BLOCKED. The firewall handled it.\n"
        "- Instead of blocking individual IPs, identify the ASN pattern and recommend pfBlockerNG.\n"
        "- Use get_threat_intel_report and investigate_host to get specifics before reporting.\n"
        "- If all threats were blocked and nothing passed, report a single [INFO] all-clear.\n"
        "- Prefix each finding with [CRITICAL], [WARNING], or [INFO].\n"
        "- Every finding MUST include: source IP/CIDR, destination, action taken (blocked/passed), count.",
    ),
    (
        "reconciler",
        "convergence-interface-reconciler",
        "Run the convergence-interface-reconciler skill. Enrich port descriptions, sync admin state, "
        "diff inventory. Prefix each finding with [CRITICAL], [WARNING], or [INFO].\n\n"
        "RULES:\n"
        "- Report a summary of what was changed, not individual port updates.\n"
        "- Only report WARNING/CRITICAL for actual mismatches or failures.",
    ),
]

REPORT_PROMPT = (
    "Produce a brief shift report summarising the current state of the Convergence network. "
    "Include: device health, security posture, interface reconciliation status, and any open issues."
)

_FINDING_RE = re.compile(r"\[(CRITICAL|WARNING|INFO)]\s*(.+?)(?:\n|$)", re.IGNORECASE)


async def _ask_netclaw(prompt: str, timeout: int = 900, agent: str = "main") -> str:
    """Send a prompt to NetClaw via the REST proxy. Retries if agent is busy."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout + 60) as client:
                resp = await client.post(
                    f"{settings.netclaw_proxy_url}/api/agent",
                    json={"message": prompt, "timeout": timeout, "agent": agent},
                )
                if resp.status_code == 503:
                    wait = 30 * (attempt + 1)
                    logger.info("Agent busy, retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "ok":
                    logger.warning("NetClaw error: %s", data.get("message", "unknown"))
                    return ""
                result = data.get("result", "")
                return result if isinstance(result, str) else str(result)
        except httpx.ReadTimeout:
            logger.error("NetClaw timeout after %ds", timeout)
            return ""
        except Exception as e:
            logger.error("NetClaw request failed: %s", e)
            return ""
    logger.warning("Agent still busy after %d retries — giving up", max_retries)
    return ""


def _parse_findings(text: str) -> list[dict]:
    return [{"severity": m.group(1).upper(), "summary": m.group(2).strip()} for m in _FINDING_RE.finditer(text)]


async def _run_poll_cycle() -> None:
    global _latest_result
    logger.info("Starting poll cycle")
    all_responses: list[str] = []
    all_findings: list[dict] = []

    # Run all skills concurrently on their dedicated agents
    async def _run_skill(agent_name, skill_name, prompt):
        logger.info("Running skill: %s (agent: %s)", skill_name, agent_name)
        response = await _ask_netclaw(prompt, timeout=600, agent=agent_name)
        if not response:
            logger.warning("Empty response for %s — skipping", skill_name)
            return skill_name, "", []
        findings = _parse_findings(response)
        logger.info("  %s: %d findings", skill_name, len(findings))
        return skill_name, response, findings

    tasks = [_run_skill(a, s, p) for a, s, p in _SKILLS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.error("Skill failed: %s", result)
            continue
        skill_name, response, findings = result
        if response:
            all_responses.append(f"--- {skill_name} ---\n{response}")
            all_findings.extend(findings)

    combined = "\n\n".join(all_responses)
    _latest_result = {"response": combined, "findings": all_findings}
    logger.info("Poll cycle complete: %d total findings", len(all_findings))

    for resp_text in all_responses:
        await post_skill_result(resp_text)


async def _run_report() -> None:
    logger.info("Generating shift report")
    response = await _ask_netclaw(REPORT_PROMPT, timeout=120)
    if response:
        await post_report(response)


@asynccontextmanager
async def lifespan(app: FastAPI):
    set_netclaw_fn(_ask_netclaw)
    _scheduler.add_job(_run_poll_cycle, "interval", minutes=settings.poll_interval_minutes, id="poll")
    _scheduler.add_job(_run_report, "interval", minutes=settings.report_interval_minutes, id="report")
    _scheduler.start()
    bot_task = asyncio.create_task(start_bot())
    asyncio.create_task(_run_poll_cycle())
    yield
    _scheduler.shutdown(wait=False)
    await stop_bot()
    bot_task.cancel()


app = FastAPI(title="convergence-scheduler", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "convergence-scheduler"}


@app.get("/api/v1/latest")
async def latest():
    return _latest_result


@app.post("/api/v1/run")
async def trigger_run():
    asyncio.create_task(_run_poll_cycle())
    return {"status": "triggered"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
