"""VictoriaMetrics baseline capture and post-action verification.

Captures a snapshot of key metrics for a given IP *before* any action is taken,
then re-queries after a wait period to measure the effect (or lack thereof).

Verification is intentionally informational — pfBlockerNG list propagation
can take several minutes, and some metrics (e.g. blocked events) may *decrease*
after a block is added because pfB drops at a higher level than pf logging.
The results are committed to the GAIT audit trail regardless.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# PromQL queries parameterised by IP.
# Using regex match because the IP may appear as a label value substring
# (pfSense logs sometimes include port in the field).
_QUERIES: dict[str, str] = {
    # Inbound blocks involving this IP as source
    "inbound_block_events": (
        'sum(increase(otelcol_pfsense_filterlog_total'
        '{{action="block",direction="in",src_ip=~".*{ip}.*"}}[{window}m])) or vector(0)'
    ),
    # Outbound events involving this IP as destination
    "outbound_pass_events": (
        'sum(increase(otelcol_pfsense_filterlog_total'
        '{{action="pass",direction="out",dst_ip=~".*{ip}.*"}}[{window}m])) or vector(0)'
    ),
    # Current threat-intel score published by the threat-intel service
    "threat_intel_score": 'threat_intel_ip_score{{ip="{ip}"}}',
    # Known-bad-actor flag (0/1 gauge)
    "known_bad_actor_flag": 'threat_intel_known_bad_actor{{ip="{ip}"}}',
}


async def _query_single(client: httpx.AsyncClient, query: str) -> float | None:
    """Execute one instant PromQL query and return the first scalar value."""
    try:
        resp = await client.get(
            f"{settings.victoriametrics_url}/api/v1/query",
            params={"query": query},
            timeout=10.0,
        )
        resp.raise_for_status()
        results = resp.json().get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
        return 0.0
    except Exception as exc:
        logger.warning("VM query failed (%s): %s", query[:60], exc)
        return None


async def capture_baseline(ip: str, lookback_minutes: int = 60) -> dict[str, Any]:
    """Capture pre-action metrics for a specific IP from VictoriaMetrics.

    Args:
        ip:               The IP address to query.
        lookback_minutes: Time window for rate/increase queries.

    Returns:
        A dict with 'ip', 'captured_at', 'lookback_minutes', and 'metrics'.
    """
    baseline: dict[str, Any] = {
        "ip": ip,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "lookback_minutes": lookback_minutes,
        "metrics": {},
    }

    async with httpx.AsyncClient() as client:
        for metric_name, query_template in _QUERIES.items():
            query = query_template.format(ip=ip, window=lookback_minutes)
            value = await _query_single(client, query)
            baseline["metrics"][metric_name] = value

    logger.info(
        "Baseline captured for %s: %s",
        ip,
        {k: v for k, v in baseline["metrics"].items() if v is not None},
    )
    return baseline


async def verify_action(
    ip: str,
    pre_baseline: dict[str, Any],
    wait_minutes: int = 5,
) -> dict[str, Any]:
    """Re-query metrics and compare against the pre-action baseline.

    Args:
        ip:           The IP that was acted on.
        pre_baseline: The dict returned by capture_baseline() before the action.
        wait_minutes: Lookback window for the post-action query.

    Returns:
        A verification dict including per-metric before/after comparison and
        an overall `action_appears_effective` boolean.
    """
    post = await capture_baseline(ip, lookback_minutes=wait_minutes)
    pre_metrics: dict[str, Any] = pre_baseline.get("metrics", {})
    post_metrics: dict[str, Any] = post.get("metrics", {})

    comparison: dict[str, Any] = {}
    reduced_count = 0
    comparable_count = 0

    for key in pre_metrics:
        pre_val = pre_metrics.get(key)
        post_val = post_metrics.get(key)

        if pre_val is not None and post_val is not None:
            comparable_count += 1
            if pre_val > 0:
                pct_change = ((post_val - pre_val) / pre_val) * 100
            else:
                pct_change = 0.0
            reduced = post_val < pre_val
            if reduced:
                reduced_count += 1
            comparison[key] = {
                "before": pre_val,
                "after": post_val,
                "pct_change": round(pct_change, 1),
                "reduced": reduced,
            }
        else:
            comparison[key] = {
                "before": pre_val,
                "after": post_val,
                "pct_change": None,
                "reduced": None,
            }

    # Heuristic: action looks effective if event counts went down or didn't rise
    inbound_before = pre_metrics.get("inbound_block_events") or 0
    inbound_after = post_metrics.get("inbound_block_events") or 0
    action_appears_effective = inbound_after <= inbound_before

    return {
        "ip": ip,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "wait_minutes": wait_minutes,
        "comparison": comparison,
        "action_appears_effective": action_appears_effective,
        "notes": (
            "Verification is informational. pfBlockerNG may take up to 5 min to propagate. "
            "A *decrease* in block events is expected when pfB drops traffic before pf logs it."
        ),
    }
