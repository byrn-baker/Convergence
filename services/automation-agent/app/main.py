"""Convergence Automation Agent — FastAPI application.

Endpoints:
  GET  /health                          Service health + config summary
  GET  /metrics                         Prometheus metrics
  GET  /api/automation/report           Full session report (JSON)
  GET  /api/automation/pending          Pending human-approval sessions
  POST /api/automation/approve/{id}     Approve a pending session
  DEL  /api/automation/approve/{id}     Reject a pending session
  GET  /api/automation/audit            Recent GAIT branches summary
  POST /api/automation/setup-pfsense   Create alias + WAN block rule (idempotent)

  # Grafana Infinity datasource (always arrays)
  GET  /api/infinity/sessions           Recent sessions flat table
  GET  /api/infinity/pending            Pending approvals flat table
  GET  /api/infinity/audit              Audit trail branch list
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app import state
from app.actions.executor import execute_and_verify
from app.actions.pfblocker import PfBlockerAction, setup_pfsense_prereqs
from app.actions.rate_limiter import get_rate_limit_status
from app.audit.git_trail import trail
from app.config import settings
from app.notifications.discord_bot import start_bot, stop_bot
from app.scheduler import start_scheduler
import app.metrics as m

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_scheduler(asyncio.get_running_loop())
    await start_bot()
    yield
    await stop_bot()


app = FastAPI(
    title="Convergence Automation Agent",
    version="0.1.0",
    description=(
        "Phase 5 event-driven automation: polls threat-intel, proposes pfSense "
        "blocking actions via Claude, gates on human approval or auto-approves, "
        "and commits an immutable GAIT audit trail to git."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    rate = await get_rate_limit_status()
    return {
        "status": "ok",
        "dry_run": settings.dry_run,
        "audit_trail_initialized": trail.initialized,
        "pending_approvals": len(state.pending_approvals),
        "auto_action_threshold": settings.auto_action_threshold,
        "auto_approve_threshold": settings.auto_approve_threshold,
        "max_actions_per_hour": settings.max_actions_per_hour,
        "rate_limit": rate,
        "threat_intel_url": settings.threat_intel_url,
        "pfsense_configured": bool(settings.pfsense_host),
        "pfsense_api_configured": bool(settings.pfsense_api_key),
        "pfsense_firewall_alias": settings.pfsense_firewall_alias,
        "discord_configured": bool(settings.discord_webhook_url),
        "anthropic_configured": bool(settings.anthropic_api_key),
    }


@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/api/automation/report")
async def report():
    if not state.latest_report:
        return JSONResponse(
            {"error": "No report yet; first poll runs 45 s after startup"},
            status_code=503,
        )
    return state.latest_report


# ---------------------------------------------------------------------------
# Approval / rejection endpoints
# ---------------------------------------------------------------------------


@app.get("/api/automation/pending")
async def list_pending():
    """List all sessions currently awaiting human approval."""
    now = datetime.now(timezone.utc)
    active: dict[str, Any] = {}
    expired: list[str] = []

    for sid, data in list(state.pending_approvals.items()):
        raw_exp = data.get("expires_at", "")
        try:
            expires = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            expires = now  # treat malformed as expired

        if now > expires:
            expired.append(sid)
        else:
            active[sid] = {k: v for k, v in data.items() if k != "session"}

    for sid in expired:
        state.pending_approvals.pop(sid, None)
    m.automation_pending_approvals.set(len(state.pending_approvals))

    return {
        "pending_count": len(active),
        "expired_pruned": len(expired),
        "sessions": active,
    }


@app.post("/api/automation/approve/{session_id}")
async def approve_action(session_id: str):
    """Approve a pending automation session and trigger execution.

    The action executes in an asyncio background task so this endpoint
    returns immediately with a 202-style response.
    """
    pending = state.pending_approvals.pop(session_id, None)
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or already expired/acted",
        )
    m.automation_pending_approvals.set(len(state.pending_approvals))

    ip = pending["ip"]
    pa = pending["pf_action"]
    pf_action = PfBlockerAction(
        action_type=pa["type"],
        target_list=pa["target_list"],
        value=pa["value"],
        reason=pa["reason"],
        duration_hours=int(pa.get("duration_hours", settings.block_ttl_hours)),
    )

    # Re-open a GAIT session for the approved execution leg
    session = None
    if trail.initialized:
        try:
            session = trail.open_session(ip, f"{session_id}-approved")
            session.record_turn(
                "approval",
                {
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "approved_via": "api",
                    "original_session_id": session_id,
                },
            )
        except Exception as exc:
            logger.error("Could not open GAIT session for approval: %s", exc)

    asyncio.create_task(
        execute_and_verify(
            session_id,
            ip,
            pf_action,
            pending["baseline"],
            pending["threat_data"],
            pending["proposed_action"],
            session,
        )
    )

    logger.info("Session %s approved by human for IP %s", session_id, ip)
    return {
        "status": "approved",
        "session_id": session_id,
        "ip": ip,
        "action": pf_action.to_dict(),
        "message": "Execution started in background; check /api/automation/report for outcome.",
    }


@app.delete("/api/automation/approve/{session_id}")
async def reject_action(session_id: str):
    """Reject a pending session — no action is taken on pfSense."""
    pending = state.pending_approvals.pop(session_id, None)
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or already expired/acted",
        )
    m.automation_pending_approvals.set(len(state.pending_approvals))
    m.automation_actions_total.labels(status="skipped").inc()

    logger.info(
        "Session %s rejected by human for IP %s", session_id, pending["ip"]
    )
    return {
        "status": "rejected",
        "session_id": session_id,
        "ip": pending["ip"],
        "message": "No action will be taken.",
    }


# ---------------------------------------------------------------------------
# Audit trail endpoint
# ---------------------------------------------------------------------------


@app.get("/api/automation/audit")
async def audit_sessions():
    """Return a summary of recent GAIT audit branches."""
    if not trail.initialized:
        return {"error": "Audit trail not initialised", "sessions": []}
    return {
        "audit_repo_path": settings.audit_repo_path,
        "sessions": trail.list_sessions(limit=50),
    }


# ---------------------------------------------------------------------------
# pfSense one-time setup
# ---------------------------------------------------------------------------


@app.post("/api/automation/setup-pfsense")
async def setup_pfsense():
    """Create the firewall alias and WAN block rule in pfSense if they don't exist.

    Uses XML-RPC exec_php with PFSENSE_XMLRPC_PASS credentials — no API key needed.
    Safe to call multiple times (idempotent).

    Returns:
        alias: "created" | "exists" | "skipped"
        rule:  "created" | "exists" | "skipped"

    In DRY_RUN mode the call is a no-op and returns skipped for both.
    """
    result = await setup_pfsense_prereqs()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


# ---------------------------------------------------------------------------
# Block submission endpoint (called by convergence-scheduler via NetClaw)
# ---------------------------------------------------------------------------


@app.post("/api/automation/submit")
async def submit_block(request_data: dict):
    """Accept a block request from NetClaw or other automation sources.

    Runs the IP through the same pipeline as the scheduler: dedup check,
    rate limit, LLM proposal, approval gate, GAIT audit trail.

    Body: {"ip": "1.2.3.4", "reason": "...", "score": 95, "direction": "inbound",
           "intel": {...}, "submitted_by": "security_expert"}
    """
    ip = request_data.get("ip", "")
    if not ip:
        raise HTTPException(status_code=400, detail="Missing 'ip' field")

    threat_data = {
        "ip": ip,
        "score": request_data.get("score", 0),
        "direction": request_data.get("direction", "inbound"),
        "count": request_data.get("count", 0),
        "intel": request_data.get("intel", {}),
        "narrative": request_data.get("reason", ""),
    }

    from app.scheduler import process_ip
    asyncio.create_task(process_ip(threat_data))

    logger.info(
        "Block submission accepted for IP %s from %s (score=%s)",
        ip, request_data.get("submitted_by", "unknown"), threat_data["score"],
    )
    return {
        "status": "accepted",
        "ip": ip,
        "message": "IP submitted to automation pipeline. Check /api/automation/pending for status.",
    }


# ---------------------------------------------------------------------------
# Grafana Infinity datasource endpoints (always return arrays)
# ---------------------------------------------------------------------------


@app.get("/api/infinity/sessions")
async def infinity_sessions():
    """Recent automation sessions as a flat array."""
    if not state.latest_report:
        return []
    return state.latest_report.get("sessions", [])


@app.get("/api/infinity/pending")
async def infinity_pending():
    """Pending approvals as a flat array."""
    rows = []
    now = datetime.now(timezone.utc)
    for sid, data in state.pending_approvals.items():
        try:
            expires = datetime.fromisoformat(
                data["expires_at"].replace("Z", "+00:00")
            )
            if now > expires:
                continue
            remaining_min = int((expires - now).total_seconds() / 60)
        except Exception:
            remaining_min = -1

        rows.append(
            {
                "session_id": sid,
                "ip": data.get("ip", ""),
                "score": data.get("threat_data", {}).get("score", 0),
                "action_type": data.get("proposed_action", {}).get("type", ""),
                "value": data.get("proposed_action", {}).get("value", ""),
                "reason": data.get("proposed_action", {}).get("reason", ""),
                "confidence": data.get("proposed_action", {}).get("confidence", ""),
                "created_at": data.get("created_at", ""),
                "expires_at": data.get("expires_at", ""),
                "expires_in_minutes": remaining_min,
            }
        )
    return rows


@app.get("/api/infinity/audit")
async def infinity_audit():
    """GAIT audit branch list as a flat array."""
    if not trail.initialized:
        return []
    return trail.list_sessions(limit=100)
