# Phase 8: Unified LLM Client, Multi-Provider Fallback, and Security Hardening

**Last Updated:** 2026-04-04
**Status:** Complete — All agents running on Ollama Cloud (qwen3-coder:480b) with automatic fallback, credential sanitization, and audit logging

### Changelog

| Date | Change |
|------|--------|
| 2026-04-04 | Reverted to Phase 7 commit (`d44786f`). Stashed prior WIP Ollama attempts. |
| 2026-04-04 | Created `llm_client.py` — unified LLM abstraction supporting Anthropic, Ollama (local + cloud), and any OpenAI-compatible API with automatic provider fallback. |
| 2026-04-04 | Removed direct `import anthropic` from all 6 net-ops-team agents + supervisor. Replaced ~475 lines of duplicated agentic loop code with calls to `run_agentic_loop()` and `run_agentic_question()`. |
| 2026-04-04 | Converted `netclaw/` from a manually cloned repo to a proper git submodule (`automateyournetwork/netclaw`). Created `docker/netclaw.Dockerfile` for reproducible builds. |
| 2026-04-04 | Fixed API path bugs: `security_engineer.py` calling `/api/v1/threats/summary` (404) → `/api/report`; both security agents calling `/api/v1/actions/pending` (404) → `/api/automation/pending`. |
| 2026-04-04 | Added `SWITCH_SSH_USER`/`SWITCH_SSH_PASS`/`SWITCH_SSH_ENABLE_PASS` to `.env` — SSH auth to switches was failing due to empty credentials. |
| 2026-04-04 | Tested with `qwen3.5:9b` (local, 12GB VRAM) → worked but limited reasoning. Switched to `qwen3-coder:480b-cloud` via Ollama Cloud → 12 findings including real infrastructure issues the 9b missed. |
| 2026-04-04 | Added credential sanitizer to `llm_client.py` — scrubs API keys, tokens, passwords, and credential env var names from all tool results before sending to the LLM. |
| 2026-04-04 | Added audit logging (`llm_audit` logger) — tracks caller agent, provider, model, cloud vs local, prompt size, latency, and tool calls for every LLM request. |
| 2026-04-04 | Locked down `.env` permissions from `664` to `600` (owner-only read/write). |
| 2026-04-04 | Added `config/netclaw/.gitignore` for runtime artifacts (sessions, backups, update-check). |

---

## Overview

Phase 8 solves three problems that emerged from Phase 7:

1. **Provider lock-in.** The net-ops-team agents were hardcoded to `import anthropic` with Anthropic's wire format for tool-use (content blocks, `tool_use`/`tool_result` types, `stop_reason`). Switching to any other LLM required rewriting every agent.

2. **No fallback.** If Anthropic was down or out of credits, every agent failed silently with 0 findings. There was no way to fall back to a local model or alternative provider.

3. **Credentials in LLM context.** Tool results (error messages, HTTP responses) could contain API tokens, passwords, and credential env var names. These were sent verbatim to the LLM — including cloud-hosted models.

---

## Architecture Change

```
Before (Phase 7):
  supervisor.py      ──import anthropic──► Anthropic API
  noc_officer.py     ──import anthropic──► Anthropic API
  network_engineer.py──import anthropic──► Anthropic API
  security_expert.py ──import anthropic──► Anthropic API
  security_engineer.py─import anthropic──► Anthropic API
  nas_engineer.py    ──import anthropic──► Anthropic API
  interface_reconciler.py─import anthropic──► Anthropic API

After (Phase 8):
  All agents ──► llm_client.py ─┬─► Ollama (local qwen3.5:9b)
                                ├─► Ollama Cloud (qwen3-coder:480b-cloud)
                                ├─► Anthropic API
                                └─► Any OpenAI-compatible API
                                
                    Automatic fallback: try primary → try next → try next
                    Credential sanitizer on all tool results
                    Audit log on every LLM call
```

---

## Files Created

| File | Purpose |
|------|---------|
| `services/net-ops-team/app/llm_client.py` | Unified LLM client with provider abstraction, fallback chain, credential sanitizer, and audit logging |
| `docker/netclaw.Dockerfile` | Dockerfile for building NetClaw from the git submodule |
| `config/netclaw/.gitignore` | Ignores runtime artifacts (agent sessions, backups, update-check) |
| `.gitmodules` | Git submodule registration for `netclaw/` |

## Files Modified

