# CIO OpenClaw Governed Model Bridge

**Phase:** P-1.2A  
**Status:** Mock provider bridge implemented; production Alex route NOT activated  
**Branch:** feat/health-agent-pipeline-containment  
**Date:** 2026-08-08

## Architecture

### Current Direct Path (pre-bridge)
```
OpenClaw (Alex agent) → openclaw.json model config
                       → deepseek/deepseek-v4-pro (direct)
                       → DeepSeek API (api.deepseek.com)
                       → DeepSeek API key exposed to OpenClaw
```
No governance. No reservation. No cap enforcement. No provenance. Silent fallback chain to flash → chat → GPT → Ollama.

### Target Governed Path (bridge)
```
OpenClaw (Alex agent)
    │
    │ X-TradeAI-Agent: alex header
    │ POST /v1/chat/completions
    ▼
┌─────────────────────────────────────────────────┐
│  CIO Governed Model Bridge (127.0.0.1:8766)      │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ 1. Caller→Process Mapping (server-side)     │ │
│  │    X-TradeAI-Agent: alex → alex_cio_synthesis│ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ 2. Process Registration (process_registry)   │ │
│  │    verify registered, allowed policies      │ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ 3. Model Policy Resolution (server-side)     │ │
│  │    alex_cio_synthesis → PRO → deepseek-v4-pro│ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ 4. Governance Pipeline                       │ │
│  │    ├─ Circuit Breaker                        │ │
│  │    ├─ Global Daily USD Cap                   │ │
│  │    ├─ Per-Process Daily USD Cap              │ │
│  │    ├─ Reservation (atomic)                   │ │
│  │    ├─ [P-1.2A: Mock Provider → fixture]      │ │
│  │    ├─ Settlement                             │ │
│  │    └─ Provenance metadata                    │ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ 5. Response (OpenAI-compatible JSON)          │ │
│  │    model: deepseek-v4-pro (server-resolved)  │ │
│  │    _tradeai: governance provenance           │ │
│  │    mock: true (P-1.2A)                       │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
    │
    │ [P-1.2A: Mock fixture response]
    │ [P-1.2B: DeepSeek V4 Pro API]
    ▼
  Trade AI canonical LLM boundary
```

## Canonical Modules Reused

The bridge reuses (does NOT duplicate) these canonical governance modules:

| Module | Function | Bridge Usage |
|--------|----------|--------------|
| `scripts/lib/llm_consumption.py` | `get_process_config()` | Process registration check |
| `scripts/lib/llm_consumption.py` | `check_cost_cap()` | Global + per-process cap enforcement |
| `scripts/lib/llm_consumption.py` | `reserve_projected_cost()` | Atomic budget reservation |
| `scripts/lib/llm_consumption.py` | `settle_reservation()` | Cost settlement |
| `scripts/lib/llm_consumption.py` | `cost_persistence_available()` | DB health check |
| `scripts/lib/llm_consumption.py` | `log_call()` | Sanitized consumption logging |
| `scripts/lib/llm_model_registry.py` | `reject_legacy_model_id()` | Reject legacy model IDs |
| `scripts/lib/llm_model_registry.py` | `estimate_usd_cost()` | Model pricing lookup |
| `scripts/lib/consumption_run_manual.py` | `projected_max_cost_usd()` | Projected cost calc |
| `scripts/lib/consumption_run_manual.py` | `validate_paid_cap_config()` | Cap config validation |

## Watchlist-Specific (NOT reused)

These are watchlist-specific and intentionally NOT reused for Alex:

- `agent_flash_governance.governed_flash_call()` — hardcoded to `deepseek-v4-flash` and watchlist `TASK_TO_PROCESS` mapping
- `agent_flash_governance.policy_for_task()` — watchlist-specific escalation decisions
- `agent_jobs_containment.guard_agent_jobs_execution()` — containment for `process_watchlist_agent_jobs.py` only
- `agent_flash_governance.TASK_TO_PROCESS` — watchlist task types (agent_narrative, debate, etc.)

