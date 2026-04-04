"""Unified LLM client for the net-ops-team agents.

Supports three provider backends selected via LLM_PROVIDER env var:
  - "anthropic"  — Anthropic Messages API (native tool-use)
  - "ollama"     — Ollama native /api/chat (tool-use via OpenAI-compat format)
  - "openai"     — Any OpenAI-compatible API (OpenRouter, vLLM, LiteLLM, etc.)

Each agent defines its own _TOOLS list (Anthropic schema) and _SYSTEM_PROMPT.
This module translates tool schemas and message formats between providers so
agents remain provider-agnostic.

Fallback: if the primary provider fails (auth error, connection refused, rate
limit), the client automatically retries with the next configured provider.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from app.config import settings

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("llm_audit")

# Patterns to scrub from tool results before sending to the LLM.
# Matches common credential formats so they never leave the machine.
import re

_SCRUB_PATTERNS = [
    # API keys / tokens (generic long hex or base64 strings after key-like words)
    (re.compile(r'(Token|Bearer|Authorization|api[_-]?key|password|secret|PASS|KEY|TOKEN)(["\']?[:\s=]+["\']?)([A-Za-z0-9_\-./+=]{16,})', re.IGNORECASE), r'\1\2[REDACTED]'),
    # Anthropic keys
    (re.compile(r'sk-ant-[A-Za-z0-9_\-]{20,}'), '[REDACTED_ANTHROPIC_KEY]'),
    # Discord tokens
    (re.compile(r'[MN][A-Za-z0-9]{23,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}'), '[REDACTED_DISCORD_TOKEN]'),
    # Generic long secrets (40+ hex chars, like Nautobot tokens)
    (re.compile(r'\b[0-9a-f]{40,}\b'), '[REDACTED_HEX_TOKEN]'),
    # Env var name hints in error messages
    (re.compile(r'(PFSENSE_XMLRPC_PASS|PFSENSE_SSH_KEY_PATH|ANTHROPIC_API_KEY|NAUTOBOT_TOKEN|DISCORD_BOT_TOKEN|SWITCH_SSH_PASS|ABUSEIPDB_API_KEY|OTX_API_KEY|OPENAI_API_KEY)'), '[CREDENTIAL_REF]'),
]


def _sanitize_tool_result(text: str) -> str:
    """Remove credentials and secrets from tool output before sending to LLM."""
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Data types returned to agents (provider-agnostic)
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalised response from any provider."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use"


# ---------------------------------------------------------------------------
# Schema translation helpers
# ---------------------------------------------------------------------------

def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function-calling format."""
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _openai_tool_calls_to_generic(choices_message: dict) -> list[ToolCall]:
    """Extract tool calls from an OpenAI-format response message."""
    calls = []
    for tc in choices_message.get("tool_calls", []):
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=tc["id"], name=fn["name"], input=args))
    return calls


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _call_anthropic(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
) -> LLMResponse:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=tools,
        messages=messages,
    )

    text = None
    tool_calls = []
    for block in resp.content:
        if hasattr(block, "text") and block.text:
            text = block.text
        if block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

    stop = "tool_use" if resp.stop_reason == "tool_use" else "end_turn"
    return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop)


