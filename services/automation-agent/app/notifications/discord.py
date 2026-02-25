"""Discord webhook notifications for the automation agent.

Discord webhooks are one-directional — we send rich embeds but cannot
receive replies inline. The approval flow works like this:

  1. Agent proposes action → sends "approval required" embed with:
       - Full threat intelligence summary
       - Proposed pfSense action details
       - Link to POST /api/automation/approve/{session_id}

  2. Human operator reviews, then either:
       - Approves:  POST http://automation-agent:8002/api/automation/approve/{id}
       - Rejects:   DELETE same URL
       - Ignores:   session expires after 4 hours with no action

  3. Agent sends outcome embed (success / failure / dry-run) for every session.

Color coding:
  Orange  — needs human approval
  Blue    — dry-run logged (no live action)
  Green   — action executed successfully
  Red     — action failed or rolled back
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Discord embed color integers (decimal)
_COLOR_APPROVAL = 0xFFA500   # Orange
_COLOR_DRY_RUN  = 0x0099FF   # Blue
_COLOR_SUCCESS  = 0x00CC66   # Green
_COLOR_FAILURE  = 0xFF3333   # Red
_COLOR_INFO     = 0x808080   # Grey


async def _post_webhook(payload: dict) -> bool:
    """POST a JSON payload to the configured Discord webhook URL."""
    if not settings.discord_webhook_url:
        logger.debug("Discord webhook not configured; skipping notification")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.discord_webhook_url, json=payload)
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Discord webhook POST failed: %s", exc)
        return False


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


async def send_action_proposal(
    session_id: str,
    ip: str,
    threat_data: dict[str, Any],
    proposed_action: dict[str, Any],
    approve_url: str,
) -> bool:
    """Send an approval-required embed for a proposed pfSense action.

    Args:
        session_id:      Unique session ID (used for the approval URL).
        ip:              Target IP address.
        threat_data:     Full threat intel dict including 'intel' sub-dict.
        proposed_action: Claude's proposed action dict.
        approve_url:     Full URL to POST for human approval.

    Returns:
        True if the webhook was delivered successfully.
    """
    intel = threat_data.get("intel", {})
    score          = intel.get("composite_score", 0)
    org            = intel.get("org", "Unknown")
    country        = intel.get("country", "??")
    threat_level   = intel.get("threat_level", "unknown").upper()
    abuse_score    = intel.get("abuse_confidence_score", 0)
    otx_pulses     = intel.get("pulse_count", 0)
    direction      = threat_data.get("direction", "unknown")
    events         = threat_data.get("count", 0)
    block_count    = threat_data.get("block_count", 0)

    action_type    = proposed_action.get("type", "unknown")
    target_list    = proposed_action.get("target_list", "?")
    value          = proposed_action.get("value", ip)
    reason         = proposed_action.get("reason", "No reason provided")
    duration       = proposed_action.get("duration_hours", 24)
    confidence     = proposed_action.get("confidence", "?")

    reject_url = approve_url.replace("/approve/", "/approve/").rstrip("/")
    # Approval = POST, Rejection = DELETE to same URL

    # Build block history label — flag repeat offenders prominently
    if block_count >= settings.repeat_offender_threshold:
        block_history_label = (
            f"🔴 **{block_count}x** — REPEAT OFFENDER (consider permanent block)"
        )
    elif block_count >= settings.high_volume_threshold // 10:  # rough mid-tier
        block_history_label = f"🟡 **{block_count}x** — seen before"
    elif block_count > 0:
        block_history_label = f"🟢 **{block_count}x** — blocked before"
    else:
        block_history_label = "🆕 First time seen"

    if events >= settings.high_volume_threshold:
        events_label = f"⚠️ **{events}** (high volume — consider permanent block)"
    else:
        events_label = str(events)

    bot_configured = bool(settings.discord_bot_token)
    if bot_configured:
        how_to = (
            f":white_check_mark: **To approve:** `/approve session_id:{session_id}`\n"
            f":x: **To reject:** `/reject session_id:{session_id}`\n"
            f":scroll: **List all pending:** `/pending`\n"
            ":clock1: **Auto-expires in 4 hours** with no action taken"
        )
    else:
        how_to = (
            f":white_check_mark: **To approve:** `POST {approve_url}`\n"
            f":x: **To reject:** `DELETE {approve_url}`\n"
            ":clock1: **Auto-expires in 4 hours** with no action taken\n"
            "_Tip: set `DISCORD_BOT_TOKEN` to enable `/approve` slash commands_"
        )

    embed = {
        "title": f"\u26a0\ufe0f Automation Approval Required \u2014 {ip}",
        "description": (
            "The automation agent has identified a **high-risk IP** and proposes "
            f"a pfSense blocking action.\n\n{how_to}"
        ),
        "color": _COLOR_APPROVAL,
        "timestamp": _ts(),
        "fields": [
            {"name": "IP Address",        "value": f"`{ip}`",              "inline": True},
            {"name": "Composite Score",   "value": f"**{score}/100**",     "inline": True},
            {"name": "Threat Level",      "value": threat_level,            "inline": True},
            {"name": "Organization",      "value": org or "—",             "inline": True},
            {"name": "Country",           "value": country,                 "inline": True},
            {"name": "Direction",         "value": direction,               "inline": True},
            {"name": "Events (1h)",       "value": events_label,            "inline": True},
            {"name": "Block History",     "value": block_history_label,     "inline": True},
            {"name": "AbuseIPDB Score",   "value": f"{abuse_score}%",       "inline": True},
            {"name": "OTX Pulses",        "value": str(otx_pulses),         "inline": True},
            {"name": "Proposed Action",   "value": f"`{action_type}`",      "inline": True},
            {"name": "Target List",       "value": f"`{target_list}`",      "inline": True},
            {"name": "Block Duration",    "value": f"{duration}h",          "inline": True},
            {"name": "AI Confidence",     "value": confidence,              "inline": True},
            {"name": "CIDR to Block",     "value": f"`{value}`",            "inline": False},
            {"name": "Reason",            "value": reason,                  "inline": False},
            {"name": "Session ID", "value": f"`{session_id}`", "inline": False},
        ],
        "footer": {"text": "Convergence AutoAgent \u2022 Phase 5 \u2022 Fail-closed"},
    }

    payload = {
        "username": "Convergence AutoAgent",
        "avatar_url": "https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/docs/assets/anthropic-logo.svg",
        "embeds": [embed],
    }

    success = await _post_webhook(payload)
    if success:
        logger.info(
            "Discord approval request sent for session %s (IP=%s score=%d)",
            session_id, ip, score,
        )
    return success


async def send_action_outcome(
    session_id: str,
    ip: str,
    success: bool,
    outcome_message: str,
    dry_run: bool = False,
) -> bool:
    """Send a completion embed for a finished automation session.

    Args:
        session_id:      Session identifier.
        ip:              IP address that was acted upon.
        success:         True if the action completed without error.
        outcome_message: Human-readable summary of what happened.
        dry_run:         True if this was a dry-run (no live pfSense change).
    """
    if dry_run:
        color = _COLOR_DRY_RUN
        icon  = "\U0001f535"   # blue circle
        title = f"{icon} Dry-Run Logged \u2014 {ip}"
    elif success:
        color = _COLOR_SUCCESS
        icon  = "\u2705"
        title = f"{icon} Action Completed \u2014 {ip}"
    else:
        color = _COLOR_FAILURE
        icon  = "\u274c"
        title = f"{icon} Action Failed \u2014 {ip}"

    embed = {
        "title": title,
        "description": outcome_message,
        "color": color,
        "timestamp": _ts(),
        "fields": [
            {"name": "Session ID", "value": f"`{session_id}`", "inline": True},
            {"name": "Dry Run",    "value": str(dry_run),       "inline": True},
            {"name": "Success",    "value": str(success),        "inline": True},
        ],
        "footer": {"text": "Convergence AutoAgent \u2022 Phase 5"},
    }

    payload = {
        "username": "Convergence AutoAgent",
        "embeds": [embed],
    }

    return await _post_webhook(payload)
