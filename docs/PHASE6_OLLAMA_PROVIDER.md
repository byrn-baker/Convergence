# Phase 6: Ollama LLM Provider Support

**Last Updated:** 2026-03-04
**Status:** Live — both services running with `qwen3.5:9b` via external Ollama instance

### Changelog

| Date | Change |
|------|--------|
| 2026-03-04 | Initial Phase 6 release. Ollama support added to both `threat-intel` and `automation-agent`. Discovered that Qwen3-family thinking models require the native `/api/chat` endpoint (not the OpenAI-compat shim) to honour `think: false`; switched Ollama path to `httpx` + native API. |

---

## Overview

Phase 6 adds **Ollama** as an alternative LLM backend for both the `threat-intel` narrative
generator and the `automation-agent` action proposer. Previously both services were hard-wired to
the Anthropic API (Claude Haiku). The provider is now selectable at runtime via a single
environment variable, and the rest of the codebase is provider-agnostic.

**Why Ollama?**
- Run entirely locally without an Anthropic API key or outbound traffic to Anthropic servers
- Use any model available in the Ollama library (Qwen, Llama, Mistral, Gemma, etc.)
- Lower latency for on-premises deployments where the Ollama host is on the same LAN

**Design constraint:** Ollama runs as an external instance (existing host machine, NAS, workstation)
— it is **not** containerised inside this stack. The container connects to it over the LAN.

---

## Architecture Change

```
Before (Phase 5):
  threat-intel  ──anthropic.AsyncAnthropic──► Anthropic API (claude-haiku-4-5)
  automation-agent ──anthropic.AsyncAnthropic──► Anthropic API (claude-haiku-4-5)

After (Phase 6):
  threat-intel  ─┬─ anthropic.AsyncAnthropic ──► Anthropic API   (LLM_PROVIDER=anthropic)
                 └─ httpx POST /api/chat ────► Ollama host:11434  (LLM_PROVIDER=ollama)

  automation-agent ─┬─ anthropic.AsyncAnthropic ──► Anthropic API   (LLM_PROVIDER=anthropic)
                    └─ httpx POST /api/chat ────► Ollama host:11434  (LLM_PROVIDER=ollama)
```

