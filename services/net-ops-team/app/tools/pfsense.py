"""pfSense read-only data queries for the NET-OPS team agents.

Uses XML-RPC exec_php (same pattern as automation-agent/pfblocker.py) to query:
  - DHCP lease table: IP → MAC → hostname → interface
  - ARP table: IP → MAC → interface (for MAC-to-port correlation)

pfSense prepends PHP echo output before the XML-RPC envelope, so xmlrpc.client
cannot parse the response. We use httpx directly and strip the echo output before
the <?xml marker, exactly as the automation-agent does.
"""
from __future__ import annotations

import json
import logging
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_XMLRPC_TIMEOUT = 20.0


async def _exec_php(php_code: str) -> str:
    """Execute PHP on pfSense via XML-RPC exec_php; return the echo output.

    Raises RuntimeError on HTTP error, auth failure, or XML-RPC fault.
    Returns empty string if PHP produced no output.
    """
    if not settings.pfsense_host:
        raise RuntimeError("PFSENSE_HOST is not configured")
    if not settings.pfsense_xmlrpc_pass:
        raise RuntimeError("PFSENSE_XMLRPC_PASS is not configured")

    url = f"https://{settings.pfsense_host}/xmlrpc.php"
    xml_body = (
        '<?xml version="1.0"?>'
        '<methodCall>'
        '<methodName>pfsense.exec_php</methodName>'
        '<params><param>'
        f'<value><string>{xml_escape(php_code)}</string></value>'
        '</param></params>'
        '</methodCall>'
    )

    async with httpx.AsyncClient(
        verify=settings.pfsense_verify_ssl,
        timeout=_XMLRPC_TIMEOUT,
    ) as client:
        resp = await client.post(
            url,
            content=xml_body.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            auth=(settings.pfsense_xmlrpc_user, settings.pfsense_xmlrpc_pass),
        )

    if resp.status_code == 401:
        raise RuntimeError("Authentication failed — check PFSENSE_XMLRPC_USER / PFSENSE_XMLRPC_PASS")
    if not resp.is_success:
        raise RuntimeError(f"HTTP {resp.status_code} from pfSense xmlrpc.php: {resp.text[:200]}")

    body = resp.text
    xml_start = body.find("<?xml")
    if xml_start < 0:
        raise RuntimeError(f"No XML-RPC envelope in pfSense reply: {body[:200]!r}")

    echo_output = body[:xml_start].strip()
    xml_part = body[xml_start:]

    try:
        root = ET.fromstring(xml_part)
        if root.find(".//fault") is not None:
            code_val, msg_val = "?", "?"
            for member in root.findall(".//struct/member"):
                name = member.findtext("name", "")
                if name == "faultCode":
                    code_val = member.findtext("value/int", "?")
                elif name == "faultString":
                    msg_val = member.findtext("value/string", "?")
            raise RuntimeError(f"XML-RPC fault {code_val}: {msg_val}")
    except ET.ParseError as exc:
        raise RuntimeError(f"Invalid XML in pfSense response: {exc}") from exc

    return echo_output


async def get_dhcp_leases() -> list[dict]:
    """Return all active DHCP leases from pfSense.

    Reads /var/dhcpd/var/db/dhcpd.leases directly (ISC DHCP format) — works on
    all pfSense versions including pfSense+ where system_get_dhcp_leases() was removed.

    Each entry contains:
        ip         — assigned IP address
        mac        — client MAC address (lowercase, colon-separated)
        hostname   — client hostname (may be empty)
        state      — "active" or "expired"

    Returns [] if pfSense is unreachable or not configured.
    Returns [{"error": "..."}] on failure.
    """
    # Parse the ISC DHCP leases file directly — no pfSense-version-specific functions needed.
    # Each lease block looks like:
    #   lease 192.168.1.10 {
    #     starts 5 2026/01/01 12:00:00;
    #     ends 5 2026/01/01 13:00:00;
    #     binding state active;
    #     hardware ethernet aa:bb:cc:dd:ee:ff;
    #     client-hostname "mydevice";
    #   }
    php_code = r"""
$leases = [];
$content = @file_get_contents('/var/dhcpd/var/db/dhcpd.leases');
if ($content) {
    preg_match_all('/lease\s+([\d.]+)\s*\{([^}]+)\}/s', $content, $blocks, PREG_SET_ORDER);
    $seen = [];
    foreach (array_reverse($blocks) as $block) {
        $ip = $block[1];
        if (isset($seen[$ip])) continue;
        $seen[$ip] = true;
        $body = $block[2];
        $entry = ['ip' => $ip, 'mac' => '', 'hostname' => '', 'state' => 'unknown'];
        if (preg_match('/binding\s+state\s+(\w+);/', $body, $m)) $entry['state'] = $m[1];
        if (preg_match('/hardware\s+ethernet\s+([\da-f:]+);/i', $body, $m)) $entry['mac'] = strtolower($m[1]);
        if (preg_match('/client-hostname\s+"([^"]+)";/', $body, $m)) $entry['hostname'] = $m[1];
        $leases[] = $entry;
    }
}
echo json_encode($leases);
"""
    try:
        output = await _exec_php(php_code)
        if not output:
            return []
        return json.loads(output)
    except RuntimeError as exc:
        logger.warning("get_dhcp_leases failed: %s", exc)
        return [{"error": str(exc)}]
    except json.JSONDecodeError as exc:
        logger.warning("get_dhcp_leases: non-JSON output from pfSense: %s", exc)
        return [{"error": f"Non-JSON output: {exc}"}]
    except Exception as exc:
        logger.exception("get_dhcp_leases unexpected error")
        return [{"error": str(exc)}]


