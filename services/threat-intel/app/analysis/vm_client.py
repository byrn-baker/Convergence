"""VictoriaMetrics query client."""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def query_instant(promql: str) -> list[dict[str, Any]]:
    """Execute an instant PromQL query; return list of result dicts."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.victoriametrics_url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("result", [])
    except Exception as exc:
        logger.warning("VictoriaMetrics query failed: %s — %s", promql, exc)
        return []


async def get_top_blocked_ips(n: int = 50, hours: int = 1) -> list[dict[str, Any]]:
    """Return top *n* blocked source IPs with their event counts."""
    query = (
        f"topk({n}, sum by (src_ip) "
        f"(increase(firewall_events_total{{action='block'}}[{hours}h])))"
    )
    results = await query_instant(query)
    out = []
    for r in results:
        ip = r.get("metric", {}).get("src_ip", "")
        count = float(r.get("value", [0, 0])[1])
        if ip:
            out.append({"ip": ip, "count": int(count), "direction": "in", "action": "block"})
    return out


async def get_top_outbound_ips(n: int = 20, hours: int = 1) -> list[dict[str, Any]]:
    """Return top *n* outbound destination IPs — exclude RFC1918."""
    query = (
        f"topk({n}, sum by (dst_ip) "
        f"(increase(firewall_events_total{{direction='out',action='pass'}}[{hours}h])))"
    )
    results = await query_instant(query)
    out = []
    for r in results:
        ip = r.get("metric", {}).get("dst_ip", "")
        count = float(r.get("value", [0, 0])[1])
        if ip and not _is_rfc1918(ip):
            out.append({"ip": ip, "count": int(count), "direction": "out", "action": "pass"})
    return out


async def get_outbound_sources(dst_ip: str, hours: int = 1, top_n: int = 5) -> list[str]:
    """Return source IPs generating outbound connections to *dst_ip*.

    NOTE: pfSense logs outbound traffic at the WAN interface after NAT, so src_ip is
    typically the pfSense WAN IP, not the original internal LAN host. To find the true
    internal source, check pfSense Diagnostics > States or enable LAN interface logging.

    Returns list of src_ips sorted by count; caller should distinguish WAN vs LAN IPs.
    """
    query = (
        f"topk({top_n}, sum by (src_ip) "
        f"(increase(firewall_events_total{{"
        f"direction='out',action='pass',dst_ip='{dst_ip}'"
        f"}}[{hours}h])))"
    )
    results = await query_instant(query)
    sources = []
    for r in results:
        src = r.get("metric", {}).get("src_ip", "")
        if src:
            sources.append(src)
    return sources


async def get_active_interfaces(hours: int = 1) -> list[str]:
    """Return a deduplicated list of pfSense interface names seen in firewall events."""
    query = f"count by (interface) (increase(firewall_events_total[{hours}h]) > 0)"
    results = await query_instant(query)
    interfaces = []
    for r in results:
        iface = r.get("metric", {}).get("interface", "")
        if iface:
            interfaces.append(iface)
    return sorted(interfaces)


def _is_rfc1918(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
