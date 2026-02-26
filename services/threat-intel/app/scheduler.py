"""APScheduler hourly enrichment job."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app import state
from app.config import settings
from app.analysis import vm_client, ports as port_analysis, claude_client
from app.enrichment import aggregator
import app.metrics as m

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _overall_risk(blocked: list[dict], outbound: list[dict]) -> str:
    """Derive overall risk from the highest individual IP score."""
    scores = [
        e.get("intel", {}).get("composite_score", 0)
        for e in blocked + outbound
    ]
    if not scores:
        return "none"
    mx = max(scores)
    if mx >= 75:
        return "critical"
    elif mx >= 50:
        return "high"
    elif mx >= 25:
        return "medium"
    elif mx >= 10:
        return "low"
    return "none"


async def _run_enrichment() -> None:
    logger.info("Starting threat intelligence enrichment cycle")

    blocked_raw = await vm_client.get_top_blocked_ips(
        settings.top_blocked_ips, settings.lookback_hours
    )
    outbound_raw = await vm_client.get_top_outbound_ips(
        settings.top_outbound_ips, settings.lookback_hours
    )

    # Enrich all IPs
    enriched_blocked: list[dict[str, Any]] = []
    for entry in blocked_raw:
        intel = await aggregator.enrich_ip(
            entry["ip"], entry["direction"], entry["action"], entry["count"]
        )
        enriched_blocked.append({**entry, "intel": intel})

    enriched_outbound: list[dict[str, Any]] = []
    for entry in outbound_raw:
        intel = await aggregator.enrich_ip(
            entry["ip"], entry["direction"], entry["action"], entry["count"]
        )
        # Look up which internal LAN hosts are connecting to this destination
        src_ips = await vm_client.get_outbound_sources(entry["ip"], settings.lookback_hours)
        enriched_outbound.append({**entry, "intel": intel, "src_ips": src_ips})

    # Active pfSense interfaces (for Claude pfSense-specific recommendations)
    interfaces = await vm_client.get_active_interfaces(settings.lookback_hours)

    # Port analysis
    top_ports = await port_analysis.get_top_blocked_ports(settings.lookback_hours)
    critical_ports = [p for p in top_ports if p["risk_level"] == "critical"]

    # Summary
    known_bad_in = sum(
        1 for e in enriched_blocked if e.get("intel", {}).get("is_known_bad_actor")
    )
    known_bad_out = sum(
        1 for e in enriched_outbound if e.get("intel", {}).get("is_known_bad_actor")
    )
    overall_risk = _overall_risk(enriched_blocked, enriched_outbound)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_hours": settings.lookback_hours,
        "summary": {
            "total_blocked_ips": len(enriched_blocked),
            "known_bad_actors_inbound": known_bad_in,
            "known_bad_actors_outbound": known_bad_out,
            "critical_ports_targeted": len(critical_ports),
            "overall_risk_level": overall_risk,
        },
        "blocked_ips": enriched_blocked,
        "outbound_ips": enriched_outbound,
        "port_analysis": {
            "top_blocked_ports": top_ports,
            "critical_ports_hit": critical_ports,
        },
    }

    # Claude narrative — pass interfaces for pfSense-specific recommendations
    narrative = await claude_client.generate_narrative(report, interfaces=interfaces)
    report["narrative"] = narrative

    # Publish to module state
    state.latest_report = report

    # Update service-level metrics
    total_ips = len(enriched_blocked) + len(enriched_outbound)
    m.threat_intel_enrichment_last_success_timestamp.set(time.time())
    m.threat_intel_enrichment_ips_processed_total.set(total_ips)

    logger.info(
        "Enrichment complete: %d blocked IPs, %d outbound IPs, risk=%s",
        len(enriched_blocked),
        len(enriched_outbound),
        overall_risk,
    )


def _job_wrapper() -> None:
    """Synchronous wrapper that runs the async job in a fresh event loop."""
    try:
        asyncio.run(_run_enrichment())
    except Exception:
        logger.exception("Enrichment job failed")


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _job_wrapper,
        "interval",
        seconds=settings.enrichment_interval_seconds,
        id="enrichment",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started; enrichment every %ds",
        settings.enrichment_interval_seconds,
    )

    # Run immediately on startup in a background thread
    import threading
    t = threading.Thread(target=_job_wrapper, daemon=True)
    t.start()
