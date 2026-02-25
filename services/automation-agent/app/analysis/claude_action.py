"""Claude-powered action proposal generator.

Separate from the threat-intel narrative generator — this prompt is tighter,
more structured, and explicitly asks for ONE machine-parseable JSON action.

Claude is instructed to:
  - Output exactly one proposed action (or "no_action" if criteria not met)
  - Include a human-readable reason grounded in the threat data
  - Respect safety rules (FP filter, RFC 1918 guard, CDN guard)
  - Prefer conservative /32 single-host blocks over wide CIDRs

The returned dict is committed to the GAIT audit trail verbatim so there is
a permanent record of what Claude saw and what it decided.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Use the same Haiku model as threat-intel to keep costs low.
# Switch to claude-sonnet-4-6 if richer reasoning is needed.
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 800

# The custom pfBlockerNG list managed by this agent.
# Must be created in pfBlockerNG > IP > IPv4 Custom Lists before enabling live mode.
_PFBLOCKER_LIST = "pfBlockerNG_AutoAgent_v4"


def build_action_prompt(
    ip: str,
    threat_data: dict[str, Any],
    baseline: dict[str, Any],
    narrative: str,
) -> str:
    """Build the action-proposal prompt. Exported for GAIT recording."""
    intel = threat_data.get("intel", {})

    # Flatten key fields for readability in the prompt
    prompt_intel = {
        "composite_score": intel.get("composite_score", 0),
        "threat_level": intel.get("threat_level", "none"),
        "is_known_bad_actor": intel.get("is_known_bad_actor", False),
        "likely_false_positive": intel.get("likely_false_positive", False),
        "org": intel.get("org", "Unknown"),
        "country": intel.get("country", "??"),
        "abuse_confidence_score": intel.get("abuse_confidence_score", 0),
        "pulse_count": intel.get("pulse_count", 0),
        "gn_classification": intel.get("gn_classification", "unknown"),
        "riot": intel.get("riot", False),
    }

    baseline_metrics = json.dumps(baseline.get("metrics", {}), indent=2)
    narrative_excerpt = (narrative or "No narrative available.")[:600]

    return f"""You are a network security automation agent for a home/SOHO pfSense firewall.
Your task: propose ONE safe, reversible pfSense blocking action for a high-risk IP.

THREAT DATA:
  IP:              {ip}
  Direction:       {threat_data.get("direction", "unknown")} (inbound=WAN, outbound=LAN→internet)
  Events (1h):     {threat_data.get("count", 0)}
  Intel:           {json.dumps(prompt_intel, indent=4)}

THREAT NARRATIVE (excerpt from threat-intel service):
{narrative_excerpt}

PRE-ACTION BASELINE METRICS (from VictoriaMetrics):
{baseline_metrics}

PFBLOCKER CONTEXT:
  Target list:     {_PFBLOCKER_LIST}
  Custom list path: /var/db/pfblockerng/custom/{_PFBLOCKER_LIST}.txt
  This is a HOME network — false positives impact real users.
  Prefer /32 (single host) unless the entire ASN/CIDR is clearly malicious.

SAFETY RULES (hard constraints — always apply):
  1. If likely_false_positive is true  → MUST output type: "no_action"
  2. If composite_score < {settings.auto_action_threshold}         → MUST output type: "no_action"
  3. Never block RFC 1918 private IPs (10.x, 172.16-31.x, 192.168.x)
  4. Never block known CDN/infrastructure orgs (Cloudflare, Akamai,
     Fastly, Google, Apple, Microsoft) UNLESS abuse_confidence_score > 80
  5. For outbound suspicious: only propose a block if composite_score > 85
     AND abuse_confidence_score > 60

DURATION GUIDELINES:
  - Persistent known bad actor (pulses > 5, abuse > 70): 72 hours
  - High score but first sighting: 24 hours
  - Borderline: 12 hours

Respond ONLY with valid JSON (no markdown, no code fences):
{{
  "type": "pfblocker_add" | "no_action",
  "target_list": "{_PFBLOCKER_LIST}",
  "value": "x.x.x.x/32",
  "reason": "concise reason citing specific intel (score, pulses, org)",
  "duration_hours": 24,
  "confidence": "high" | "medium" | "low",
  "notes": "any caveats or recommended follow-up steps"
}}"""


async def propose_action(
    ip: str,
    threat_data: dict[str, Any],
    baseline: dict[str, Any],
    narrative: str = "",
) -> dict[str, Any]:
    """Ask Claude to propose a structured action for a high-risk IP.

    Returns a dict that is always safe to inspect for "type" == "pfblocker_add".
    Falls back to {"type": "no_action"} on any error.
    """
    if not settings.anthropic_api_key:
        logger.info("No Anthropic API key configured; returning no_action")
        return {
            "type": "no_action",
            "reason": "ANTHROPIC_API_KEY not set",
            "confidence": "none",
            "notes": "Configure ANTHROPIC_API_KEY to enable AI action proposals.",
        }

    prompt = build_action_prompt(ip, threat_data, baseline, narrative)

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()
        logger.debug(
            "Claude action proposal (%d chars): %s…",
            len(raw_text),
            raw_text[:120],
        )

        if not raw_text:
            return {
                "type": "no_action",
                "reason": "empty_response",
                "confidence": "none",
            }

        # Strip optional markdown code fences
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            end = -1 if lines[-1].strip() == "```" else len(lines)
            raw_text = "\n".join(lines[1:end]).strip()

        parsed = json.loads(raw_text)
        parsed["model"] = _MODEL
        parsed["prompt_tokens"] = message.usage.input_tokens
        parsed["completion_tokens"] = message.usage.output_tokens
        return parsed

    except json.JSONDecodeError as exc:
        logger.warning("Claude action response non-JSON: %s", exc)
        return {
            "type": "no_action",
            "reason": "json_parse_error",
            "confidence": "none",
            "raw_response": raw_text if "raw_text" in dir() else "",
        }
    except Exception as exc:
        logger.warning("Claude action proposal failed: %s", exc)
        return {
            "type": "no_action",
            "reason": str(exc),
            "confidence": "none",
        }
