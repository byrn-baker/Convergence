#!/usr/bin/env python3
"""Convergence MCP Server — exposes the Convergence security platform
to NetClaw via the Model Context Protocol (stdio JSON-RPC).

Tools: get_threat_intel_report, get_blocked_ips, get_outbound_suspicious,
       submit_block_action, get_pending_approvals, approve_block,
       get_netops_report, query_metrics, query_logs, investigate_host

Transport: stdio
"""

from __future__ import annotations

import json
import logging
import os
import sys
import re
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - convergence-mcp - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("convergence-mcp")

THREAT_INTEL_URL = os.getenv("THREAT_INTEL_URL", "http://threat-intel:8000")
AUTOMATION_AGENT_URL = os.getenv("AUTOMATION_AGENT_URL", "http://automation-agent:8000")
NET_OPS_TEAM_URL = os.getenv("NET_OPS_TEAM_URL", "")  # RETIRED — net-ops-team removed in Phase 10
VICTORIAMETRICS_URL = os.getenv("VICTORIAMETRICS_URL", "http://victoriametrics:8428")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
PFSENSE_HOST = os.getenv("PFSENSE_HOST", "")
PFSENSE_USER = os.getenv("PFSENSE_XMLRPC_USER", "admin")
PFSENSE_PASS = os.getenv("PFSENSE_XMLRPC_PASS", "")
NAUTOBOT_URL = os.getenv("NAUTOBOT_URL", "")
NAUTOBOT_TOKEN = os.getenv("NAUTOBOT_TOKEN", "")

HTTP_TIMEOUT = 15.0

mcp = FastMCP("convergence-mcp")


async def _exec_php_raw(php_code: str) -> str:
    """Execute PHP on pfSense via XML-RPC exec_php, return echo output."""
    from xml.etree import ElementTree as ET
    from xml.sax.saxutils import escape as xml_escape

    url = f"https://{PFSENSE_HOST}/xmlrpc.php"
    xml_body = (
        '<?xml version="1.0"?>'
        "<methodCall><methodName>pfsense.exec_php</methodName>"
        "<params><param><value><string>"
        f"{xml_escape(php_code)}"
        "</string></value></param></params></methodCall>"
    )
    async with httpx.AsyncClient(verify=False, timeout=20.0) as client:
        resp = await client.post(
            url, content=xml_body.encode(), headers={"Content-Type": "text/xml"},
            auth=(PFSENSE_USER, PFSENSE_PASS),
        )
    body = resp.text
    xml_start = body.find("<?xml")
    return body[:xml_start].strip() if xml_start >= 0 else ""


async def _get(url: str) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, verify=False) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


async def _post(url: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, verify=False) as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
        return r.json()


# ── Threat Intel ──────────────────────────────────────────────────────────

@mcp.tool()
async def get_threat_intel_report() -> str:
    """Get the full threat intelligence report with scored IPs, abuse data,
    and AI-generated narratives from the Convergence threat-intel service."""
    try:
        data = await _get(f"{THREAT_INTEL_URL}/api/report")
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_blocked_ips() -> str:
    """Get the top blocked IPs with threat scores from the Infinity datasource."""
    try:
        data = await _get(f"{THREAT_INTEL_URL}/api/infinity/blocked_ips")
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_outbound_suspicious() -> str:
    """Get suspicious outbound destinations detected by the threat-intel service."""
    try:
        data = await _get(f"{THREAT_INTEL_URL}/api/infinity/outbound_suspicious")
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Automation Agent ──────────────────────────────────────────────────────

@mcp.tool()
async def submit_block_action(ip: str, reason: str, score: int, direction: str = "inbound") -> str:
    """Submit an IP for blocking via the Convergence automation pipeline.
    Goes through dedup, rate limiting, LLM action proposal, approval, and GAIT audit trail."""
    try:
        data = await _post(
            f"{AUTOMATION_AGENT_URL}/api/automation/submit",
            {"ip": ip, "reason": reason, "score": score, "direction": direction, "submitted_by": "netclaw"},
        )
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_pending_approvals() -> str:
    """List pending block actions awaiting approval in the automation agent."""
    try:
        data = await _get(f"{AUTOMATION_AGENT_URL}/api/automation/pending")
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def approve_block(action_id: str) -> str:
    """Approve a pending block action by its ID."""
    try:
        data = await _post(f"{AUTOMATION_AGENT_URL}/api/automation/approve/{action_id}", {})
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── NET-OPS Team ──────────────────────────────────────────────────────────

