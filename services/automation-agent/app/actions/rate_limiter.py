"""Redis-backed rate limiter and IP deduplication for automation actions.

Uses two Redis data structures:
  1. Sorted set  automation:actions_this_hour  — sliding 60-min window counter
  2. String keys automation:processed:{ip}     — TTL-based deduplication

Both use Redis DB 1 (isolated from threat-intel's DB 0).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None
_RATE_KEY = "automation:actions_this_hour"
_PROC_PREFIX = "automation:processed:"
_BLOCK_COUNT_PREFIX = "automation:block_count:"
_BLOCK_COUNT_TTL = 365 * 24 * 3600  # 1 year — long enough to track persistent threats


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def check_rate_limit() -> bool:
    """Return True if the service is under the max_actions_per_hour cap.

    Uses a sliding-window sorted set: member = str(timestamp), score = timestamp.
    Members older than 60 minutes are removed before counting.
    """
    r = get_redis()
    now = int(time.time())
    window_start = now - 3600

    pipe = r.pipeline()
    pipe.zremrangebyscore(_RATE_KEY, 0, window_start)  # prune stale
    pipe.zcard(_RATE_KEY)                               # count remaining
    pipe.expire(_RATE_KEY, 7200)                        # safety TTL
    results = await pipe.execute()
    current_count = int(results[1])

    under_limit = current_count < settings.max_actions_per_hour
    if not under_limit:
        logger.warning(
            "Rate limit reached: %d/%d actions in the last hour",
            current_count,
            settings.max_actions_per_hour,
        )
    return under_limit


async def record_action_taken() -> None:
    """Increment the sliding-window counter after a live action is executed."""
    r = get_redis()
    now = int(time.time())
    # Use timestamp as both member and score so pruning is O(log N)
    await r.zadd(_RATE_KEY, {str(now): float(now)})
    await r.expire(_RATE_KEY, 7200)
    logger.debug("Rate limiter: recorded action at %d", now)


async def is_ip_already_processed(ip: str) -> bool:
    """Return True if this IP was actioned (or skipped) recently.

    Prevents the same IP from being re-evaluated on every poll cycle.
    TTL is set by mark_ip_processed() — typically 4h for no-action,
    block_ttl_hours for a live block.
    """
    r = get_redis()
    key = f"{_PROC_PREFIX}{ip}"
    return bool(await r.exists(key))


async def mark_ip_processed(ip: str, ttl_hours: int = 4) -> None:
    """Mark an IP as recently processed so subsequent polls skip it."""
    r = get_redis()
    key = f"{_PROC_PREFIX}{ip}"
    await r.set(key, "1", ex=ttl_hours * 3600)
    logger.debug("Marked IP %s as processed (TTL=%dh)", ip, ttl_hours)


async def get_block_count(ip: str) -> int:
    """Return the lifetime number of times this IP has been blocked by the agent."""
    r = get_redis()
    val = await r.get(f"{_BLOCK_COUNT_PREFIX}{ip}")
    return int(val) if val else 0


async def increment_block_count(ip: str) -> int:
    """Increment the lifetime block count for this IP and return the new total."""
    r = get_redis()
    key = f"{_BLOCK_COUNT_PREFIX}{ip}"
    count = await r.incr(key)
    await r.expire(key, _BLOCK_COUNT_TTL)
    logger.debug("Block count for %s incremented to %d", ip, count)
    return int(count)


async def get_rate_limit_status() -> dict:
    """Return current rate limiter state (for /health and dashboard)."""
    r = get_redis()
    now = int(time.time())
    window_start = now - 3600
    await r.zremrangebyscore(_RATE_KEY, 0, window_start)
    count = await r.zcard(_RATE_KEY)
    return {
        "actions_last_hour": int(count),
        "max_actions_per_hour": settings.max_actions_per_hour,
        "remaining": max(0, settings.max_actions_per_hour - int(count)),
        "window_seconds": 3600,
    }
