# Local LLM Runtime Policy (canonical)

**Status:** Active · **Updated:** 2026-06-29
**Authority:** This is the single source of truth that `config/hermes_research_budget.yaml`, `scripts/hermes_research_budget_guard.py`, `scripts/local_llm.py`, and `scripts/local_llm_config.py` must agree with. The Hermes research budget guard explicitly states its market-hours local-GPU rules **must match this document**.

> This file was reconstructed 2026-06-29 because it was referenced across the codebase (guard, budget YAML, CHANGELOG, `HERMES_RESEARCH_BUDGET_POLICY.md`) but absent on disk. The rules below are transcribed from the live, enforced implementation, not aspirational.

---

## 1. Hardware context
Single-GPU box (Intel Arc B50). Ollama runs **one resident model at a time** — VRAM is the binding constraint. Concurrency and heavy-model rules below exist to prevent GPU contention, OOM, and the multi-minute stalls a too-large model causes.

## 2. Market-hours local-GPU window
- **Window:** `06:00–12:00` America/New_York. **This is the GPU-heavy gating window, NOT regular trading hours (9:30–16:00).** It protects the box during the busiest research/ingestion hours.
- **Blocked local models during the window:** `gemma3:27b`, `gemma4-31b` (the "local heavy" tier).
- **Allowed local models during the window:** `gemma3:4b`, `gemma3:12b`, `qwen3:8b`, `nomic-embed-text`.
- **Enforcement:** `hermes_research_budget_guard._is_market_hours()` + the `local_heavy` block (decision → `BLOCK`, reason "local heavy model (27B/31B) blocked during market hours — defer to overnight or use free-OAuth"). The same 06:00–12:00 ET window is independently enforced in `scripts/claude_escalation_handler.py`.
- Heavy local research is **deferred to overnight** (batch lane) or routed to a **free-OAuth** cloud lane — never run during the window.

## 3. Model tiers (lane taxonomy)
| Tier | Models | Use |
|------|--------|-----|
| `local_fast` | `gemma3:4b` | default local model (`DEFAULT_LOCAL_LLM_MODEL`); fast classification/scoring |
| `local_quality` | `gemma3:12b` | quality local — *see runtime caveat below* |
| `local_heavy` | `gemma3:27b`, `gemma4-31b` | deep/overnight only; **blocked 06:00–12:00 ET** |
| `cloud_free` | `grok` (xAI proxy `:8645`), `chatgpt` (openai-codex proxy `:8646`) | free-OAuth cloud; no API key, no metered cost |
| `cloud_paid` | `claude-sonnet-4-6`, `claude-opus-4-8`, `gpt-4o` | deliberate, cost-gated oversight **only** — never a fallback |
| `embedding` | `nomic-embed-text` | embeddings |

**Runtime caveat (`local_llm_config.py`):** the live default is `gemma3:4b`. `gemma3:12b` is policy-"allowed" but was observed to stall (~500s/prompt) at the Ollama runtime and is avoided in practice; treat 4b as the working default and 12b as opt-in only.

## 4. GPU concurrency & disabled-model enforcement
- `OLLAMA_MAX_LOADED_MODELS=3` (live systemd unit; single resident model is still the practical constraint via the file lock), `OLLAMA_KEEP_ALIVE=5m` on the live unit (`30m` in older notes).
- **Cross-process single-job lock:** `scripts/local_llm.py` acquires `/tmp/tradeai_local_llm_single_job.lock` (wait timeout 600s) so only one caller hits Ollama at a time — no concurrent GPU contention.
- **Disabled models:** `DISABLED_LOCAL_LLM_MODELS` (env). A disabled request is substituted with `LOCAL_LLM_SAFE_MODEL` (default `gemma3:4b`). Pre-call cleanup unloads disabled/non-target models and **fails closed** if a disabled model is still resident.

## 5. Free-OAuth vs paid (hard rules)
- `lanes.free_oauth = [grok, chatgpt]` — the only cloud lanes Hermes research may use; both are OAuth-proxied, **no API key, no paid path**.
- `no_paid_fallback: true` — paid Claude/OpenAI are **never** a fallback for a free-OAuth or local job.
- `fail_closed: true` — unknown lane / unknown trigger / missing inputs → block, never guess.
- **Cloud unavailable** (free-OAuth proxy down/auth-expired) → `DEFER`; **never** fall back to paid and **never** fall back to a local-heavy model.
- Paid lane requested for a research call → `BLOCK` (paid is reserved for explicit cost-gated oversight outside this research path).

## 6. Health-agent escalation (`claude_escalation_handler.py`)

Tier 3 local LLM is **ops triage only** — root-cause narrative from log tails; **never** auto-executes fixes (Tier 1 `retry_cmd` is separate and allowlisted).

| Tier | Model | When |
|------|--------|------|
| 3a | gemma4:31b (llama.cpp) | Off-hours, low load — skipped 06:00–12:00 ET and when `load1` > cap |
| 3b | **gemma3:4b** (default) | Market hours, batch ≥2 items, or high load — avoids 12b stalls/timeouts |
| 3b fallback | gemma3:4b | If a heavier Ollama model was selected and fails |
| 3c | Claude CLI | Opt-in (`ESCALATION_USE_CLAUDE_CLI=1`) only |

**Trust model:** treat Tier 3 Telegram as **hypothesis for operator review**, not authoritative. Portfolio weekly/monthly **actions** use OAuth + `portfolio_report_llm.sanitize_action_text()`, not local 4b.

Env: `ESCALATION_LLM_MODEL_SMALL` (default `gemma3:4b`), `ESCALATION_LLM_MODEL` (default `gemma3:12b`, avoided in practice), `ESCALATION_31B_LOAD_CAP`, `DISABLE_GEMMA4_31B_ESCALATION`.

## 7. Cross-references
- `config/hermes_research_budget.yaml` — `market_hours`, `lanes`, tier policy (must mirror §2–§5).
- `scripts/hermes_research_budget_guard.py` — `_is_market_hours()`, `_lane_kind()`, the local-heavy block, no-paid-fallback enforcement.
- `scripts/local_llm.py` / `scripts/local_llm_config.py` — single-job lock, disabled-model substitution, concurrency env.
- `scripts/llm_lane.py` — the free-OAuth lane clients (Grok `:8645`, ChatGPT `:8646`).
- `docs/HERMES_RESEARCH_BUDGET_POLICY.md`, `docs/HERMES_RESEARCH_SCOPE_AUDIT.md`.
