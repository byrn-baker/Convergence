"""Anthropic Claude client for generating threat narratives."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 2000

# Well-known benign infrastructure organisations — likely false positives even with threat scores
_BENIGN_ORGS = {
    "google", "cloudflare", "amazon", "microsoft", "apple", "akamai",
    "fastly", "netflix", "roblox", "meta", "facebook", "twitter",
    "zoom", "dropbox", "github", "cdn", "icloud", "gstatic",
    "broadsoft", "charter", "comcast", "verizon", "at&t",
}


def _is_likely_fp(intel: dict) -> bool:
    """Heuristic: RIOT flag or well-known infrastructure org suggests false positive."""
    if intel.get("riot"):
        return True
    org = intel.get("org", "").lower()
    return any(b in org for b in _BENIGN_ORGS)


def _build_prompt(report_data: dict[str, Any], interfaces: list[str]) -> str:
    summary = report_data.get("summary", {})
    blocked = report_data.get("blocked_ips", [])[:15]
    outbound = report_data.get("outbound_ips", [])
    ports = report_data.get("port_analysis", {}).get("top_blocked_ports", [])[:10]

    # --- Inbound blocked IPs: include org, score, RIOT flag, and FP hint ---
    top_blocked_list = []
    for e in blocked:
        intel = e.get("intel", {})
        fp = _is_likely_fp(intel)
        top_blocked_list.append({
            "ip": e["ip"],
            "count": e["count"],
            "country": intel.get("country", ""),
            "org": intel.get("org", ""),
            "asn": intel.get("org", "").split(" ")[0] if intel.get("org") else "",
            "score": intel.get("composite_score", 0),
            "threat_level": intel.get("threat_level", "none"),
            "greynoise": intel.get("gn_classification", "unknown"),
            "abuse_score": intel.get("abuse_confidence_score", 0),
            "otx_pulses": intel.get("pulse_count", 0),
            "riot": intel.get("riot", False),
            "likely_false_positive": fp,
        })

    # --- Outbound: ALL destinations, highlight bad actors ---
    # Note: pfSense NAT means src_ips from VM are typically the WAN IP, not internal hosts.
    # True internal source tracking requires Diagnostics > States on the pfSense appliance.
    outbound_list = []
    for e in outbound:
        intel = e.get("intel", {})
        fp = _is_likely_fp(intel)
        outbound_list.append({
            "ip": e["ip"],
            "count": e["count"],
            "org": intel.get("org", ""),
            "asn": intel.get("org", "").split(" ")[0] if intel.get("org") else "",
            "country": intel.get("country", ""),
            "score": intel.get("composite_score", 0),
            "threat_level": intel.get("threat_level", "none"),
            "is_known_bad_actor": intel.get("is_known_bad_actor", False),
            "abuse_score": intel.get("abuse_confidence_score", 0),
            "otx_pulses": intel.get("pulse_count", 0),
            "likely_false_positive": fp,
        })

    port_list = [
        {"port": p["port"], "service": p["service"], "risk": p["risk_level"], "count": p["count"]}
        for p in ports
    ]

    # --- Interface context ---
    iface_note = ""
    if interfaces:
        iface_note = f"\nACTIVE PFSENSE INTERFACES: {', '.join(interfaces)}"

    suspicious_outbound = [o for o in outbound_list if o["is_known_bad_actor"]]

    return f"""You are a network security analyst for a home/small-office pfSense firewall.
Analyze this 1-hour firewall telemetry and generate a threat assessment with pfSense-specific remediation steps.{iface_note}

FIREWALL CONTEXT:
- pfSense firewall with pfBlockerNG available for IP/ASN/CIDR blocking
- Inbound blocks = WAN interface, direction in
- Outbound suspicious = LAN interface, direction out
- pfSense blocks IPs via: Firewall > Rules (single IP) or pfBlockerNG (ranges/ASNs/GeoIP)

