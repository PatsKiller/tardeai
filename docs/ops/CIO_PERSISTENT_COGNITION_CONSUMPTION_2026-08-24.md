# CIO persistent cognition consumption

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED. Not MERGED as live. Not NATURALLY_PROVEN.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

M1 is LIVE on CURRENT `5c0a993a` (natural timer 11:23:44–11:27:13 ET, run_id `5e9028fb`). This PR makes CIO / Advisory / Telegram **read** that brain.

## What

`scripts/lib/cio_persistent_cognition.py` is the shared read-only loader.

Lookup is identity-first:

`ticker | alias | CUSIP-like → security_guid → TickerResearchState → HermesCurationSummary (MATERIAL or BASELINE_PROJECTION v0) → SymbolThesis → gaps / contradictions`

Baseline v0 is legitimate prior cognition, not “no cognition.”

CIOContextEnvelope@v2 is nested inside ContextEnvelope@v1 (`research_memory.cio_context_v2`). It is not a competing envelope. Required sections all carry `authority / source / version / as_of / entity GUID / freshness`.

TickerResearchState and curation are `RESEARCH_CONTEXT`. They cannot override cash, quantity, market value, orders, risk, or 2FA (`AUTHORITATIVE_FINANCIAL_TRUTH`).

## Consumers (same loader)

| surface | path |
|---|---|
| ContextEnvelope | `get_context_for_agent` attaches `persistent_ticker_cognition` |
| CIO worker | `CIORunWorker._cio_synthesis` / `_load_goal_context` |
| CIO reassessment | `reassess_on_research_completed` starts from the pack |
| Advisory Desk | `advisory_memory.build_memory_for_row` exposes `security_guid`, `research_state_version`, `curation_version` (no raw JSON in UI) |
| Telegram CIO | `cio_telegram_converse.assemble_context` |

No `cio_ticker_memory.jsonl`. Canonical JSONL remains canonical.

## WHAT_CHANGED

CIO asks: **WHAT MATERIAL THING CHANGED FOR THE PORTFOLIO?**

Possible calls: `NO_PORTFOLIO_CHANGE` | `RESEARCH_REQUIRED` | `THESIS_REVIEW_REQUIRED` | `PORTFOLIO_REASSESSMENT_REQUIRED` | `OPERATOR_NOTIFICATION_CANDIDATE`.

Live M1 `NO_NEW_INFO` / `FRESH_NO_CHANGE` / `BASELINE_PROJECTION` is **not** a material delta even when RAG artifact watermarks grow. Unchanged cognition → deterministic `NO_PORTFOLIO_CHANGE` **without a model**.

If synthesis is needed, the pack marks `FLASH_ELIGIBLE` / `CHALLENGER_ELIGIBLE` / `PRO_ELIGIBLE` and **stops before dispatch**. This prompt authorizes no paid calls.

## ResearchGap

CIO may upsert `ResearchGap` via `need_data_gap`. It does not web-search and does not start a duplicate research lane.

Sources discover → Hermes investigates → Librarian curates → CIO decides.

## Conflict

`TickerResearchState` `CONFLICTED` surfaces support + counterevidence and suppresses recommendations. No silent resolution.

## Context budget

Materiality roles: HELD, REENTRY, WATCH, OPPORTUNITY, LARGE_EXPOSURE, CASH_DEPLOYMENT, PORTFOLIO_THESIS, CURRENT_DECISION. Default cap 12 names. Token estimate recorded on the pack.

## Audit

Every consumption emits `ContextUseReceipt@v1` (run_id, agent, task, security_guid, state/curation/thesis versions, gap IDs, why selected, source SHA). No chain-of-thought.

## Not in this PR

- SQL `r10_memory_shadow.sql` apply
- Neo4j / Mem0 / Redis
- Producer retirement
- UI overhaul
- Paid Flash activation
- CURRENT promote
- Merge without operator review after exact-head CI
