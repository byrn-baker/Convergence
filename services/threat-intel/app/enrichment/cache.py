"""Redis cache with 24-hour TTL for per-IP enrichment data."""
import json
import logging
from datetime import date
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None

IP_PREFIX = "threat-intel:ip:"
BUDGET_PREFIX = "threat-intel:budget:abuseipdb:"


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def get_ip(ip: str) -> Optional[dict[str, Any]]:
    try:
        r = await get_redis()
        raw = await r.get(f"{IP_PREFIX}{ip}")
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis get failed for %s: %s", ip, exc)
    return None


async def set_ip(ip: str, data: dict[str, Any]) -> None:
    try:
        r = await get_redis()
        await r.setex(f"{IP_PREFIX}{ip}", settings.cache_ttl_seconds, json.dumps(data))
    except Exception as exc:
        logger.warning("Redis set failed for %s: %s", ip, exc)


async def check_abuseipdb_budget() -> bool:
    """Return True if we have remaining AbuseIPDB quota for today."""
    key = f"{BUDGET_PREFIX}{date.today().isoformat()}"
    try:
        r = await get_redis()
        count = await r.get(key)
        return int(count or 0) < settings.abuseipdb_daily_budget
    except Exception as exc:
        logger.warning("Redis budget check failed: %s", exc)
        return True  # fail open


async def increment_abuseipdb_budget() -> None:
    key = f"{BUDGET_PREFIX}{date.today().isoformat()}"
    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)
        await pipe.execute()
    except Exception as exc:
        logger.warning("Redis budget increment failed: %s", exc)
