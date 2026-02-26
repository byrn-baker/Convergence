"""GreyNoise community API enrichment client."""
import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.greynoise.io/v3/community/{ip}"

# Community API rate limit: ~60 req/min unauthenticated.
# Semaphore limits concurrent GreyNoise calls to 3; sleep between calls avoids bursts.
_gn_semaphore = asyncio.Semaphore(3)
_GN_DELAY = 0.15  # seconds between GreyNoise requests

# Numeric mapping used for Prometheus gauge
CLASSIFICATION_MAP = {
    "malicious": 2,
    "unknown": 1,
    "benign": 0,
}


async def query(ip: str) -> dict[str, Any]:
    """Return GreyNoise community data for *ip*."""
    headers = {"Accept": "application/json"}
    if settings.greynoise_api_key:
        headers["key"] = settings.greynoise_api_key
    try:
        async with _gn_semaphore:
            await asyncio.sleep(_GN_DELAY)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(BASE_URL.format(ip=ip), headers=headers)
                if resp.status_code == 404:
                    # IP not seen by GreyNoise
                    return {"classification": "unknown", "noise": False, "riot": False, "name": ""}
                resp.raise_for_status()
                data = resp.json()
                classification = data.get("classification", "unknown")
                riot = data.get("riot", False)
                return {
                    "classification": "riot" if riot else classification,
                    "noise": data.get("noise", False),
                    "riot": riot,
                    "name": data.get("name", ""),
                    "classification_numeric": -1 if riot else CLASSIFICATION_MAP.get(classification, 1),
                }
    except Exception as exc:
        logger.warning("GreyNoise query failed for %s: %s", ip, exc)
        return {"classification": "unknown", "noise": False, "riot": False, "name": ""}