The Ollama path uses the **native `/api/chat` endpoint** (not the OpenAI-compatible
`/v1/chat/completions` shim). See [Implementation Notes](#implementation-notes) for why.

---

## Files Modified

### Both services

| File | Change |
|------|--------|
| `app/config.py` | Added `llm_provider`, `ollama_base_url`, `ollama_model` settings |
| `requirements.txt` | Added `openai>=1.57.0` (kept for future; Ollama path now uses `httpx`) |

### `services/threat-intel`

| File | Change |
|------|--------|
| `app/analysis/claude_client.py` | Added `_call_llm()` dispatcher; updated `generate_narrative()` gate check; added `"provider"` field to response dict |

### `services/automation-agent`

| File | Change |
|------|--------|
| `app/analysis/claude_action.py` | Added `_call_llm()` dispatcher; updated `propose_action()` gate check; added `"provider"` field; token counts flow through tuple return into GAIT audit |

### Stack-level

| File | Change |
|------|--------|
| `docker-compose.yml` | `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` env vars + `extra_hosts: host.docker.internal:host-gateway` on both services |
| `.env.example` | New Ollama config section with commented defaults |

---

## Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `ollama` |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Base URL of the Ollama instance. `host.docker.internal` resolves to the Docker host on Linux via `extra_hosts`. |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model tag as shown in `ollama list` |
| `ANTHROPIC_API_KEY` | _(empty)_ | Still required when `LLM_PROVIDER=anthropic` |

### `.env` example

```env
# Use Ollama instead of Anthropic
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://192.168.1.50:11434   # or http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
```

### Gate logic (both services)

Neither service will attempt an LLM call if the required config is absent:

```
LLM_PROVIDER=anthropic  →  skips if ANTHROPIC_API_KEY is empty
LLM_PROVIDER=ollama     →  skips if OLLAMA_BASE_URL is empty
```

On skip, `threat-intel` returns `{"narrative": {"available": false}}` and `automation-agent`
returns `{"type": "no_action", "reason": "..."}` — the rest of the pipeline continues normally.

---

## Setting Up Ollama

### 1. Install and start Ollama on your host

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Enable network binding (default is 127.0.0.1 only)
sudo systemctl edit ollama
```

Add to the systemd override:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### 2. Pull a model

```bash
# Recommended: Qwen3.5 9B — good reasoning, JSON-following, 6 GB VRAM
ollama pull qwen3.5:9b

# Lighter alternative for CPU-only hosts
ollama pull llama3.2:3b
```

### 3. Verify it's reachable from the Docker host

```bash
curl http://<ollama-host>:11434/api/tags
```

### 4. Update `.env` and restart

```bash
# Edit .env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://<ollama-host>:11434
OLLAMA_MODEL=qwen3.5:9b

# Recreate containers (restart alone won't pick up new env vars)
docker compose up -d --force-recreate threat-intel automation-agent
```

### 5. Confirm env vars loaded

```bash
docker compose exec threat-intel printenv | grep -E "LLM|OLLAMA"
```

### 6. Trigger a test enrichment

```bash
docker compose exec threat-intel python3 -c "
import asyncio
from app.scheduler import _run_enrichment
asyncio.run(_run_enrichment())
"
```

Then check the report:

```bash
curl -s http://localhost:8001/api/report | python3 -m json.tool | grep -E '"provider"|"model"|"available"|"risk_level"'
```

Expected output:

```json
"available": true,
"provider": "ollama",
"model": "qwen3.5:9b",
"risk_level": "high",
```

---

## Implementation Notes

### Why the native `/api/chat` endpoint, not `/v1/chat/completions`

Ollama's OpenAI-compatible shim (`/v1/chat/completions`) does **not** forward the `think` parameter
to the underlying model runtime. On thinking models (Qwen3-family, DeepSeek-R1, etc.) this means
the model consumes its entire `max_tokens` budget on an internal reasoning chain and returns an
empty `content` field — the actual answer never appears.

The native endpoint (`/api/chat`) honours `"think": false`, which completely suppresses the
reasoning chain so all output goes directly to `message.content`.

Concrete failure mode observed during testing:

```
# OpenAI-compat (/v1/chat/completions) — think parameter ignored
finish_reason: length
content:       ""           ← empty; 2000 tokens consumed by reasoning
reasoning:     "Thinking Process:\n\n..."

# Native (/api/chat) — think: false honoured
content:       '{\n  "risk_level": "high", ...'   ← full JSON answer
thinking:      ""
prompt_tokens: 4075, completion_tokens: 970
```

### `_call_llm()` dispatcher pattern

Both service files contain an identical async helper:

```python
async def _call_llm(prompt: str, max_tokens: int) -> tuple[str, int, int]:
    """Returns (response_text, prompt_tokens, completion_tokens)."""
    provider = settings.llm_provider

    if provider == "anthropic":
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=_ANTHROPIC_MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text, message.usage.input_tokens, message.usage.output_tokens

    if provider == "ollama":
        import httpx
        url = f"{settings.ollama_base_url}/api/chat"
        payload = {
            "model": settings.ollama_model,
            "think": False,        # suppress reasoning chain on thinking models
            "stream": False,
            "options": {"num_predict": max_tokens},
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=120.0) as http:
            resp = await http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return (
            data["message"]["content"],
            data.get("prompt_eval_count", 0),
            data.get("eval_count", 0),
        )

    raise RuntimeError(f"Unknown llm_provider: {provider!r}")
```

The tuple return keeps callers provider-agnostic. Token counts map directly:

| Field | Anthropic | Ollama native |
|-------|-----------|---------------|
| Prompt tokens | `message.usage.input_tokens` | `prompt_eval_count` |
| Completion tokens | `message.usage.output_tokens` | `eval_count` |

### GAIT audit trail

`automation-agent` records `prompt_tokens` and `completion_tokens` in the GAIT `proposed_action.json`
turn verbatim. These fields are provider-agnostic — both providers populate them the same way via
the tuple return. A `"provider"` field is also added so the audit record captures which backend
made the decision.

### `host.docker.internal` on Linux

Docker Desktop automatically resolves `host.docker.internal` to the Docker host. On Linux with the
Docker Engine (no Desktop), it requires an explicit mapping:

```yaml
# docker-compose.yml — added to both threat-intel and automation-agent
extra_hosts:
  - "host.docker.internal:host-gateway"
```

This is already in place. If you point `OLLAMA_BASE_URL` at a static LAN IP instead
(e.g. `http://192.168.1.50:11434`), the `extra_hosts` entry is harmless but unnecessary.

---

## Model Recommendations

| Model | Size | VRAM | Notes |
|-------|------|------|-------|
| `qwen3.5:9b` | 9.7B Q4 | ~6 GB | Strong JSON adherence, fast on modern GPUs. **Tested and confirmed working.** Requires `think: false` via native API. |
| `qwen3-coder:30b` | 30.5B Q4 | ~20 GB | Higher quality reasoning; slower. Same `think: false` requirement. |
| `llama3.2:3b` | 3B | ~2 GB | Default in config. Good for CPU-only hosts. No thinking mode — works with both endpoints. |
| `llama3.1:8b` | 8B | ~5 GB | Good balance of quality and speed on CPU/GPU. |
| `mistral:7b` | 7B | ~4 GB | Reliable JSON output, no thinking mode. |

**Tip:** The prompts in both services explicitly instruct the model to output only valid JSON with
no markdown fences. Models with strong instruction-following (Qwen3, Llama 3.x) work best.

---

## Switching Between Providers

No rebuild is needed — the provider is read from env at startup.

```bash
# Switch to Ollama
sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=ollama/' .env
docker compose up -d --force-recreate threat-intel automation-agent

# Switch back to Anthropic
sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=anthropic/' .env
docker compose up -d --force-recreate threat-intel automation-agent
```

---

## Troubleshooting

### `LLM narrative generation failed: Connection refused`
Ollama is not running or not listening on the network. Check `OLLAMA_HOST=0.0.0.0` is set and
`ollama serve` is running.

### `LLM narrative generation failed: Request timed out`
The Ollama host is reachable but not responding within 120 seconds. The model may be loading for
the first time (cold start), or the host is under heavy load. Try `ollama run <model> hello` on
the Ollama host to pre-warm the model.

### `LLM returned empty response`
This was the original symptom when using Qwen3 via the OpenAI-compat endpoint. If you see this
after the Phase 6 fix, check that the container image was rebuilt (`docker compose build`) and
recreated (`--force-recreate`), not just restarted.

### `json_parse_error` in narrative
The model returned a response but it wasn't valid JSON. This can happen if `max_tokens` is too low
for the model to complete the JSON structure. The narrative `MAX_TOKENS=2000` and action
`_MAX_TOKENS=800` are set conservatively — increase them in `claude_client.py` / `claude_action.py`
if needed for larger models.

### Verifying the active provider in a running report

```bash
curl -s http://localhost:8001/api/report \
  | python3 -c "import json,sys; n=json.load(sys.stdin).get('narrative',{}); print(n.get('provider'), n.get('model'))"
```