@mcp.tool()
async def get_netops_report() -> str:
    """Get the latest NET-OPS team findings report. DEPRECATED: net-ops-team was retired in Phase 10.
    Use convergence-scheduler /api/v1/latest instead."""
    if not NET_OPS_TEAM_URL:
        return json.dumps({"error": "net-ops-team retired in Phase 10. Use convergence-scheduler /api/v1/latest"})
    try:
        data = await _get(f"{NET_OPS_TEAM_URL}/api/v1/report/latest")
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Metrics & Logs ────────────────────────────────────────────────────────

@mcp.tool()
async def query_metrics(promql: str, time_range: str = "5m") -> str:
    """Run a PromQL query against VictoriaMetrics and return current values."""
    try:
        data = await _get(f"{VICTORIAMETRICS_URL}/api/v1/query?query={promql}&time_range={time_range}")
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def query_logs(logql: str, since: str = "1h", limit: int = 100) -> str:
    """Run a LogQL query against Loki and return matching log lines."""
    try:
        # Convert since to nanosecond timestamp
        import time
        units = {"m": 60, "h": 3600, "d": 86400}
        multiplier = units.get(since[-1], 60)
        seconds = int(since[:-1]) * multiplier
        start_ns = int((time.time() - seconds) * 1e9)
        url = f"{LOKI_URL}/loki/api/v1/query_range?query={logql}&start={start_ns}&limit={limit}"
        data = await _get(url)
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Host Investigation ────────────────────────────────────────────────────

@mcp.tool()
async def investigate_host(ip: str) -> str:
    """Investigate an internal IP: DHCP lease, ARP entry, and Nautobot device record.
    Returns MAC address, hostname, switch port, and device inventory data."""
    result = {"ip": ip, "timestamp": datetime.now(timezone.utc).isoformat()}

    # pfSense DHCP + ARP via exec_php (not xmlrpc.client — system_get_dhcp_leases was removed in 25.11)
    if PFSENSE_HOST and PFSENSE_PASS:
        try:
            dhcp_php = r"""
$content = @file_get_contents('/var/dhcpd/var/db/dhcpd.leases');
$leases = [];
if ($content) {
    preg_match_all('/lease\s+([\d.]+)\s*\{([^}]+)\}/s', $content, $blocks, PREG_SET_ORDER);
    $seen = [];
    foreach (array_reverse($blocks) as $block) {
        $ip = $block[1]; if (isset($seen[$ip])) continue; $seen[$ip] = true;
        $body = $block[2]; $entry = ['ip' => $ip, 'mac' => '', 'hostname' => ''];
        if (preg_match('/hardware\s+ethernet\s+([\da-f:]+);/i', $body, $m)) $entry['mac'] = strtolower($m[1]);
        if (preg_match('/client-hostname\s+"([^"]+)";/', $body, $m)) $entry['hostname'] = $m[1];
        $leases[] = $entry;
    }
}
echo json_encode($leases);
"""
            arp_php = r"""
$entries = [];
exec('arp -an', $lines);
foreach ($lines as $line) {
    if (preg_match('/\(?(\d+\.\d+\.\d+\.\d+)\)?\s+at\s+([\da-f:]+)\s+on\s+(\S+)/i', $line, $m)) {
        $entries[] = ['ip' => $m[1], 'mac' => strtolower($m[2]), 'interface' => $m[3]];
    }
}
echo json_encode($entries);
"""
            leases = json.loads(await _exec_php_raw(dhcp_php) or "[]")
            for lease in leases:
                if isinstance(lease, dict) and lease.get("ip") == ip:
                    result["dhcp"] = lease
                    break
            arp = json.loads(await _exec_php_raw(arp_php) or "[]")
            for entry in arp:
                if isinstance(entry, dict) and entry.get("ip") == ip:
                    result["arp"] = entry
                    break
        except Exception as e:
            result["pfsense_error"] = str(e)

    # Nautobot lookup
    if NAUTOBOT_URL and NAUTOBOT_TOKEN:
        mac = result.get("dhcp", result.get("arp", {})).get("mac", "")
        if mac:
            result["mac"] = mac
            try:
                query = '{ ip_addresses(address: "%s") { address host { name } interfaces { name device { name } } } }' % ip
                async with httpx.AsyncClient(timeout=10, verify=False) as c:
                    r = await c.post(
                        f"{NAUTOBOT_URL}/api/graphql/",
                        json={"query": query},
                        headers={"Authorization": f"Token {NAUTOBOT_TOKEN}"},
                    )
                    if r.status_code == 200:
                        result["nautobot"] = r.json()
            except Exception as e:
                result["nautobot_error"] = str(e)

    return json.dumps(result, indent=2, default=str)


if __name__ == "__main__":
    logger.info("Starting Convergence MCP Server (stdio transport)")
    mcp.run(transport="stdio")
