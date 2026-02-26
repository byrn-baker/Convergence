"""Port risk analysis: Loki LogQL query + local JSON lookup."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_PORT_SERVICES: dict[str, dict[str, str]] | None = None


def _load_port_services() -> dict[str, dict[str, str]]:
    global _PORT_SERVICES
    if _PORT_SERVICES is None:
        path = os.path.join(settings.data_dir, "port_services.json")
        try:
            with open(path) as f:
                _PORT_SERVICES = json.load(f)
        except Exception as exc:
            logger.warning("Could not load port_services.json: %s", exc)
            _PORT_SERVICES = {}
    return _PORT_SERVICES


async def get_top_blocked_ports(hours: int = 1, limit: int = 20) -> list[dict[str, Any]]:
    """Query Loki for top blocked destination ports via filterlog CSV parsing.

    Loki label reality: only {job="syslog"} exists — log_type/action are NOT labels.
    We filter with line filters instead:
      |~ "filterlog"  — only pfSense firewall log lines
      |~ ",block,"    — only block actions (field [6] in filterlog CSV)

    Filterlog TCP/UDP CSV field layout (0-indexed):
      [6]  action   (block/pass)
      [16] proto    (tcp/udp/icmp)
      [18] src_ip
      [19] dst_ip
      [20] src_port
      [21] dst_port   ← we extract this

    Regexp: match `,tcp,<len>,<src>,<dst>,<sport>,<dport>,` to capture dst_port.
    ICMP lines have "request"/"reply" at [20] — they don't match the regexp and are skipped.
    """
    # Build the LogQL metric query
    logql = (
        f'sum by (dst_port) ('
        f'count_over_time('
        f'{{job="syslog"}}'
        f' |~ "filterlog"'
        f' |~ ",block,"'
        f' | regexp `,(?:tcp|udp),\\d+,[^,]+,[^,]+,\\d+,(?P<dst_port>\\d+),`'
        f'[{hours}h]))'
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.loki_url}/loki/api/v1/query",
                params={"query": logql, "limit": limit},
            )
            resp.raise_for_status()
            raw = resp.json()
            results = raw.get("data", {}).get("result", [])
            logger.debug("Loki port query returned %d series", len(results))
    except Exception as exc:
        logger.warning("Loki port query failed: %s", exc)
        results = []

    port_svc = _load_port_services()
    entries: list[dict[str, Any]] = []
    for r in results:
        port = r.get("metric", {}).get("dst_port", "")
        count = int(float(r.get("value", [0, 0])[1]))
        if not port:
            continue
        svc_info = port_svc.get(port, {})
        entries.append(
            {
                "port": port,
                "service": svc_info.get("service", "unknown"),
                "risk_level": svc_info.get("risk_level", "medium"),
                "count": count,
                "description": svc_info.get("description", ""),
            }
        )

    # Sort by count desc
    entries.sort(key=lambda x: x["count"], reverse=True)

    # Update Prometheus gauge
    import app.metrics as met
    for e in entries:
        met.threat_intel_port_event_count.labels(
            port=e["port"], port_service=e["service"], risk_level=e["risk_level"]
        ).set(e["count"])

    return entries
