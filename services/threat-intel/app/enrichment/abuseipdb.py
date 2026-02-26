"""AbuseIPDB /v2/check enrichment client."""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.abuseipdb.com/api/v2/check"


async def query(ip: str) -> dict[str, Any]:
    """Return AbuseIPDB data for *ip*.  Returns empty dict on error/no key."""
    if not settings.abuseipdb_api_key:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                BASE_URL,
                headers={"Key": settings.abuseipdb_api_key, "Accept": "application/json"},
                params={"ipAddress": ip, "maxAgeInDays": 30},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "abuse_confidence_score": data.get("abuseConfidenceScore", 0),
                "country_code": data.get("countryCode", ""),
                "usage_type": data.get("usageType", ""),
                "isp": data.get("isp", ""),
                "domain": data.get("domain", ""),
                "total_reports": data.get("totalReports", 0),
            }
    except Exception as exc:
        logger.warning("AbuseIPDB query failed for %s: %s", ip, exc)
        return {}