async def get_arp_table() -> list[dict]:
    """Return the ARP table from pfSense.

    Each entry contains:
        ip         — IP address
        mac        — MAC address (lowercase, colon-separated)
        interface  — pfSense interface name (e.g. "em0", "igb1")
        status     — ARP entry status: "permanent", "expires in Xs", etc.
        hostname   — resolved hostname if available (may be empty)

    Returns [] if pfSense is unreachable or not configured.
    Returns [{"error": "..."}] on failure.
    """
    # Use exec('arp -an') — works on all pfSense versions, no internal functions needed.
    # Output format: "? (192.168.1.1) at aa:bb:cc:dd:ee:ff on igb0 [ethernet]"
    php_code = r"""
$entries = [];
exec('arp -an', $lines);
foreach ($lines as $line) {
    if (preg_match('/\(?([\d.]+)\)?\s+at\s+([\da-f:]+)\s+on\s+(\S+)/i', $line, $m)) {
        $entries[] = ['ip' => $m[1], 'mac' => strtolower($m[2]), 'interface' => $m[3], 'hostname' => ''];
    }
}
echo json_encode($entries);
"""
    try:
        output = await _exec_php(php_code)
        if not output:
            return []
        raw = json.loads(output)
        entries = []
        if isinstance(raw, dict):
            items = raw.get("arp", [])
        else:
            items = raw
        for item in items:
            if not isinstance(item, dict):
                continue
            entries.append({
                "ip":        item.get("ip-address", item.get("ip", "")),
                "mac":       item.get("mac-address", item.get("mac", "")).lower(),
                "interface": item.get("interface", ""),
                "status":    item.get("expires", item.get("status", "")),
                "hostname":  item.get("hostname", ""),
            })
        return entries
    except RuntimeError as exc:
        logger.warning("get_arp_table failed: %s", exc)
        return [{"error": str(exc)}]
    except json.JSONDecodeError as exc:
        logger.warning("get_arp_table: non-JSON output from pfSense: %s", exc)
        return [{"error": f"Non-JSON output: {exc}"}]
    except Exception as exc:
        logger.exception("get_arp_table unexpected error")
        return [{"error": str(exc)}]


def build_mac_lookup(leases: list[dict], arp: list[dict]) -> dict[str, dict]:
    """Build a combined MAC → device info lookup from DHCP leases + ARP table.

    Returns dict keyed by lowercase MAC address:
        {
          "aa:bb:cc:dd:ee:ff": {
            "ip": "192.168.3.42",
            "hostname": "mydevice",
            "source": "dhcp"    # or "arp"
          }
        }

    DHCP entries are preferred over ARP-only entries (more stable hostname data).
    """
    lookup: dict[str, dict] = {}

    # Seed from ARP (lower confidence — no hostname usually)
    for entry in arp:
        if "error" in entry:
            continue
        mac = entry.get("mac", "").lower()
        if mac and mac != "ff:ff:ff:ff:ff:ff":
            lookup[mac] = {
                "ip": entry.get("ip", ""),
                "hostname": entry.get("hostname", ""),
                "source": "arp",
            }

    # Override with DHCP (higher confidence — has hostname)
    for lease in leases:
        if "error" in lease:
            continue
        mac = lease.get("mac", "").lower()
        if mac:
            lookup[mac] = {
                "ip": lease.get("ip", ""),
                "hostname": lease.get("hostname", ""),
                "source": "dhcp",
            }

    return lookup
