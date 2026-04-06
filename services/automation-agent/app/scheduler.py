"""APScheduler polling job for the automation agent.

Poll cycle (every POLL_INTERVAL_SECONDS, default 10 min):
  1. Fetch high-risk IPs from threat-intel /api/infinity/blocked_ips
     and /api/infinity/outbound_suspicious
  2. Filter: composite_score >= AUTO_ACTION_THRESHOLD
             AND is_known_bad_actor = true
             AND likely_false_positive = false
             AND not already processed recently (Redis TTL dedup)
  3. Rate-limit check (MAX_ACTIONS_PER_HOUR sliding window)
  4. For each qualifying IP: open GAIT session → baseline → Claude proposal
     → decision (dry_run / pending / auto_approve) → execute_and_verify
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from app import state
from app.actions.executor import execute_and_verify, _update_state
from app.actions.baseline import capture_baseline
from app.actions.pfblocker import PfBlockerAction, execute_pfblocker_add, PFBLOCKER_CUSTOM_LIST
from app.actions.rate_limiter import (
    check_rate_limit,
    is_ip_already_processed,
    mark_ip_processed,
    get_block_count,
)
from app.analysis.claude_action import build_action_prompt, propose_action
from app.audit.git_trail import trail
from app.config import settings
from app.notifications.discord import send_action_proposal, send_action_outcome
import app.metrics as m

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_loop: asyncio.AbstractEventLoop | None = None


# ---------------------------------------------------------------------------
# Session ID helpers
# ---------------------------------------------------------------------------


def make_session_id(ip: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = ip.replace(".", "-")
    return f"{ts}-{safe}"


# ---------------------------------------------------------------------------
# Threat-intel polling
# ---------------------------------------------------------------------------


async def fetch_high_risk_ips() -> list[dict[str, Any]]:
    """Pull qualifying IPs from the threat-intel service.

    Returns a list of dicts each containing:
        ip, score, direction, count, intel (full enrichment dict)

    An IP qualifies if:
      - composite_score >= AUTO_ACTION_THRESHOLD
      - is_known_bad_actor == true
      - likely_false_positive == false (from intel or heuristic)
    """
    qualifying: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            blocked_resp = await client.get(
                f"{settings.threat_intel_url}/api/infinity/blocked_ips"
            )
            blocked_resp.raise_for_status()
            blocked_flat: list[dict] = blocked_resp.json()

            outbound_resp = await client.get(
                f"{settings.threat_intel_url}/api/infinity/outbound_suspicious"
            )
            outbound_resp.raise_for_status()
            outbound_flat: list[dict] = outbound_resp.json()

            # Full report gives us the nested intel dict (flat endpoints lose some fields)
            try:
                full_resp = await client.get(
                    f"{settings.threat_intel_url}/api/report"
                )
                full_resp.raise_for_status()
                full_report: dict = full_resp.json()
            except Exception as exc:
                logger.warning("Could not fetch full threat-intel report: %s", exc)
                full_report = {}

        # Build lookup: ip → full enrichment entry
        full_blocked  = {e["ip"]: e for e in full_report.get("blocked_ips", [])}
        full_outbound = {e["ip"]: e for e in full_report.get("outbound_ips", [])}
        narrative_text = (
            full_report.get("narrative", {}).get("executive_summary", "")
        )

        def _build_entry(flat: dict, direction: str, full_lookup: dict) -> dict | None:
            ip    = flat.get("ip", "")
            score = flat.get("score", 0)
            is_bad = flat.get("is_known_bad_actor", False)

            if not ip or score < settings.auto_action_threshold or not is_bad:
                return None

            full_entry = full_lookup.get(ip, {})
            intel = full_entry.get("intel", {})

            # If full report is unavailable, reconstruct intel from flat fields
            if not intel:
                intel = {
                    "composite_score": score,
                    "is_known_bad_actor": is_bad,
                    "org": flat.get("org", ""),
                    "country": flat.get("country", ""),
                    "abuse_confidence_score": flat.get("abuse_score", 0),
                    "threat_level": flat.get("threat_level", "unknown"),
                    "pulse_count": flat.get("otx_pulses", 0),
                    "gn_classification": flat.get("greynoise", "unknown"),
                    "likely_false_positive": False,
                    "riot": False,
                }

            if intel.get("likely_false_positive"):
                logger.debug("Skipping likely FP: %s", ip)
                return None

            return {
                "ip": ip,
                "score": score,
                "direction": direction,
                "count": flat.get("events", 0),
                "intel": intel,
                "narrative": narrative_text,
            }

        for flat in blocked_flat:
            entry = _build_entry(flat, "inbound", full_blocked)
            if entry:
                qualifying.append(entry)

        for flat in outbound_flat:
            # Outbound: apply a higher threshold (conservative for home net)
            outbound_threshold = max(settings.auto_action_threshold, 85)
            if flat.get("score", 0) < outbound_threshold:
                continue
            entry = _build_entry(flat, "outbound", full_outbound)
            if entry:
                qualifying.append(entry)

    except Exception as exc:
        logger.error("Failed to fetch from threat-intel service: %s", exc)

    logger.info(
        "Poll: %d qualifying IPs found (threshold=%d)",
        len(qualifying),
        settings.auto_action_threshold,
    )
    return qualifying


# ---------------------------------------------------------------------------
# Per-IP session
# ---------------------------------------------------------------------------


async def process_ip(threat_data: dict[str, Any]) -> None:
    """Run a full automation session for one qualifying IP."""
    ip = threat_data["ip"]
    session_id = make_session_id(ip)

    # ---- Deduplication -----------------------------------------------
    if await is_ip_already_processed(ip):
        logger.debug("IP %s already processed recently; skipping", ip)
        return

    # In-memory check: don't create a second pending session for the same IP
    # (covers container-restart scenarios where Redis keys were wiped)
    already_pending = any(
        data.get("ip") == ip for data in state.pending_approvals.values()
    )
    if already_pending:
        logger.debug("IP %s already awaiting approval in memory; skipping", ip)
        return

    # ---- Rate limiting -----------------------------------------------
    if not await check_rate_limit():
        logger.warning(
            "Rate limit reached; skipping IP %s for this cycle", ip
        )
        m.automation_rate_limited_total.inc()
        m.automation_actions_total.labels(status="skipped").inc()
        return

    m.automation_qualifying_ips_total.inc()
    start_time = time.monotonic()
    logger.info("Starting automation session %s for IP %s", session_id, ip)

    # ---- Open GAIT audit session -------------------------------------
    session = None
    if trail.initialized:
        try:
            session = trail.open_session(ip, session_id)
        except Exception as exc:
            logger.error("Could not open GAIT audit session: %s", exc)

    def record(name: str, data: Any, as_text: bool = False) -> None:
        if session:
            try:
                session.record_turn(name, data, as_text=as_text)
            except Exception as exc:
                logger.warning("GAIT record_turn(%s) failed: %s", name, exc)

    try:
        # Turn 00: input -----------------------------------------------
        record("input", {
            "session_id": session_id,
            "ip": ip,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "threat_data": {k: v for k, v in threat_data.items() if k != "intel"},
            "intel_summary": {
                "composite_score": threat_data.get("score"),
                "threat_level": threat_data.get("intel", {}).get("threat_level"),
                "org": threat_data.get("intel", {}).get("org"),
            },
            "config_snapshot": {
                "auto_action_threshold": settings.auto_action_threshold,
                "auto_approve_threshold": settings.auto_approve_threshold,
                "dry_run": settings.dry_run,
                "block_ttl_hours": settings.block_ttl_hours,
                "max_actions_per_hour": settings.max_actions_per_hour,
            },
        })

        # Turn 01: baseline metrics ------------------------------------
        baseline = await capture_baseline(ip)
        record("baseline", baseline)

        # Enrich threat_data with block history before Claude sees it
        threat_data["block_count"] = await get_block_count(ip)

        # Turn 02: Claude prompt (record exact text for audit) ---------
        narrative = threat_data.get("narrative", "")
        prompt_text = build_action_prompt(ip, threat_data, baseline, narrative)
        record("claude_prompt", prompt_text, as_text=True)

        # Turn 03: Claude action proposal ------------------------------
        proposed = await propose_action(ip, threat_data, baseline, narrative)
        record("proposed_action", proposed)

        action_type = proposed.get("type", "no_action")
        logger.info(
            "Session %s: Claude proposed type=%s confidence=%s",
            session_id, action_type, proposed.get("confidence", "?"),
        )

        # ---- No action -----------------------------------------------
        if action_type != "pfblocker_add":
            record("decision", {
                "decision": "no_action",
                "reason": proposed.get("reason", "Claude returned no_action"),
            })
            m.automation_actions_total.labels(status="skipped").inc()
            await mark_ip_processed(ip, ttl_hours=2)
            if session:
                session.close("no_action", success=True)
            return

        # ---- Build the action object ---------------------------------
        pf_action = PfBlockerAction(
            action_type=action_type,
            target_list=proposed.get("target_list", PFBLOCKER_CUSTOM_LIST),
            value=proposed.get("value", f"{ip}/32"),
            reason=proposed.get("reason", "high composite threat score"),
            duration_hours=int(proposed.get("duration_hours", settings.block_ttl_hours)),
        )

        score = threat_data.get("score", 0)
        needs_approval = score < settings.auto_approve_threshold

        # ---- DRY-RUN: log everything, touch nothing ------------------
        if settings.dry_run:
            record("decision", {
                "decision": "dry_run",
                "would_need_approval": needs_approval,
                "action": pf_action.to_dict(),
            })
            dry_result = await execute_pfblocker_add(pf_action)  # returns immediately
            record("execution_result", dry_result)

            _update_state(
                session_id, ip, threat_data, proposed, dry_result, "dry_run"
            )
            await send_action_outcome(
                session_id, ip, success=True,
                outcome_message=(
                    f"Dry-run: would have added `{pf_action.value}` to "
                    f"`{pf_action.target_list}` "
                    f"(score={score}, duration={pf_action.duration_hours}h, "
                    f"would_need_approval={needs_approval})"
                ),
                dry_run=True,
            )
            m.automation_actions_total.labels(status="dry_run").inc()
            await mark_ip_processed(ip, ttl_hours=4)
            if session:
                session.close("dry_run", success=True)
            return

        # ---- LIVE: gate on approval or auto-approve ------------------
        if needs_approval:
            # Build the approval URL.  External callers need host:8002,
            # but the service references its own container name internally.
            approve_url = (
                f"http://automation-agent:8000/api/automation/approve/{session_id}"
            )
            notified = await send_action_proposal(
                session_id, ip, threat_data, proposed, approve_url
            )
            record("decision", {
                "decision": "pending_approval",
                "score": score,
                "auto_approve_threshold": settings.auto_approve_threshold,
                "discord_notified": notified,
                "approve_url": approve_url,
            })

            state.pending_approvals[session_id] = {
                "ip": ip,
                "threat_data": threat_data,
                "proposed_action": proposed,
                "pf_action": pf_action.to_dict(),
                "baseline": baseline,
                "session": None,   # can't serialise AuditSession; approval reopens
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=4)
                ).isoformat(),
            }
            m.automation_pending_approvals.set(len(state.pending_approvals))
            m.automation_actions_total.labels(status="pending").inc()
            _update_state(session_id, ip, threat_data, proposed, None, "pending")
            # Mark processed so subsequent poll cycles don't re-alert this IP
            # while it sits in the approval queue (TTL matches the 4h expiry above)
            await mark_ip_processed(ip, ttl_hours=4)
            # Leave session open — it will be re-opened by the approval endpoint
            return

        # ---- AUTO-APPROVE (score >= auto_approve_threshold) ----------
        record("decision", {
            "decision": "auto_approve",
            "score": score,
            "auto_approve_threshold": settings.auto_approve_threshold,
        })
        await execute_and_verify(
            session_id, ip, pf_action, baseline, threat_data, proposed, session
        )

    except Exception as exc:
        logger.exception("Session %s failed unexpectedly: %s", session_id, exc)
        m.automation_actions_total.labels(status="fail").inc()
        if session:
            session.close(f"exception: {exc}", success=False)

    finally:
        elapsed = time.monotonic() - start_time
        m.automation_session_duration_seconds.observe(elapsed)
        logger.info("Session %s finished in %.1fs", session_id, elapsed)


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------


async def poll_cycle() -> None:
    """One poll: fetch qualifying IPs, process each serially."""
    m.automation_last_poll_timestamp.set(time.time())

    if state.latest_report is None:
        state.latest_report = {"sessions": [], "last_poll": None}
    state.latest_report["last_poll"] = datetime.now(timezone.utc).isoformat()

    qualifying = await fetch_high_risk_ips()
    for threat in qualifying:
        try:
            await process_ip(threat)
        except Exception as exc:
            logger.exception(
                "Unhandled error processing IP %s: %s",
                threat.get("ip"),
                exc,
            )


def _job_wrapper() -> None:
    """Synchronous bridge for APScheduler background thread → async poll_cycle.

    Submits poll_cycle() to the uvicorn event loop via run_coroutine_threadsafe
    so all async code (Redis, httpx, etc.) runs on the same loop that created
    those clients. Never calls asyncio.run() which would spin up a second loop.
    """
    if _loop is None:
        logger.error("Event loop not captured; skipping poll")
        return
    future = asyncio.run_coroutine_threadsafe(poll_cycle(), _loop)
    try:
        future.result(timeout=max(settings.poll_interval_seconds - 30, 60))
    except Exception:
        logger.exception("Automation poll job raised at the top level")


# ---------------------------------------------------------------------------
# Scheduler startup
# ---------------------------------------------------------------------------


def start_scheduler(loop: asyncio.AbstractEventLoop) -> None:
    global _scheduler, _loop
    if _scheduler is not None:
        return
    _loop = loop

    # Initialise the GAIT audit repository
    try:
        trail.initialize()
    except Exception as exc:
        logger.error(
            "GAIT audit trail init failed (%s); sessions will not be git-committed",
            exc,
        )

    if not settings.poll_enabled:
        logger.info(
            "Automation poll DISABLED (POLL_ENABLED=false). "
            "Agent will only execute actions submitted via /api/automation/submit."
        )
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _job_wrapper,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="automation_poll",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Automation scheduler started (poll every %ds, threshold=%d, dry_run=%s)",
        settings.poll_interval_seconds,
        settings.auto_action_threshold,
        settings.dry_run,
    )

    # First poll after a short delay to let the threat-intel service warm up
    def _delayed_first_poll() -> None:
        time.sleep(45)
        _job_wrapper()

    threading.Thread(target=_delayed_first_poll, daemon=True, name="initial-poll").start()