| File | Change |
|------|--------|
| `services/net-ops-team/app/config.py` | Added `llm_provider`, `ollama_base_url`, `ollama_model`, `openai_base_url`, `openai_api_key`, `openai_model` |
| `services/net-ops-team/app/team/supervisor.py` | Replaced `anthropic.AsyncAnthropic` with `llm_client.chat()` for routing |
| `services/net-ops-team/app/team/noc_officer.py` | Replaced agentic loop with `run_agentic_loop()` / `run_agentic_question()` |
| `services/net-ops-team/app/team/network_engineer.py` | Same pattern |
| `services/net-ops-team/app/team/security_expert.py` | Same pattern + fixed `/api/v1/actions/pending` → `/api/automation/pending` |
| `services/net-ops-team/app/team/security_engineer.py` | Same pattern + fixed `/api/v1/threats/summary` → `/api/report` and `/api/v1/actions/pending` → `/api/automation/pending` |
| `services/net-ops-team/app/team/nas_engineer.py` | Same pattern |
| `services/net-ops-team/app/team/interface_reconciler.py` | Same pattern |
| `services/net-ops-team/requirements.txt` | Added `openai>=1.57.0` |
| `docker-compose.yml` | Added `LLM_PROVIDER`, `OLLAMA_*`, `OPENAI_*` env vars to net-ops-team; added `build:` directive for netclaw submodule |
| `.env.example` | Documented `openai` provider option |
| `.gitignore` | Removed `netclaw/` (now tracked as submodule) |

---

## The Unified LLM Client

### Provider Support

| Provider | Config | Tool Calling | Notes |
|----------|--------|-------------|-------|
| `anthropic` | `ANTHROPIC_API_KEY` | Native Anthropic format | Content blocks, `tool_use`/`tool_result` types |
| `ollama` | `OLLAMA_BASE_URL` + `OLLAMA_MODEL` | OpenAI-compat `/v1/chat/completions` | Works with local models and `-cloud` models |
| `openai` | `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `OPENAI_MODEL` | Native OpenAI format | Works with OpenRouter, vLLM, LiteLLM, etc. |

### Automatic Fallback

The client tries providers in order: primary (from `LLM_PROVIDER`) → next available → next available. If Ollama returns a 429 rate limit, it tries Anthropic. If Anthropic has no credits, it tries the next. All failures are logged with the provider name and error.

### Schema Translation

Agents define tools in Anthropic's format (`name`, `description`, `input_schema`). The client translates to OpenAI function-calling format (`type: "function"`, `function.parameters`) when talking to Ollama or OpenAI-compat endpoints. Multi-turn tool-use conversations are translated bidirectionally — Anthropic content blocks ↔ OpenAI tool_calls/tool messages.

### Public API

```python
# Single chat completion with fallback
resp = await chat(messages, system, tools, max_tokens, caller="noc_officer")

# Full agentic tool-use loop (replaces the while-True pattern)
findings = await run_agentic_loop(
    system=_SYSTEM_PROMPT,
    tools=_TOOLS,
    user_message="Run your analysis.",
    handle_tool_call=_handle_tool_call,
    findings=[],
    caller="network_engineer",
)

# Agentic loop for Discord questions
answer = await run_agentic_question(
    system=_SYSTEM_PROMPT,
    tools=_TOOLS,
    question="What's plugged into port 24?",
    handle_tool_call=_handle_tool_call,
    caller="network_engineer",
)
```

---

## Credential Sanitizer

Every tool result passes through `_sanitize_tool_result()` before being sent to the LLM. This catches:

| Pattern | Example | Replacement |
|---------|---------|-------------|
| API tokens after keywords | `Token f7eb49a6f648...` | `Token [REDACTED]` |
| Anthropic keys | `sk-ant-api03-abc...` | `[REDACTED_ANTHROPIC_KEY]` |
| Discord bot tokens | `MTQ3NjI5NTcx...` | `[REDACTED_DISCORD_TOKEN]` |
| Long hex strings (40+ chars) | `f7eb49a6f6482796e3a54a5f8fbc155eb81ec0e2` | `[REDACTED_HEX_TOKEN]` |
| Credential env var names | `PFSENSE_XMLRPC_PASS` | `[CREDENTIAL_REF]` |
| Generic key/password values | `api_key: abcdef1234567890abcdef` | `api_key: [REDACTED]` |

**Not scrubbed** (the model needs these to reason correctly):
- Internal IP addresses (`192.168.3.2`)
- MAC addresses, interface names, hostnames
- Metric values, VLAN IDs, port numbers

---

## Audit Logging

Every LLM call is logged to the `llm_audit` logger:

```
caller=security_expert provider=ollama model=qwen3-coder:480b-cloud cloud=True
prompt_chars=12847 tools_called=['get_threat_intel', 'query_netflow'] latency_ms=3420 stop=tool_use
```

Fields:
- `caller` — which agent made the call
- `provider` — which backend handled it
- `model` — model name used
- `cloud` — whether data left the machine (True for Anthropic, OpenAI, and Ollama `-cloud` models)
- `prompt_chars` — total characters in system prompt + messages
- `tools_called` — tool names invoked by the LLM in this turn
- `latency_ms` — round-trip time for the LLM call

---

## NetClaw Git Submodule

NetClaw was previously a manually cloned copy of `automateyournetwork/netclaw` inside the project, gitignored, with its own `.git/` history. It's now a proper git submodule:

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>

# Update to latest upstream
git submodule update --remote netclaw

# Check pinned commit
git submodule status
```

The Dockerfile lives at `docker/netclaw.Dockerfile` (not inside the submodule) so the build recipe is controlled by Convergence, not upstream.

---

## Ollama Cloud Models

Ollama Cloud offloads model inference to Ollama's servers while using the same local Ollama API. Cloud models have a `-cloud` suffix:

