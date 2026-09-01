# v3 Journal → Backtesting Integrity Audit (2026-06-06)

Status:      HISTORICAL
as_of:       2026-06-06T11:30:56-04:00
Measured at: efcc51365 / not measured

Read-only audit + safe fixes only. No trading/GO-WAIT/strategy/broker/proposal/order/stop/live changes.
Verdict: **treat the Backtesting page as DIAGNOSTIC/ADVISORY only** until the code fixes below land.

## 1. "Last run" badge — FIXED 2026-06-06 (was STALE SOURCE)
- Backtest data IS fresh: `trade_backtest_results` max computed_at = 2026-06-05 22:52; LLM reviews dated
  2026-06-05; drain/edge work 2026-06-06. So the engine is running; the **badge reads a stale/wrong source**.
- `/api/v2/backtesting/status` aggregates counts from `backtest_datasets` / `strategy_backtest_runs`
  (the latter has no `computed_at`); the badge conflates "strategy backtest run" with "engine run / LLM
  review / edge comparison." ROOT CAUSE = single badge over multiple distinct pipelines with no per-source
  timestamp. FIX: show per-source last-run (engine / strategy / LLM-review / edge) each with its own
  max-timestamp; stop emitting one ambiguous date.

## 2. Cadences — CONFIRMED configured + running (no fix needed)
cron: Sun 22:00 enterprise_backtester --replay-trades · Mon–Fri 06:00 strategy_backtester --all-strategies
· Sun 23:00 trade_close_llm_analyzer --source backtest · Mon–Fri 18:30 trade_backtest_engine · history
snapshots Mon–Fri 06:10 + Sun 22:10. The "daily 6AM / Sunday 10PM" cadences exist and fire. The stale
badge is a UI/source bug, NOT a cadence failure.

## 3. Endpoint freshness / source tables
- trade_backtest_results (95, fresh) · strategy_backtest_trades (~2050, LLM-review source) ·
  strategy_backtest_runs (367). Endpoints read these directly. Provenance gap: see #9.

## 4. Missed proposals — DUPLICATED, no canonical dedup (needs fix, not applied)
`/api/v2/backtesting/missed-opportunities` joins `paper_trade_proposals` → `strategy_backtest_trades` by
symbol + 72h window, with **no dedup by proposal/signal key** → one proposal matches many sim rows →
ARM/SNOW/MRVL/BLBD repeat. FIX: `DISTINCT ON (ptp.id)` (or a canonical proposal+signal dedupe key); count
distinct proposals, not join rows.

## 5. Missed-proposal verdict — derived from P&L sign only (needs fix, not applied)
`would_win` = `simulated_pnl > 0`; no verdict field. The "21 win / 29 lose" metric is unreliable. FIX: add
explicit `verdict` (WIN/LOSS/BREAKEVEN/NO_FILL/INSUFFICIENT) from the sim row, not bare P&L sign.

## 6. Optimization tab — repeated breakeven-threshold blocks — FIXED 2026-06-06
Repeated identical breakeven-threshold families = response-shape/rendering bug in
`trailing-optimization` / `mfe-analysis` output (or the frontend mapping without dedup). FIXED: `/api/v2/backtesting/trailing-optimization` was `SELECT * ... ORDER BY created_at DESC` returning ALL
267 history rows (one per strategy_family PER RUN, ~65 runs each). Now `SELECT DISTINCT ON (strategy_family)
... ORDER BY strategy_family, created_at DESC` → 5 latest-per-family rows + diagnostics{distinct_families,
raw_history_rows}. v3 tab shows 'latest for N families (collapsed from 267 historical run rows)'. Verified 267->5.

## 7. LLM review errors — 1778/2102 (85%), but ROOT CAUSE is INFRASTRUCTURE (triaged)
Error classification (status='error'):
- **924 "timed out"** + **709 "Connection refused [Errno 111]"** + 29 "remote end closed" + 9 HTTP 500
  = **1671 LLM-availability failures** (Ollama down/overloaded during the Sun 23:00 review cron).
- 60 json_parse_failed (real parser issues) · 47 null.
So the 85% is **not** bad analytics logic — it is the local LLM being unavailable for the batch. FIX:
gate the LLM-review cron on an Ollama health check + bounded retry for transient (timeout/conn-refused);
only the 60 parse failures need parser hardening. Until then the review corpus is too sparse to feed even
shadow learning (185 valid of 2102).

## 8. Stale cost-basis pollution — FIXED (safe, reversible)
10 V/AXTI reviews cited pre-fix inflated returns ("exceptional 641%", "661.37%", "641.71%") while marked
`meaningful_structured_review` (counted as valid). **Invalidated**: status → `superseded_stale_cost_basis`
+ error_message note; backed up to data/runtime/llm_review_stale_basis_backup_20260606/rows.json (ids
2063,2065,2070,2071,2072,2083,2084,2093,2095,2096). Valid reviews 195 → 185. Regenerate after basis repair.

## 9. Provenance — MISSING on reviews (needs fix, not applied)
`trade_llm_reviews` has paper_trade_id + backtest_trade_id + source_table but **no trade_instance_id**.
The page can't show canonical lineage per row. FIX: add `trade_instance_id` (additive, like the other
consumer tables) + surface source_table / replay-vs-sim-vs-import-vs-paper / linked-status / data_quality
in the UI so every analytic row is provenanced.

## 10. Autonomous learning — CONFIRMED SHADOW_ONLY / DO_NOT_GRAFT
evaluate_shadow_efficacy → INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT (n<20); GO/WAIT + strategy scoring untouched.

## Summary
| # | Item | Status |
|---|------|--------|
| 1 | last-run badge stale source | **FIXED** 2026-06-06 (per-pipeline last_runs + last_run_overall; badge shows freshest) |
| 2 | backtest cadences | CONFIRMED running |
| 3 | endpoint freshness/source | documented |
| 4 | missed-proposal dedup | **FIXED** 2026-06-06 (1461->168; proposal_id key) |
| 5 | missed-proposal verdict field | **FIXED** 2026-06-06 (sim_outcome_verdict incl MIXED) |
| 6 | optimization repeated blocks | **FIXED** 2026-06-06 (DISTINCT ON strategy_family; 267->5 latest-per-family) |
| 7 | LLM review 85% errors | **FIXED** 2026-06-06 (Ollama health gate: skip+classify, no flood) |
| 8 | stale-basis pollution | **FIXED** (10 invalidated, reversible) |
| 9 | per-row provenance | **FIXED+BACKFILLED** 2026-06-06 (exact backfill: strategy 4->2055, ti 4->28, provenance 100%; writer-side stamping; base-data-quality scorecard) |
| 10 | learning shadow-only | CONFIRMED |

## Safety proof
SELECT-only except the explicitly-requested, reversible review invalidation (#8, backed up). No trading/
GO-WAIT/strategy/broker/proposal/order/stop/live/Phase-205 changes. ALPACA_MODE=paper, live disabled.
