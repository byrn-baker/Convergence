"""LLM-powered action proposal generator.

Separate from the threat-intel narrative generator — this prompt is tighter,
more structured, and explicitly asks for ONE machine-parseable JSON action.

Supports two providers selected via the LLM_PROVIDER environment variable:
  - "anthropic" (default): uses the Anthropic API (Claude Haiku)
  - "ollama": uses a local/external Ollama instance via its OpenAI-compatible API

The LLM is instructed to:
  - Output exactly one proposed action (or "no_action" if criteria not met)
  - Include a human-readable reason grounded in the threat data
  - Respect safety rules (FP filter, RFC 1918 guard, CDN guard)
  - Prefer conservative /32 single-host blocks over wide CIDRs

The returned dict is committed to the GAIT audit trail verbatim so there is
a permanent record of what the LLM saw and what it decided.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Anthropic model (used when llm_provider == "anthropic")
# Switch to claude-sonnet-4-6 if richer reasoning is needed.
_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 800

# The firewall alias (or pfBlockerNG list) managed by this agent.
# Reads from settings so it stays in sync with PFSENSE_FIREWALL_ALIAS / PFBLOCKER_CUSTOM_LIST.
_PFBLOCKER_LIST = settings.pfsense_firewall_alias


async def _call_llm(prompt: str, max_tokens: int) -> tuple[str, int, int]:
    """Dispatch a single-turn prompt to the configured LLM provider.

    Returns (response_text, prompt_tokens, completion_tokens).
    Raises on connection/API errors — callers handle exceptions.
    """
    provider = settings.llm_provider

    if provider == "anthropic":
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=_ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text
        return text, message.usage.input_tokens, message.usage.output_tokens

    if provider == "ollama":
        import httpx
        # Use the native Ollama API (/api/chat) rather than the OpenAI-compat shim
        # because only the native endpoint honours think=false, which suppresses the
        # internal reasoning chain on Qwen3-family models so output goes to content.
        url = f"{settings.ollama_base_url}/api/chat"
        payload = {
            "model": settings.ollama_model,
            "think": False,
            "stream": False,
            "options": {"num_predict": max_tokens},
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=120.0) as http:
            resp = await http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = data["message"]["content"]
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        return text, prompt_tokens, completion_tokens

    raise RuntimeError(f"Unknown llm_provider: {provider!r}. Set LLM_PROVIDER=anthropic or ollama.")


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

    block_count = threat_data.get("block_count", 0)
    hourly_events = threat_data.get("count", 0)
    repeat_threshold = settings.repeat_offender_threshold
    high_volume_threshold = settings.high_volume_threshold

    # Classify the severity of repeat behaviour for Claude
    if block_count >= repeat_threshold:
        repeat_label = (
            f"⚠️ REPEAT OFFENDER — blocked {block_count} time(s) previously. "
            f"Consider recommending permanent block list addition."
        )
    elif block_count > 0:
        repeat_label = f"Previously blocked {block_count} time(s)."
    else:
        repeat_label = "First time seen by this agent."

    if hourly_events >= high_volume_threshold:
        volume_label = (
            f"⚠️ HIGH VOLUME — {hourly_events} events in the last hour. "
            f"Actively hammering the network. Consider recommending permanent block."
        )
    else:
        volume_label = f"{hourly_events} events in the last hour."

    baseline_metrics = json.dumps(baseline.get("metrics", {}), indent=2)
    narrative_excerpt = (narrative or "No narrative available.")[:600]

    return f"""You are a network security automation agent for a home/SOHO pfSense firewall.
Your task: propose ONE safe, reversible pfSense blocking action for a high-risk IP.

THREAT DATA:
  IP:              {ip}
  Direction:       {threat_data.get("direction", "unknown")} (inbound=WAN, outbound=LAN→internet)
  Events (1h):     {volume_label}
  Block history:   {repeat_label}
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

DURATION GUIDELINES (escalate based on history):
  - First sighting, high score: 24 hours
  - Borderline score: 12 hours
  - Persistent bad actor (pulses > 5, abuse > 70): 72 hours
  - Blocked {repeat_threshold}+ times previously OR {high_volume_threshold}+ events/hour:
      → Use 168 hours (7 days) AND include "recommend_permanent_block": true in notes

Respond ONLY with valid JSON (no markdown, no code fences):
{{
  "type": "pfblocker_add" | "no_action",
  "target_list": "{_PFBLOCKER_LIST}",
  "value": "x.x.x.x/32",
  "reason": "concise reason citing specific intel (score, pulses, org, block history)",
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
    provider = settings.llm_provider

    # Gate: skip if required credentials/config are missing
    if provider == "anthropic" and not settings.anthropic_api_key:
        logger.info("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY not set; returning no_action")
        return {
            "type": "no_action",
            "reason": "ANTHROPIC_API_KEY not set",
            "confidence": "none",
            "notes": "Configure ANTHROPIC_API_KEY to enable AI action proposals.",
        }
    if provider == "ollama" and not settings.ollama_base_url:
        logger.info("LLM_PROVIDER=ollama but OLLAMA_BASE_URL not set; returning no_action")
        return {
            "type": "no_action",
            "reason": "OLLAMA_BASE_URL not set",
            "confidence": "none",
            "notes": "Configure OLLAMA_BASE_URL to enable AI action proposals.",
        }

    model_name = _ANTHROPIC_MODEL if provider == "anthropic" else settings.ollama_model
    prompt = build_action_prompt(ip, threat_data, baseline, narrative)

    try:
        raw_text, prompt_tokens, completion_tokens = await _call_llm(prompt, _MAX_TOKENS)
        raw_text = raw_text.strip()
        logger.debug(
            "LLM action proposal (%s, %d chars): %s…",
            model_name,
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
        parsed["model"] = model_name
        parsed["provider"] = provider
        parsed["prompt_tokens"] = prompt_tokens
        parsed["completion_tokens"] = completion_tokens
        return parsed

    except json.JSONDecodeError as exc:
        logger.warning("LLM action response non-JSON (provider=%s): %s", provider, exc)
        return {
            "type": "no_action",
            "reason": "json_parse_error",
            "confidence": "none",
            "raw_response": raw_text if "raw_text" in dir() else "",
        }
    except Exception as exc:
        logger.warning("LLM action proposal failed (provider=%s): %s", provider, exc)
        return {
            "type": "no_action",
            "reason": str(exc),
            "confidence": "none",
        }
