# ADR: LLM Governance Boundary

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-LLM-002
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3 (23 corrections)

## Decision

Freeze exactly one governed paid-model boundary for production financial agents. All financial-agent LLM calls route through Trade AI's governed gateway. No financial agent may use direct OpenClaw DeepSeek as fallback.

## Canonical Gateway Module

**Path:** `scripts/lib/agent_flash_governance.py` (544 lines)

This is the canonical LLM gateway module. It provides a governed path for DeepSeek Flash calls with the following capabilities:

### Core Structure

```python
FLASH_MODEL = "deepseek-v4-flash"
FLASH_POLICY = "FAST"
FLASH_THINK_POLICY = "FAST_THINK"

LEGACY_MODEL_IDS = frozenset({"deepseek-chat", "deepseek-reasoner", "deepseek-v4", "deepseek_v4", "v4"})

TASK_TO_PROCESS: dict[str, str] = {
    "agent_narrative": "watchlist_maria_flash_narrative",
    "agent_debate": "watchlist_agent_debate_flash",
    "sector_correlation": "watchlist_risk_flash_narrative",
    "cio_synthesis": "watchlist_steph_flash_narrative",
    "catalyst_classification": "watchlist_agent_flash_extract",
    "sentiment": "watchlist_agent_flash_extract",
    "fast_summary": "watchlist_agent_flash_extract",
    "code_generation": "watchlist_agent_flash_extract",
    "default": "watchlist_maria_flash_narrative",
}
```

### Governance Methods

| Method | Function | Canonical |
|---|---|---|
| `governed_flash_call()` | Primary entry: execute one governed DeepSeek Flash call. Fail-closed, no silent fallback. | YES |
| `reject_legacy_model_id()` | Reject any legacy model ID (deepseek-chat, deepseek-reasoner, etc.) | YES |
| `process_for_task()` | Map task_type to registered process ID | YES |
| `policy_for_task()` | Return (policy, escalation_reason) — FAST by default, FAST_THINK for deterministically escalated cases | YES |
| `should_escalate_fast_think()` | Deterministic conditions for FAST_THINK escalation | YES |
| `evidence_hash()` | SHA-256 deduplication key from process_id + task_type + prompt + job_key | YES |
| `already_completed()` / `mark_completed()` | Deduplication cache (6h TTL) | YES |
| `circuit_open()` / `_trip_circuit()` / `_reset_circuit_on_success()` | Circuit breaker (8 errors → 900s cooldown) | YES |
| `_reserve_run_budget()` | Pre-flight cost reservation against aggregate + per-process run caps | YES |
| `reset_run_budget()` / `run_budget_snapshot()` | Run budget lifecycle | YES |

### Governance Enforced at Gateway Level

1. **Containment check** (calls `agent_jobs_containment.guard_agent_jobs_execution` before any call)
2. **Circuit breaker** (in-process, 8 consecutive errors → 900s cooldown, fail-closed)
3. **Process registration** (must be in `config/llm_process_registry.json`; unregistered → rejected)
4. **Input limit enforcement** (per-process max_input_tokens from registry)
5. **Output limit enforcement** (per-process max_output_tokens clamped)
6. **Deduplication** (SHA-256 evidence hash, 6h TTL, persistent cache)
7. **Pre-flight cost reservation** (projected cost against aggregate + per-process run caps)
8. **Model ID verification** (exact `deepseek-v4-flash`; returned model mismatch → circuit trip)
9. **Fallback prohibition** (provider fallback → circuit trip, no silent routing)
10. **Provenance** (process_id, run_id, model, policy, evidence_hash, cost_estimate, tokens)

### Consumption Ledger Integration

The gateway calls `scripts/lib/llm_consumption.py`:
- `lc.get_process_config(process_id)` — lookup process registry configuration
- `lc.gate_and_generate(...)` — actual provider call with settlement recording
- Post-call: cost estimate is recorded in the result dict

### Canonical Cost Cap Constants

```python
MAX_CALLS_PER_PROCESS = int(os.environ.get("AGENT_FLASH_MAX_CALLS_PER_PROCESS", "40"))
MAX_CALLS_PER_RUN_TOTAL = int(os.environ.get("AGENT_FLASH_MAX_CALLS_PER_RUN_TOTAL", "40"))
MAX_PROJECTED_USD_PER_RUN = float(os.environ.get("AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN", "0.50"))
CIRCUIT_ERROR_THRESHOLD = int(os.environ.get("AGENT_FLASH_CIRCUIT_ERRORS", "8"))
CIRCUIT_COOLDOWN_SEC = int(os.environ.get("AGENT_FLASH_CIRCUIT_COOLDOWN_SEC", "900"))
```

## Canonical Supporting Modules

### Model Registry

**Path:** `config/llm_model_registry.json` + `scripts/lib/llm_model_registry.py`

Resolves logical policies (FAST, FAST_THINK, PRO, PRO_THINK, PRO_MAX) to exact provider model IDs. Validates against `EXACT_DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}`. Rejects legacy model IDs (`deepseek-chat`, `deepseek-reasoner`). Fail-closed on unknown policies, disabled providers/models, or missing operator cost confirmation.