async def _call_openai_compat(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
    base_url: str,
    api_key: str,
) -> LLMResponse:
    """Call any OpenAI-compatible endpoint (Ollama, OpenRouter, vLLM, etc.)."""
    import httpx

    oai_tools = _anthropic_tools_to_openai(tools)

    # Build OpenAI-format messages
    oai_messages: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        role = m["role"]
        content = m.get("content")

        if role == "user" and isinstance(content, list):
            # Could be tool_result blocks (Anthropic format) — convert
            tool_results = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_result"]
            if tool_results:
                for tr in tool_results:
                    oai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": tr.get("content", ""),
                    })
                continue
            # Otherwise flatten to string
            oai_messages.append({"role": "user", "content": str(content)})

        elif role == "assistant" and isinstance(content, list):
            # Anthropic assistant content blocks — convert to OpenAI format
            text_parts = []
            tc_list = []
            for block in content:
                if hasattr(block, "type"):
                    # Anthropic SDK objects
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        tc_list.append({
                            "id": block.id,
                            "type": "function",
                            "function": {"name": block.name, "arguments": json.dumps(block.input)},
                        })
                elif isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tc_list.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {"name": block["name"], "arguments": json.dumps(block.get("input", {}))},
                        })
            msg: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                msg["content"] = "\n".join(text_parts)
            else:
                msg["content"] = ""
            if tc_list:
                msg["tool_calls"] = tc_list
            oai_messages.append(msg)
        else:
            oai_messages.append({"role": role, "content": content if isinstance(content, str) else str(content)})

    payload: dict[str, Any] = {
        "model": model,
        "messages": oai_messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if oai_tools:
        payload["tools"] = oai_tools

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    async with httpx.AsyncClient(timeout=180.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    msg = choice["message"]
    finish = choice.get("finish_reason", "stop")

    text = msg.get("content")
    tool_calls = _openai_tool_calls_to_generic(msg) if msg.get("tool_calls") else []
    stop = "tool_use" if (finish in ("tool_calls", "function_call") or tool_calls) else "end_turn"

    return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop)


# ---------------------------------------------------------------------------
# Provider resolution & fallback
# ---------------------------------------------------------------------------

def _get_provider_chain() -> list[str]:
    """Return ordered list of providers to try. Primary first, then fallbacks."""
    primary = settings.llm_provider
    all_providers = ["anthropic", "ollama", "openai"]
    chain = [primary] + [p for p in all_providers if p != primary]
    return chain


def _provider_available(provider: str) -> bool:
    if provider == "anthropic":
        return bool(settings.anthropic_api_key)
    if provider == "ollama":
        return bool(settings.ollama_base_url)
    if provider == "openai":
        return bool(getattr(settings, "openai_base_url", ""))
    return False


def _get_model_for_provider(provider: str) -> str:
    if provider == "anthropic":
        return settings.model
    if provider == "ollama":
        return settings.ollama_model
    if provider == "openai":
        return getattr(settings, "openai_model", settings.model)
    return settings.model


def _is_cloud_provider(provider: str) -> bool:
    """Return True if this provider sends data off-machine."""
    if provider == "anthropic":
        return True
    if provider == "openai":
        return True
    if provider == "ollama":
        model = settings.ollama_model
        return "cloud" in model.lower()
    return False


def _estimate_prompt_chars(system: str, messages: list[dict]) -> int:
    total = len(system)
    for m in messages:
        c = m.get("content", "")
        total += len(str(c))
    return total


async def _dispatch(
    provider: str,
    messages: list[dict],
    system: str,
    tools: list[dict],
    max_tokens: int,
    caller: str = "unknown",
) -> LLMResponse:
    model = _get_model_for_provider(provider)
    is_cloud = _is_cloud_provider(provider)
    prompt_chars = _estimate_prompt_chars(system, messages)
    t0 = time.monotonic()

    if provider == "anthropic":
        resp = await _call_anthropic(messages, system, tools, model, max_tokens)
    elif provider == "ollama":
        resp = await _call_openai_compat(
            messages, system, tools, model, max_tokens,
            base_url=settings.ollama_base_url,
            api_key="ollama",
        )
    elif provider == "openai":
        resp = await _call_openai_compat(
            messages, system, tools, model, max_tokens,
            base_url=getattr(settings, "openai_base_url", ""),
            api_key=getattr(settings, "openai_api_key", ""),
        )
    else:
        raise RuntimeError(f"Unknown provider: {provider}")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    tool_names = [tc.name for tc in resp.tool_calls] if resp.tool_calls else []

    audit_logger.info(
        "caller=%s provider=%s model=%s cloud=%s prompt_chars=%d "
        "tools_called=%s latency_ms=%d stop=%s",
        caller, provider, model, is_cloud, prompt_chars,
        tool_names or "none", elapsed_ms, resp.stop_reason,
    )

    return resp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat(
    messages: list[dict],
    system: str,
    tools: list[dict],
    max_tokens: int = 4096,
    caller: str = "unknown",
) -> LLMResponse:
    """Send a chat completion request with automatic provider fallback.

    Tries the primary provider first. On failure, falls back to the next
    available provider in the chain.
    """
    chain = _get_provider_chain()
    last_err = None

    for provider in chain:
        if not _provider_available(provider):
            continue
        try:
            resp = await _dispatch(
                provider, messages, system, tools, max_tokens, caller=caller,
            )
            return resp
        except Exception as exc:
            logger.warning("LLM provider %s failed: %s — trying next", provider, exc)
            last_err = exc

    if last_err:
        raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")
    raise RuntimeError(
        "No LLM provider configured. Set ANTHROPIC_API_KEY, OLLAMA_BASE_URL, or OPENAI_BASE_URL."
    )


async def run_agentic_loop(
    system: str,
    tools: list[dict],
    user_message: str,
    handle_tool_call: Callable[[str, dict, list], Awaitable[Any]],
    findings: list,
    max_tokens: int = 4096,
    max_iterations: int = 25,
    caller: str = "unknown",
) -> list:
    """Run a full tool-use agentic loop and return findings.

    This replaces the while-True loop that was duplicated in every agent.
    """
    messages = [{"role": "user", "content": user_message}]

    for _ in range(max_iterations):
        resp = await chat(messages, system, tools, max_tokens, caller=caller)

        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            break

        # Build assistant message in Anthropic content-block format
        # (the translation layer handles converting this for non-Anthropic providers)
        assistant_content: list[dict] = []
        if resp.text:
            assistant_content.append({"type": "text", "text": resp.text})
        for tc in resp.tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        messages.append({"role": "assistant", "content": assistant_content})

        # Execute tools and build results
        tool_results = []
        for tc in resp.tool_calls:
            result = await handle_tool_call(tc.name, tc.input, findings)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": _sanitize_tool_result(str(result)),
            })
        messages.append({"role": "user", "content": tool_results})

    return findings


async def run_agentic_question(
    system: str,
    tools: list[dict],
    question: str,
    handle_tool_call: Callable[[str, dict, list], Awaitable[Any]],
    max_tokens: int = 4096,
    max_iterations: int = 25,
    caller: str = "unknown",
) -> str:
    """Run an agentic loop for a user question and return the final text answer."""
    messages = [{"role": "user", "content": question}]
    findings: list = []

    for _ in range(max_iterations):
        resp = await chat(messages, system, tools, max_tokens, caller=caller)

        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            return (resp.text or "No response generated.")[:1800]

        assistant_content: list[dict] = []
        if resp.text:
            assistant_content.append({"type": "text", "text": resp.text})
        for tc in resp.tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for tc in resp.tool_calls:
            result = await handle_tool_call(tc.name, tc.input, findings)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": _sanitize_tool_result(str(result)),
            })
        messages.append({"role": "user", "content": tool_results})

    return "No response generated."
