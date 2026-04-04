from typing import Optional

import httpx

from ..config import settings


async def query_instant(metric: str, time_range: str = "5m") -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.victoriametrics_url}/api/v1/query",
                params={"query": metric, "time": "now"},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e), "metric": metric}


async def query_range(metric: str, start: str, end: str, step: str = "60s") -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.victoriametrics_url}/api/v1/query_range",
                params={"query": metric, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e), "metric": metric}


async def get_device_uptime(device_name: str) -> Optional[float]:
    try:
        result = await query_instant(f'system_uptime_seconds{{device_name="{device_name}"}}')
        data = result.get("data", {})
        results = data.get("result", [])
        if results:
            return float(results[0]["value"][1])
        return None
    except Exception:
        return None


async def get_interface_errors(device_name: str) -> list:
    try:
        result = await query_instant(f'interface_in_errors_total{{device_name="{device_name}"}}')
        data = result.get("data", {})
        out = []
        for item in data.get("result", []):
            labels = item.get("metric", {})
            out.append({
                "interface": labels.get("interface", "unknown"),
                "count": float(item["value"][1]),
            })
        return out
    except Exception as e:
        return [{"error": str(e)}]


async def get_firewall_block_rate(minutes: int = 5) -> float:
    try:
        query = f'rate(firewall_events_total{{action="block"}}[{minutes}m])'
        result = await query_instant(query)
        data = result.get("data", {})
        results = data.get("result", [])
        if results:
            return float(results[0]["value"][1])
        return 0.0
    except Exception:
        return 0.0
