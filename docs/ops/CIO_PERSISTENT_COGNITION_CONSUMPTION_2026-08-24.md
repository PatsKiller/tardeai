# CIO persistent cognition consumption

**Date:** 2026-08-24  
**Status:** MERGED (#497, #502) + DEPLOYED (`1afb1479`). Hermes free-first NATURALLY_PROVEN. CIO pack-in-trace **NATURALLY_PROVEN** 23:17 ET SCHD on exact-main `1afb1479`.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

M1 natural (11:23 ET, `5e9028fb`) remains historical. Consumer #497 merged 19:37Z; first CURRENT `0a0e19bf`. Natural free-first 19:23:55–19:27:23 ET run_id `b1623bcb` SOURCE `0a0e19bf`, 120 FRESH_NO_CHANGE, 0 paid. Exact-main promote after #500: CURRENT `15ab2362-main-exact-phase2-20260824-200105` at 20:01:58 ET (SOURCE=BUILD=GIT=`15ab2362361cbd8e0ded3d0c2ce2b83f7e8bacc7`). Telegram CIO was still on `b935076f` until a read-only restart at 20:08:24 ET onto `15ab2362`. Natural free-first on that SHA: 20:23:47–20:27:24 ET run_id `019117db`, 120 FRESH_NO_CHANGE, 0 paid.

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

Natural **material_scan** (systemd `tradeai-cio-material-scan.timer`) on CURRENT `15ab2362` at 20:06:16–20:06:20 ET: `READ_ONLY_ADVISORY`, `dry_run=true`, SCHD DecisionPayload `DATA_CONFLICT` / `financial_action=false` / `notification.sent=false`. Trace does **not** embed `persistent_ticker_cognition`. That path is still a DecisionPayload surface, not a pack-in-trace proof.

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

## Not in this program

- SQL `r10_memory_shadow.sql` apply
- Neo4j / Mem0 / Redis
- Producer retirement
- UI overhaul
- Paid Flash activation
- Dual writer
