# PHASE 213 — Codex Headless Closeout & External Lane Hardening — CLOSEOUT (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T16:43:49-04:00
Measured at: efcc51365 / not measured

- Phase 213 complete: **YES**
- Hermes version: **0.16.0** · newer Hermes available: **NO**
- Codex interactive ready: **YES** (`hermes -p dev chat`, openai-codex/gpt-5-codex, free)
- Codex headless automation available: **NO** · reason code: **hermes_headless_limit**
- Capability cache added: **YES** (`data/runtime/hermes_llm_capabilities.json`)
- chatgpt lane fails closed: **YES** (cache-gated, no Codex retry, status=unavailable)
- Force retest available: **YES** (`--force-retest`)
- Grok automated lane ready: **YES** (xai-oauth proxy, free) · Local automated lane ready: **YES** (Ollama)
- Claude status: **credits_required** · Nous status: **auth_pending**
- Production Hermes upgraded: **NO**
- tradeai/tradeai12b remain tool-less: **YES** · retired gateway disabled: **YES**
- v2 UI changed: **NO** · trading/proposal/protection/broker touched: **NO** · live trading: **ZERO** · Level 7: **PROHIBITED**
- Read-only update checker added: `scripts/check_hermes_update_available.py` (weekly schedule = plan only, not enabled)
- **Next recommended gate:** when `check_hermes_update_available` flags a build > 0.16.0, re-run PHASE212E;
  if headless Codex finalizes, clear the cache block and the chatgpt lane auto-activates. Meanwhile: Grok =
  free automated external lane; Claude = high-stakes once credits added.
