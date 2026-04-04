import httpx

from ..config import settings


async def query_logs(logql: str, limit: int = 100, since: str = "5m") -> list:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.loki_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "limit": limit,
                    "since": since,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            entries = []
            for stream in data.get("data", {}).get("result", []):
                for ts, line in stream.get("values", []):
                    entries.append({
                        "timestamp": ts,
                        "line": line,
                        "labels": stream.get("stream", {}),
                    })
            return entries
    except Exception as e:
        return [{"error": str(e), "logql": logql}]


async def get_recent_firewall_blocks(since: str = "5m") -> list:
    logql = '{job="syslog"} |= "filterlog" | action="block"'
    return await query_logs(logql, limit=100, since=since)


async def get_device_syslogs(device_name: str, since: str = "10m") -> list:
    logql = f'{{job="syslog", device="{device_name}"}}'
    return await query_logs(logql, limit=100, since=since)


async def query_netflow(ip_filter: str = "", since: str = "5m", limit: int = 100) -> list:
    """Query NetFlow records from Loki.

    ip_filter: optional IP address to filter on (matches src or dst)
    Returns flow records with src/dst IPs, ports, protocol, bytes, packets.
    Each record's raw JSON line contains all attributes from the OTEL netflow receiver.
    """
    base = '{job="netflow"}'
    if ip_filter:
        logql = f'{base} |= "{ip_filter}"'
    else:
        logql = base
    return await query_logs(logql, limit=limit, since=since)