SUMMARY:
- Total blocked IPs: {summary.get('total_blocked_ips', 0)}
- Known bad actors (inbound): {summary.get('known_bad_actors_inbound', 0)}
- Known bad actors (outbound): {summary.get('known_bad_actors_outbound', 0)}
- Critical ports targeted: {summary.get('critical_ports_targeted', 0)}
- Overall risk level: {summary.get('overall_risk_level', 'unknown')}

TOP BLOCKED INBOUND IPs (sorted by event count):
{json.dumps(top_blocked_list, indent=2)}

ALL OUTBOUND DESTINATIONS:
{json.dumps(outbound_list, indent=2)}

SUSPICIOUS OUTBOUND (known bad actors only):
{json.dumps(suspicious_outbound, indent=2)}

NOTE: pfSense NAT masks the internal source IP in WAN-level logs. To identify which internal
host is connecting to a suspicious destination, check pfSense Diagnostics > States and filter
by the destination IP. The recommended_actions should include this step for suspicious outbound.

TOP TARGETED PORTS:
{json.dumps(port_list, indent=2)}

INSTRUCTIONS:
1. top_threats: 3-5 specific threats. For each:
   - Name the IP, org/owner (e.g. "Roblox AS22697"), and why it is or isn't a real threat
   - For outbound: name the internal_sources (LAN IPs) generating the traffic
   - Flag likely_false_positive=true entries as "probable false positive — verify before blocking"
   - Include ASN and CIDR context (e.g. "entire AS50360 Tamatiya EOOD appears hostile")

2. recommended_actions: 3-5 pfSense-specific actions. For each:
   - Specify the exact pfSense UI path and interface (use real interface names from ACTIVE PFSENSE INTERFACES)
   - For single IPs: "Firewall > Rules > [INTERFACE] — add block rule for [IP], direction [in/out]"
   - For ASN ranges: "pfBlockerNG > IP > IPv4 — add custom CIDR list or import AS[NUMBER] feed; assign to [INTERFACE] inbound"
   - For suspicious outbound (source unknown due to NAT): "pfSense Diagnostics > States — filter by [DST_IP] to identify internal host; then Firewall > Rules > LAN — block source [INTERNAL_IP] to destination [DST_IP], direction out"
   - Do NOT recommend blocking known-benign orgs (Google, Apple, Microsoft, Roblox game servers, etc.) unless abuse_score > 50

Respond ONLY with valid JSON (no markdown, no code fences) in this exact structure:
{{
  "risk_level": "none|low|medium|high|critical",
  "executive_summary": "2-3 sentence summary of current threat landscape, noting any false positives in the data",
  "top_threats": ["threat 1 with org, IPs, and internal sources where applicable", "..."],
  "inbound_analysis": "1-2 sentences about inbound attack patterns and ASNs",
  "outbound_analysis": "1-2 sentences about outbound activity, naming internal LAN hosts and their destinations",
  "port_analysis": "1-2 sentences about port targeting (or 'No port data available' if empty)",
  "recommended_actions": ["pfSense-specific action 1", "pfSense-specific action 2", "..."]
}}"""


async def generate_narrative(
    report_data: dict[str, Any],
    interfaces: list[str] | None = None,
) -> dict[str, Any]:
    """Call Claude Haiku and return parsed narrative JSON."""
    if not settings.anthropic_api_key:
        logger.info("No Anthropic API key configured; skipping narrative generation")
        return {"available": False}

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        prompt = _build_prompt(report_data, interfaces or [])
        message = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()
        logger.debug("Claude raw response (%d chars): %s", len(raw_text), raw_text[:200])

        if not raw_text:
            logger.warning("Claude returned empty response (stop_reason=%s)", message.stop_reason)
            return {"available": False, "error": "empty_response"}

        # Strip markdown code fences if Claude wrapped JSON in them
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            inner = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            raw_text = inner.strip()

        parsed = json.loads(raw_text)
        parsed["available"] = True
        parsed["model"] = MODEL
        return parsed
    except json.JSONDecodeError as exc:
        logger.warning("Claude returned non-JSON response: %s", exc)
        return {"available": False, "error": "json_parse_error"}
    except Exception as exc:
        logger.warning("Claude narrative generation failed: %s", exc)
        return {"available": False, "error": str(exc)}
