"""AlienVault OTX enrichment client."""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://otx.alienvault.com/api/v1/indicators/IPv4/{ip}/general"


async def query(ip: str) -> dict[str, Any]:
    """Return OTX general indicator data for *ip*."""
    if not settings.otx_api_key:
        return {"pulse_count": 0}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                BASE_URL.format(ip=ip),
                headers={"X-OTX-API-KEY": settings.otx_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            pulse_info = data.get("pulse_info", {})
            return {
                "pulse_count": pulse_info.get("count", 0),
                "country": data.get("country_name", ""),
                "asn": data.get("asn", ""),
            }
    except Exception as exc:
        logger.warning("OTX query failed for %s: %s", ip, exc)
        return {"pulse_count": 0}
