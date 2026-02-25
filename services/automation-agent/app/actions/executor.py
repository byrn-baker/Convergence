"""Shared execution logic for live and approval-gated pfSense actions.

Exported as a standalone module so both the scheduler (auto-approve path) and
the FastAPI approval endpoint (human-gated path) can call execute_and_verify()
without importing across module boundaries.

Flow:
    execute_and_verify()
      → execute_pfblocker_add()      (apply change to pfSense)
      → asyncio.sleep(300)           (wait 5 min for propagation)
      → verify_action()              (re-query VictoriaMetrics)
      → rollback_pfblocker_add()     (on failure, attempt undo)
      → record metrics + GAIT turns  (always)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app import state
from app.actions.baseline import capture_baseline, verify_action
from app.actions.pfblocker import PfBlockerAction, execute_pfblocker_add, rollback_pfblocker_add
from app.actions.rate_limiter import record_action_taken, mark_ip_processed, increment_block_count
from app.config import settings
from app.notifications.discord import send_action_outcome
import app.metrics as m

logger = logging.getLogger(__name__)


def _record(session: Any, name: str, data: Any) -> None:
    """Safe wrapper: record a GAIT turn, swallowing errors."""
    if session is None:
        return
    try:
        session.record_turn(name, data)
    except Exception as exc:
        logger.warning("GAIT record_turn(%s) failed: %s", name, exc)


def _update_state(
    session_id: str,
    ip: str,
    threat_data: dict,
    proposed: dict,
    result: dict | None,
    status: str,
) -> None:
    """Append a session summary to the in-memory report."""
    if state.latest_report is None:
        state.latest_report = {"sessions": [], "last_poll": None}

    entry = {
        "session_id": session_id,
        "ip": ip,
        "score": threat_data.get("score", 0),
        "direction": threat_data.get("direction", "unknown"),
        "proposed_action_type": proposed.get("type", "unknown"),
        "value": proposed.get("value", ""),
        "reason": proposed.get("reason", ""),
        "confidence": proposed.get("confidence", ""),
        "status": status,
        "result_message": (result or {}).get("message", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    sessions: list = state.latest_report.setdefault("sessions", [])
    sessions.append(entry)
    # Cap to last 100 in memory
    state.latest_report["sessions"] = sessions[-100:]


async def execute_and_verify(
    session_id: str,
    ip: str,
    pf_action: PfBlockerAction,
    baseline: dict[str, Any],
    threat_data: dict[str, Any],
    proposed: dict[str, Any],
    session: Any,  # AuditSession | None
) -> None:
    """Apply a pfSense action, wait, verify, roll back on failure, and commit outcome.

    This is the terminal step of an automation session — called either directly
    by the scheduler (auto-approve) or by the /api/automation/approve endpoint
    (human-approved).

    Args:
        session_id:  Unique identifier for the GAIT audit session.
        ip:          IP being acted upon.
        pf_action:   Fully constructed PfBlockerAction to execute.
        baseline:    Pre-action VM metrics snapshot (from capture_baseline).
        threat_data: Original threat intelligence data for this IP.
        proposed:    Claude's raw action proposal dict.
        session:     Open AuditSession (or None if GAIT is unavailable).
    """
    # ------------------------------------------------------------------ execute
    logger.info(
        "Executing action for session %s: %s → list '%s'",
        session_id,
        pf_action.value,
        pf_action.target_list,
    )
    result = await execute_pfblocker_add(pf_action)
    _record(session, "execution_result", result)

    if not result.get("success"):
        logger.error(
            "Action execution FAILED for %s: %s — attempting rollback",
            ip,
            result.get("message"),
        )
        rollback_result = await rollback_pfblocker_add(pf_action)
        _record(session, "rollback_result", rollback_result)

        m.automation_actions_total.labels(status="fail").inc()
        _update_state(session_id, ip, threat_data, proposed, result, "fail")
        await send_action_outcome(
            session_id,
            ip,
            success=False,
            outcome_message=(
                f"Execution failed: {result.get('message')}. "
                f"Rollback attempted (dry_run={settings.dry_run})."
            ),
        )
        if session:
            session.close("execution_failed", success=False)
        return

    # ------------------------------------------------------------------ verify
    logger.info(
        "Action applied for %s; waiting %d s for pfBlockerNG propagation",
        ip,
        300,
    )
    await asyncio.sleep(300)  # 5 minutes for pfB list reload

    verification = await verify_action(ip, baseline, wait_minutes=5)
    _record(session, "verification", verification)

    effective = verification.get("action_appears_effective", True)
    if not effective:
        logger.warning(
            "Verification suggests action may not be effective for %s; "
            "review verification.json in audit branch %s",
            ip,
            getattr(session, "branch", "n/a"),
        )

    # ------------------------------------------------------------------ finish
    status = "success"
    _update_state(session_id, ip, threat_data, proposed, result, status)
    m.automation_actions_total.labels(status=status).inc()

    await record_action_taken()
    await mark_ip_processed(ip, ttl_hours=pf_action.duration_hours)
    total_blocks = await increment_block_count(ip)

    repeat_note = ""
    if total_blocks >= settings.repeat_offender_threshold:
        repeat_note = (
            f" — ⚠️ **{total_blocks}x blocked total** (repeat offender — "
            f"consider adding to a permanent block list)"
        )
    elif total_blocks > 1:
        repeat_note = f" — blocked {total_blocks}x total"

    outcome_msg = (
        f"Added `{pf_action.value}` to `{pf_action.target_list}` "
        f"(TTL={pf_action.duration_hours}h, dry_run={settings.dry_run}, "
        f"effective={effective}, session={session_id}){repeat_note}"
    )
    await send_action_outcome(session_id, ip, success=True, outcome_message=outcome_msg)

    if session:
        session.close("success", success=True)

    logger.info(
        "Session %s complete — %s added to %s, effective=%s",
        session_id,
        pf_action.value,
        pf_action.target_list,
        effective,
    )