## Generic Governance Extraction

The bridge extracts governance as a generic pipeline that can serve any agent. The caller→process mapping, policy resolution, reserve/settle pipeline, and circuit breaker are all generic. Watchlist Flash keeps its own `governed_flash_call()` unchanged.

## Server-Side Caller→Process Mapping

```
X-TradeAI-Agent: alex  →  alex_cio_synthesis
```

- Mapping is server-side only; client CANNOT inject a process_id
- Unknown callers get 401 UNAUTHORIZED with $0 cost
- This header is a pre-shared secret between OpenClaw config and the bridge

## Model-Policy Mapping

```
alex_cio_synthesis  → PRO       → deepseek-v4-pro (thinking: disabled)
alex_cio_escalation → PRO_THINK → deepseek-v4-pro (thinking: enabled, operator confirmation required)
```

## Request/Response Contract

- **Endpoint:** `POST /v1/chat/completions`
- **Format:** OpenAI-compatible JSON
- **Auth:** `X-TradeAI-Agent: alex` header (pre-shared)
- **Request:** `messages`, optional `tools`, `tool_choice`, `response_format`, `stream`, `max_tokens`
- **Response:** `id`, `object`, `model`, `choices`, `usage`, `_tradeai` provenance
- **Client model field:** Logged but IGNORED for resolution
- **Streaming:** Supported via SSE (`text/event-stream`) in P-1.2A mock mode

## Tool-Call Contract

- `tools` array in request forwarded to provider
- `tool_calls` in assistant response preserved
- `tool` role messages with `tool_call_id` preserved for continuations
- MockProvider returns fixture tool_calls when tools are present

## Security Boundary

```
OpenClaw (untrusted)  ⟷  Bridge (127.0.0.1:8766)  ⟷  DeepSeek API (api.deepseek.com)
```

- Bridge binds to 127.0.0.1 only (never 0.0.0.0 or LAN)
- DeepSeek API key NEVER exposed to OpenClaw; key stays in Trade AI env
- Server-side process/model resolution (client claims ignored)
- Fail-closed on all governance failures
- Legacy model IDs rejected
- No silent fallback — errors surfaced as visible failures

## Logging/Privacy

- Full prompt content is SHA-256 hashed for audit trail
- Log summaries show role counts and character lengths only
- Never log raw portfolio data, account numbers, or SSN-like content
- All `log_call()` entries use hashed content references

## Dedupe Semantics

- Alex CIO processes use `request_id_only` dedupe policy
- This means: same request_id within TTL is deduped
- Not content-hash based (unlike watchlist evidence_hash dedupe)

## Rollback

```
# Identity changes:
cp ~/.openclaw/agents/alex/agent/IDENTITY.md.bak_p1_2a_rollback ~/.openclaw/agents/alex/agent/IDENTITY.md
cp ~/.openclaw/agents/alex/agent/SOUL.md.bak_p1_2a_rollback ~/.openclaw/agents/alex/agent/SOUL.md
cp ~/.openclaw/openclaw.json.bak_p1_2a_rollback ~/.openclaw/openclaw.json

# Process registry:
cp config/llm_process_registry.json.bak_p1_2a_rollback config/llm_process_registry.json
```

## Later Activation / Canary Steps (P-1.2B)

1. Update `openclaw.json` models.providers to include `tradeai-governed` provider pointing to `http://127.0.0.1:8766/v1`
2. Change Alex's model primary from `deepseek/deepseek-v4-pro` to `tradeai-governed/deepseek-v4-pro`
3. Remove fallbacks for Alex only (no silent fallback on governed path)
4. Add `X-TradeAI-Agent: alex` header to provider config
5. Replace MockProvider with actual DeepSeek client
6. Start bridge as systemd service
7. Canary: single operator-initiated query, verify response arrives with provenance
8. Full activation
