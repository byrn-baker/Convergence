import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException

from .config import settings
from .models import ShiftReport, TeamStatus
from .team import supervisor
from .team.discord_bot import start_bot
from .tools.discord_reporter import post_shift_report

logger = logging.getLogger(__name__)

# Module-level state
_latest_report: Optional[ShiftReport] = None
_scheduler = AsyncIOScheduler()


async def _run_poll_cycle():
    global _latest_report
    try:
        logger.info("Starting NOC team poll cycle...")
        report = await supervisor.run_team_cycle()
        _latest_report = report

        # Post CRITICAL and WARNING alerts immediately to Discord.
        # INFO findings are suppressed — visible in Grafana dashboards only.
        if settings.discord_webhook_url:
            from .tools.discord_reporter import post_alert
            for finding in report.findings:
                if finding.severity.value in ("CRITICAL", "WARNING"):
                    await post_alert(finding, settings.discord_webhook_url)

        logger.info(
            "Poll cycle complete: %d findings, %d escalations",
            len(report.findings),
            report.escalations,
        )
    except Exception:
        logger.exception("Error during NOC poll cycle")


async def _run_shift_report():
    global _latest_report
    if _latest_report is None:
        logger.info("No report available yet for shift report, running cycle first...")
        await _run_poll_cycle()

    if _latest_report and settings.discord_webhook_url:
        try:
            ok = await post_shift_report(_latest_report, settings.discord_webhook_url)
            if ok:
                logger.info("Shift report posted to Discord")
            else:
                logger.warning("Failed to post shift report to Discord")
        except Exception:
            logger.exception("Error posting shift report")


async def _check_netclaw() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.netclaw_url}/health")
            return resp.status_code == 200
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting net-ops-team service...")

    # Schedule poll cycle
    _scheduler.add_job(
        _run_poll_cycle,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="noc_poll",
        replace_existing=True,
    )

    # Schedule shift report
    _scheduler.add_job(
        _run_shift_report,
        "interval",
        seconds=settings.shift_report_interval_seconds,
        id="shift_report",
        replace_existing=True,
    )

    _scheduler.start()

    # Run an initial poll on startup (non-blocking)
    asyncio.create_task(_run_poll_cycle())

    # Start the Discord bot (non-blocking; disabled if token not set)
    asyncio.create_task(start_bot())

    yield

    _scheduler.shutdown(wait=False)
    logger.info("net-ops-team service stopped")


app = FastAPI(title="net-ops-team", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "net-ops-team"}


@app.get("/api/v1/status", response_model=TeamStatus)
async def get_status():
    netclaw_ok = await _check_netclaw()
    if _latest_report is None:
        return TeamStatus(
            last_poll=None,
            findings_count=0,
            active_escalations=0,
            netclaw_available=netclaw_ok,
        )
    return TeamStatus(
        last_poll=_latest_report.timestamp,
        findings_count=len(_latest_report.findings),
        active_escalations=_latest_report.escalations,
        netclaw_available=netclaw_ok,
    )


@app.get("/api/v1/report/latest")
async def get_latest_report():
    if _latest_report is None:
        raise HTTPException(status_code=404, detail="No report available yet")
    return _latest_report.model_dump(mode="json")


@app.post("/api/v1/run")
async def trigger_run():
    """Manually trigger a team cycle."""
    asyncio.create_task(_run_poll_cycle())
    return {"status": "triggered", "message": "Team cycle started in background"}
