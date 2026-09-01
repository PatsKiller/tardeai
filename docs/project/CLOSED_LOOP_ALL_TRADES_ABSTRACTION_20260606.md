# Closed-Loop All-Trades Abstraction (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T00:08:45-04:00
Measured at: efcc51365 / not measured

> **Canonical model note:** Paper trades are the first executable source and first backfilled source. The canonical learning loop is all-trades, broker/account neutral (`trade_instances`). `paper_trade_id` is a compatibility key; `trade_instance_id` is the canonical key going forward. See `CLOSED_LOOP_ALL_TRADES_ABSTRACTION_20260606.md`.

## Why
Steps 1–7 closed real gaps but centered on `paper_trades`. With Alpaca paper as the only executable
broker/account, paper-specific names (`paper_trade_id`, `paper_trade_edge_comparison`,
`closed_paper_trade`, `paper_trades.trade_key`) risked hardening as the canonical model. They must not.

## Canonical model
`trade_instances` (broker/account-neutral lifecycle): trade_uid, source_system, source_table,
source_trade_id, execution_broker/account/environment, trade_mode, symbol, strategy/signal/card/candidate/
proposal lineage, status/side/prices/pnl/r/hold, trade_key, lineage_confidence/source/notes.
UNIQUE(source_table, source_trade_id). `paper_trades.id` is just one source implementation.

## Backfill (353 instances)
- alpaca_paper 51 (from paper_trades; rich lineage — signal/execution/proposal)
- schwab_import 302 (from `trades` non-alpaca; lineage_confidence=imported_broker_statement)
- fidelity_import 0 (no closed-trade ledger rows yet — honest, not fabricated)
- lineage_confidence: exact (proposal-linked paper) / imported_broker_statement (schwab) / missing
- coverage: strategy_id 51, proposal_id 43, signal_id 14 (not fabricated for imports)

## Canonical links added (additive; legacy keys retained)
`trade_instance_id` on hermes_research_intelligence, journal_trade_reviews, trade_backtest_results,
paper_trade_edge_comparison, candidate_shadow_efficacy, candidate_shadow_scores, proposal_outcome_chain.
Backfilled: hermes 6, journal 15, backtest 92 (incl 58 imported), edge 43. Canonical
`trade_edge_comparison` (43) populated from paper_trade_edge_comparison.

## Hermes targeting (the behavioral fix)
`closed_paper_trade` → **`closed_trade_needing_reflection`**: queries `trade_instances` for any closed
trade (paper OR imported Schwab/Fidelity) with no reflection linked by trade_instance_id; sublabel by
source_system. Verified: targets now span schwab_import + alpaca_paper. Write-path stamps
trade_instance_id (+ legacy related_trade_id for paper). New journal/backtest writes also stamp it.

## Validation — 14/14 PASS (scripts/validate_all_trades_closed_loop.py)
Every paper_trade has an instance; imports represented (302); multi-source; hermes/journal/backtest/edge
linked by trade_instance_id; backtest covers imported trades (58); targeting is all-trades; closed_paper_trade
removed from canonical path; no order/GO-WAIT writes; paper mode/live disabled.

## Safety
Additive schema only; paper loop unchanged; no broker writes, no order/stop, no GO/WAIT, no strategy
threshold, no live enablement, no Schwab/Fidelity API, no Phase-205. Learning graft still gated (Step 6).

## Imported edge comparison (2026-06-06)
> Imported trades generally lack proposal-time expected edge. Their canonical edge comparison uses per-trade backtest evidence, not fabricated proposal snapshots.
Canonical `trade_edge_comparison` now 101 rows: alpaca_paper 43 (proposal-edge) + schwab_import 58 (per-trade-backtest). See `CLOSED_LOOP_IMPORTED_EDGE_COMPARISON_20260606.md`.

## Structured news linkage (2026-06-06)
News → trade_instance is now a structured FK (`trade_instance_news`, classified by lifecycle window) + summary counts on trade_instances — closing the cert audit news gap (was symbol/date-only). See `CLOSED_LOOP_NEWS_LINKAGE_20260606.md`.