```bash
# Pull a cloud model on your Ollama host
ollama pull qwen3-coder:480b-cloud

# Use it — same API, same code, no GPU needed
OLLAMA_MODEL=qwen3-coder:480b-cloud
```

### Local vs Cloud Model Quality (observed)

| Model | Findings | Escalations | Quality |
|-------|----------|-------------|---------|
| `qwen3.5:9b` (local) | 7 | 0 | Said "all healthy" when SNMP was broken. Generic recommendations. |
| `qwen3-coder:480b-cloud` | 12 | 8 | Found SNMP failures, SSH auth issues, missing monitoring infrastructure. Real actionable findings. |
| `qwen3-coder:480b-cloud` (after fixes) | 3 | 0 | All INFO — correctly identified everything as healthy after bugs were fixed. |

---

## Security Hardening

| Change | Impact |
|--------|--------|
| `.env` permissions `664` → `600` | Only the owner can read credentials |
| Credential sanitizer in `llm_client.py` | API keys, tokens, passwords never reach the LLM |
| Audit logging | Visibility into what data goes to cloud vs local |
| Fallback chain | If cloud is unavailable, falls back to local (no data leaves the machine) |

---

## Configuration

### Environment Variables (new in Phase 8)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `ollama`, or `openai` |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama instance URL |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Model tag (use `-cloud` suffix for Ollama Cloud) |
| `OPENAI_BASE_URL` | _(empty)_ | Any OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | _(empty)_ | API key for the OpenAI-compat endpoint |
| `OPENAI_MODEL` | _(empty)_ | Model name for the OpenAI-compat endpoint |
| `SWITCH_SSH_USER` | _(empty)_ | SSH username for Cisco switches |
| `SWITCH_SSH_PASS` | _(empty)_ | SSH password for Cisco switches |
| `SWITCH_SSH_ENABLE_PASS` | _(empty)_ | Enable password for Cisco switches |

### Switching Providers

```bash
# Use Ollama Cloud (480b model, offloaded to Ollama servers)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3-coder:480b-cloud

# Use local Ollama (runs on your GPU)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3.5:9b

# Use Anthropic
LLM_PROVIDER=anthropic

# Use OpenRouter or any OpenAI-compatible API
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api
OPENAI_API_KEY=sk-or-v1-...
OPENAI_MODEL=qwen/qwen3-30b-a3b
```

No rebuild needed — just change `.env` and `docker compose up -d --force-recreate net-ops-team`.

---

## Closed-Loop Threat Response

Phase 8 also closes the gap between threat detection and action. Previously, the security expert would find a high-risk IP and post a Discord recommendation saying "block this IP." A human had to read it, log into pfSense, and manually create the rule.

Now the security expert can act directly:

### submit_block_action tool

When the security expert identifies a high-confidence threat (composite_score >= 80, is_known_bad_actor=true), it calls `submit_block_action` which POSTs to the automation-agent's new `/api/automation/submit` endpoint. The IP goes through the full existing pipeline:

1. Deduplication check (Redis TTL — won't re-process recently handled IPs)
2. Rate limiting (MAX_ACTIONS_PER_HOUR sliding window)
3. LLM action proposal (structured JSON with block type, duration, confidence)
4. Approval gate (auto-approve if score >= AUTO_APPROVE_THRESHOLD, else Discord approval)
5. pfSense execution (XML-RPC alias add → filter_configure)
6. GAIT audit trail (every step committed to an immutable git branch)

The security expert still uses `recommend_action` for things that can't be automated: policy changes, service hardening, manual forensic analysis.

### investigate_host tool

When the security expert finds suspicious outbound traffic from an internal IP, it calls `investigate_host` instead of just reporting "investigate 192.168.100.130." The tool:

1. Queries pfSense DHCP leases — finds the MAC address and hostname
2. Queries pfSense ARP table — fallback if DHCP doesn't have it
3. Searches Nautobot interface inventory on both switches — finds which physical port the device is connected to

The security expert gets back: IP, MAC, hostname, switch name, port name, port description. It includes this in its finding so the human knows exactly what device is involved and where it's physically connected — no manual investigation needed.

### System Prompt Changes

The security expert's system prompt now explicitly instructs it to act:

```
ACTION PROTOCOL — when you find a threat, DO NOT just recommend blocking. Take action:
- For high-risk IPs: use submit_block_action to send the IP directly to the automation agent
- For suspicious internal hosts: use investigate_host to identify the device
- Use recommend_action ONLY for things that cannot be automated
```

### New Automation Agent Endpoint

`POST /api/automation/submit` — accepts block requests from the security agents:

```json
{
  "ip": "5.187.35.26",
  "reason": "High-confidence threat: abuse_score=95, 47 block events in 1h",
  "score": 92,
  "direction": "inbound",
  "intel": {"abuse_confidence_score": 95, "org": "...", "country": "BG"},
  "submitted_by": "security_expert"
}
```

The IP enters the same pipeline as scheduler-discovered threats — same dedup, same rate limits, same approval flow, same GAIT audit trail.
