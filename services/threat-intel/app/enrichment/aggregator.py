"""Combines results from the four threat-intel sources into a single enriched record."""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.enrichment import cache, abuseipdb, greynoise, otx, ipinfo
import app.metrics as m

logger = logging.getLogger(__name__)

# Known benign infrastructure orgs — these generate firewall hits from normal
# traffic (CDN edge nodes, DNS, cloud API endpoints, game servers, ISP infra).
# If an IP belongs to one of these AND has a low abuse score, it's not a threat.
_BENIGN_ORGS = {
    "google", "cloudflare", "amazon", "microsoft", "apple", "akamai",
    "fastly", "netflix", "roblox", "meta", "facebook", "twitter",
    "zoom", "dropbox", "github", "cdn", "icloud", "gstatic",
    "broadsoft", "charter", "comcast", "verizon", "at&t", "centurylink",
    "lumen", "level3", "cogent", "hurricane electric", "he.net",
    "conviva", "steam", "valve", "epic games", "riot games",
    "disney", "hulu", "spotify", "twitch", "youtube",
}


def _is_benign_org(org: str) -> bool:
    """Check if the org string matches a known benign infrastructure provider."""
    org_lower = org.lower()
    return any(b in org_lower for b in _BENIGN_ORGS)


def _compute_score(
    abuse_score: float,
    otx_pulses: int,
    gn_classification: str,
    is_riot: bool,
) -> float:
    """Composite 0-100 threat score per the plan spec."""
    if is_riot:
        return 0.0
    score = 0.0
    # 50% weight: AbuseIPDB
    score += min(abuse_score, 100) * 0.5
    # 30% weight: OTX (capped at 20 pulses = 30 points)
    score += min(otx_pulses, 20) / 20 * 30
    # 20% weight: GreyNoise
    if gn_classification == "malicious":
        score += 20
    elif gn_classification in ("noise", "unknown"):
        score += 5
    return round(min(score, 100), 1)


def _threat_level(score: float) -> str:
    if score < 10:
        return "none"
    elif score < 25:
        return "low"
    elif score < 50:
        return "medium"
    elif score < 75:
        return "high"
    return "critical"


def _is_outbound_c2(intel: dict[str, Any], direction: str) -> bool:
    """Detect likely C2/malicious outbound destinations.

    Tighter than before: requires multiple signals, not just one.
    Benign orgs are excluded even if they have OTX pulses (popular services
    get mentioned in threat reports without being threats themselves).
    """
    if direction != "out":
        return False
    if intel.get("riot", False):
        return False
    if _is_benign_org(intel.get("org", "")):
        return False

    abuse_score = intel.get("abuse_confidence_score", 0)
    otx_count = intel.get("pulse_count", 0)
    gn_cls = intel.get("gn_classification", "unknown")

    # Require strong evidence: high abuse + OTX presence, or confirmed malicious
    if gn_cls == "malicious":
        return True
    if abuse_score >= 50 and otx_count >= 3:
        return True
    if abuse_score >= 80:
        return True
    return False


async def enrich_ip(ip: str, direction: str, action: str, event_count: int) -> dict[str, Any]:
    """Return full enriched record for *ip*, using Redis cache when available."""
    # Check cache first
    cached = await cache.get_ip(ip)
    if cached:
        m.threat_intel_cache_hits_total.inc()
        record = cached
    else:
        # Query all sources concurrently via asyncio.gather
        import asyncio

        # AbuseIPDB has rate-limit guard
        can_query_abuse = await cache.check_abuseipdb_budget()

        abuse_task = abuseipdb.query(ip) if can_query_abuse else asyncio.sleep(0, result={})
        abuse_data, gn_data, otx_data, ipinfo_data = await asyncio.gather(
            abuse_task,
            greynoise.query(ip),
            otx.query(ip),
            ipinfo.query(ip),
        )

        if can_query_abuse and abuse_data:
            await cache.increment_abuseipdb_budget()

        abuse_score = float((abuse_data or {}).get("abuse_confidence_score", 0))
        pulse_count = int((otx_data or {}).get("pulse_count", 0))
        gn_cls = (gn_data or {}).get("classification", "unknown")
        is_riot = (gn_data or {}).get("riot", False)

        composite = _compute_score(abuse_score, pulse_count, gn_cls, is_riot)
        threat_level = _threat_level(composite)

        country = (ipinfo_data or {}).get("country") or (otx_data or {}).get("country", "")
        org = (ipinfo_data or {}).get("org", "")

        record = {
            "ip": ip,
            "country": country,
            "org": org,
            "classification": gn_cls,
            "composite_score": composite,
            "threat_level": threat_level,
            "abuse_confidence_score": abuse_score,
            "pulse_count": pulse_count,
            "gn_classification": gn_cls,
            "gn_name": (gn_data or {}).get("name", ""),
            "riot": is_riot,
        }
        await cache.set_ip(ip, record)

    # Derived fields that depend on direction
    org = record.get("org", "")
    composite = record.get("composite_score", 0)
    abuse = record.get("abuse_confidence_score", 0)
    is_riot = record.get("riot", False)
    is_benign = is_riot or _is_benign_org(org)

    # Known bad actor: requires composite >= 50 (high/critical threat level).
    # Benign infrastructure orgs are excluded unless abuse_score is very high,
    # which would indicate the IP is genuinely compromised or malicious despite
    # belonging to a legitimate org.
    if is_benign and abuse < 80:
        record["is_known_bad_actor"] = False
        record["likely_false_positive"] = True
    else:
        record["is_known_bad_actor"] = (
            composite >= 50
            or _is_outbound_c2(record, direction)
        )
        record["likely_false_positive"] = False

    # Update Prometheus metrics
    labels = {
        "ip": ip,
        "direction": direction,
        "country": record.get("country", ""),
        "org": org,
        "classification": record.get("classification", "unknown"),
    }
    m.threat_intel_ip_score.labels(**labels).set(composite)
    m.threat_intel_ip_event_count.labels(ip=ip, direction=direction, action=action).set(event_count)
    m.threat_intel_abuseipdb_score.labels(ip=ip, direction=direction).set(abuse)
    m.threat_intel_otx_pulses.labels(ip=ip, direction=direction).set(record.get("pulse_count", 0))

    gn_numeric = -1 if is_riot else {
        "malicious": 2, "unknown": 1, "benign": 0
    }.get(record.get("gn_classification", "unknown"), 1)
    m.threat_intel_greynoise_classification.labels(ip=ip, direction=direction).set(gn_numeric)
    m.threat_intel_known_bad_actor.labels(
        ip=ip, direction=direction, country=record.get("country", "")
    ).set(1 if record["is_known_bad_actor"] else 0)

    return record
