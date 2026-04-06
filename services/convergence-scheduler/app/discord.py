from __future__ import annotations

import logging
import time

import httpx

from .config import settings

logger = logging.getLogger("convergence-scheduler")

_sent: dict[str, float] = {}


def _dedup_key(text: str) -> str:
    return text[:120]


async def post_finding(title: str, body: str, severity: str) -> None:
    key = _dedup_key(f"{severity}:{title}")
    now = time.time()
    if key in _sent and now - _sent[key] < settings.dedup_minutes * 60:
        return
    _sent[key] = now

    color = {"CRITICAL": 0xFF0000, "WARNING": 0xFFA500}.get(severity, 0x3498DB)
    embed = {"title": f"{'🔴' if severity == 'CRITICAL' else '🟡'} [{severity}] {title}", "description": body[:2000], "color": color}
    await _send({"embeds": [embed]})


async def post_skill_result(text: str) -> None:
    """Post a full skill response to Discord, chunked to fit the 4000-char embed limit."""
    # Extract skill name from the --- header if present
    title = "📊 Convergence Monitor"
    if text.startswith("--- "):
        first_line = text.split("\n", 1)[0]
        skill_name = first_line.strip("- ").strip()
        title = f"📊 {skill_name}"
        text = text.split("\n", 1)[1] if "\n" in text else ""

    text = text.strip()
    if not text:
        return

    # Send in chunks that fit Discord embed description limit
    for i in range(0, len(text), 3900):
        chunk = text[i:i + 3900]
        embed_title = title if i == 0 else f"{title} (cont.)"
        await _send({"embeds": [{"title": embed_title, "description": chunk, "color": 0x3498DB}]})


async def post_report(text: str) -> None:
    await _send({"embeds": [{"title": "📋 Convergence Shift Report", "description": text[:4000], "color": 0x3498DB}]})


async def _send(payload: dict) -> None:
    if not settings.discord_webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL not set — skipping notification")
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.discord_webhook_url, json=payload)
            resp.raise_for_status()
    except Exception as e:
        logger.error("Discord send failed: %s", e)
