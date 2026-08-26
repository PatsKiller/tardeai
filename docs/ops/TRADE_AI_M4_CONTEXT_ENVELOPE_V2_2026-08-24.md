# M4 ContextEnvelope@v2

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED + MERGED (#500 `15ab2362`, reconciled head `ef1ec953`) + DEPLOYED on CURRENT `15ab2362-main-exact-phase2-20260824-200105`. Full PR E UI is **not** implemented. Natural same-brain after this promote is a scheduled-cycle proof, not a diagnostic substitute.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

M4 consumes M3 contracts (`AgentEpisode@v1`, `MemoryConsolidator@v1`) rather than duplicating them. Nested `CIOContextEnvelope@v2` lives inside `ContextEnvelope@v1` (`research_memory.cio_context_v2`). It is not a competing private brain.

## Same-brain agents

Hermes, CIO (Alex), Advisory, Telegram CIO, Maria, Steph, Aegis advisory, weekly CIO learning.

Shared lookup: ticker/alias → `security_guid` → TickerResearchState → curation/baseline → SymbolThesis. Ticker remains alias.

Read-only diagnostic on CURRENT `15ab2362` (2026-08-24 20:09 ET): `same_brain` **consistent=true** for SCHD, SCHG, CSCO, ANET, NOC, PRSO. PRSO `security_guid=null` is an **identity gap**, not a cross-agent fork. `telegram_fork=false`. `portfolio_delta=NO_PORTFOLIO_CHANGE`. `paid_dispatch=0`.

## Planes

`cio_persistent_cognition.V2_SECTIONS` (envelope builder): OFFICE_TRUTH, PORTFOLIO_STATE, OPERATOR_POLICY, PORTFOLIO_THESIS, MARKET_CONTEXT, SEASONALITY, TICKER_RESEARCH_STATE, BASELINE_OR_CURRENT_CURATION, SYMBOL_THESIS, RESEARCH_GAPS, CONTRADICTIONS, EVENTS_CATALYSTS, RELEVANT_FEEDBACK, MATURE_OUTCOMES, LESSONS, MEMORY_RETRIEVAL_UNITS.

`cio_context_envelope_v2.SECTIONS` (M4 overlay tuple) additionally names POLICY, CURATION, EPISODIC_CONTEXT, SEMANTIC_OPERATOR_MEMORY, RAG_SUPPORT, RAG_COUNTER. That naming split is **source-honest**, not silently unified in this closeout.

Every item carries authority / source / version / as_of / entity GUID / freshness. Hard distinction: AUTHORITATIVE_FINANCIAL_TRUTH, DETERMINISTIC_POLICY, DURABLE_INVESTMENT_BELIEF, RESEARCH_CONTEXT, OPERATOR_CONTEXT, HISTORICAL_CONTEXT. Memory cannot override financial truth.

## Bounded context

Default cap 12 names. Token estimate recorded. No raw history dump. No private chain-of-thought.

## Command Center views (spec only)

CIO BRAIN · TICKER INTELLIGENCE · MEMORY · LEARNING — **not** implemented as UI in this PR.

## Proactive CIO

Source detector may emit `OPERATOR_NOTIFICATION_CANDIDATE`. No trading.

## Natural proof

Manual `same_brain` diagnostic does **not** substitute for a scheduled Hermes/CIO/Advisory/Telegram cycle on this SHA.

Observed (not `systemctl start`):

- `tradeai-free-first-circulation.timer` 20:23:47–20:27:24 ET, run_id `019117db-e364-4668-a96f-a453f0f1bf16`, SOURCE `15ab2362`, 120 FRESH_NO_CHANGE, 0 paid, 0 SearXNG, `financial_action=false`.
- `tradeai-hermes-cio-worker.timer` 20:15:46 ET claimed 0 (no duplicate research drain).
- `tradeai-cio-material-scan.timer` 20:06 and 20:26 ET: SCHD DecisionPayload, `notification.sent=false`, **pack-in-trace still false**.

See `docs/_evidence/yedas_eye/NATURAL_CIO_PERSISTENT_COGNITION_ACCEPTANCE.json`.
