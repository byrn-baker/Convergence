"""IPInfo enrichment client."""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://ipinfo.io/{ip}"


async def query(ip: str) -> dict[str, Any]:
    """Return IPInfo data for *ip*."""
    params: dict[str, str] = {}
    if settings.ipinfo_token:
        params["token"] = settings.ipinfo_token
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                BASE_URL.format(ip=ip),
                params=params,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "country": data.get("country", ""),
                "org": data.get("org", ""),
                "city": data.get("city", ""),
                "region": data.get("region", ""),
                "hostname": data.get("hostname", ""),
            }
    except Exception as exc:
        logger.warning("IPInfo query failed for %s: %s", ip, exc)
        return {"country": "", "org": ""}