### Process Registry

**Path:** `config/llm_process_registry.json` (424 lines, 29 registered processes)

Contains registered process definitions with per-process policies:
- `lane_policy`, `allowed_lanes`, `deepseek_default_policy`, `deepseek_allowed_policies`
- `max_input_tokens`, `max_output_tokens`, `daily_soft_cap`, `daily_cost_cap_usd`
- `tools_allowed`, `fallback_allowed`, `advisory_only`
- `escalation_conditions`, `requires_operator_cost_confirmation_for`

Registered process IDs observed:
- `watchlist_maria_flash_narrative`, `watchlist_risk_flash_narrative`, `watchlist_steph_flash_narrative`
- `watchlist_agent_debate_flash`, `watchlist_agent_flash_extract`
- `deepseek_flash_operator_smoke`, `watchlist_cio_synthesis`
- `unregistered`, `pipeline_health_diagnosis`, `architecture_review`
- Plus 19 more processes across Grok, ChatGPT, and OAuth lanes

### Consumption / Settlement Module

**Path:** `scripts/lib/llm_consumption.py`
**Cost projection:** `scripts/lib/consumption_run_manual.py`

Handles post-flight cost settlement: records actual provider usage, token counts, cost estimate, and settles against the daily cap. The `gate_and_generate()` function with `return_provenance=True` returns provider provenance including usage, estimated_cost_usd, requested_model_id, returned_model.

### Pro Routing

**Path:** `scripts/lib/rockville/model_policy.py`
**Config:** `config/rockville/ROCKVILLE_WATCH_CIO_MODEL_POLICY.json`

Handles escalation from FAST → PRO_THINK → PRO_MAX for CIO synthesis. Requires operator cost confirmation for PRO_MAX. Policy escalation driven by deterministic conditions (explicit flags, severity, reviewer disagreement, conflicting evidence) — not by LLM classification.

### Containment Module

**Path:** `scripts/lib/agent_jobs_containment.py`

Guards agent job execution via `guard_agent_jobs_execution()`. Called at the entry of `governed_flash_call()`. Fail-closed on any uncertainty (I/O errors, malformed content, unknown env values → block).

### Deduplication

In-process within `agent_flash_governance.py`:
- `evidence_hash()` — deterministic SHA-256 key
- `already_completed()` / `mark_completed()` — thread-safe dedupe cache
- Persisted to `AGENT_FLASH_DEDUPE_PATH` (default: `/tmp/tradeai_agent_flash_dedupe.json`)
- TTL: 6 hours (`_DEDUPE_TTL_SEC = 6 * 3600`)

### Circuit Breaker

In-process within `agent_flash_governance.py`:
- `circuit_open()` — check if breaker is tripped
- `_trip_circuit(err)` — increment error count; trip at threshold
- `_reset_circuit_on_success()` — clear on success
- Triggers on: provider exception, returned model mismatch, provider fallback detected
- Cooldown: 900 seconds after threshold (8 errors)

## Governed Call Flow

```
OpenClaw Alex / Specialists
  │
  ▼
Trade AI LLM Gateway (agent_flash_governance.py)
  │
  ├─ 1. Containment check (agent_jobs_containment.guard_agent_jobs_execution)
  ├─ 2. Circuit breaker check
  ├─ 3. Process ID resolution (process_for_task)
  ├─ 4. Process registry validation (llm_consumption.get_process_config)
  ├─ 5. Input limit enforcement
  ├─ 6. Deduplication check (evidence_hash → already_completed)
  ├─ 7. Pre-flight cost reservation (_reserve_run_budget)
  ├─ 8. Provider call (llm_consumption.gate_and_generate)
  ├─ 9. Post-flight verification (model match, fallback check)
  ├─ 10. Settlement (consumption ledger recording)
  ├─ 11. Deduplication marking (mark_completed)
  │
  ▼
deepseek-v4-flash (or deepseek-v4-pro for governed escalation)
```

## LAB Exception (Non-Financial Only)

Direct OpenClaw DeepSeek may exist ONLY for:
1. Separate non-financial diagnostic/test agent
2. Explicit manual CLI diagnostic (`openclaw agent --agent diag`)
3. Isolated lab config (no financial tools, no portfolio access)
4. NO production CIO handoff route

**Rule:** Financial agents (Alex/Maria/Steph/Guardian/Ledger) must NEVER have direct OpenClaw DeepSeek as fallback. If the governed route fails → typed failure → no silent fallback to direct OpenClaw path.

## Prohibited Patterns

| Prohibited | Reason |
|---|---|
| Direct OpenClaw DeepSeek calls from financial agents | Bypasses authorization, reservation, cap, dedupe, circuit breaker, provenance |
| Dual-key architecture with two consumption ledgers | Creates governance gap; must be ONE governed boundary |
| Silent provider fallback | Model routing must be explicit and validated; fallback → circuit trip |
| Legacy model ID usage (deepseek-chat, deepseek-reasoner, etc.) | Rejected at gateway entry; no backward compatibility |
| Unregistered process ID calls | Rejected; must be in `config/llm_process_registry.json` |

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires operator approval and ADR amendment.*
