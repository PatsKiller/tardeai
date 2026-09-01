# v3 LLM-Review Provenance Backfill (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T11:30:56-04:00
Measured at: efcc51365 / not measured

## Root cause
trade_llm_reviews rows lacked provenance: strategy_id 4/2105, account 4, trade_instance_id 4,
source_system 0, provenance_kind 0. So account/strategy filters were technically wired but returned
sparse/misleading data (the underlying rows had no lineage). Two populations: 2050 close_analysis reviews
(source=strategy_backtest_trades, backtest_trade_id set) and 51 structured_backtest_eval reviews
(source=trade_backtest_results, NO backtest_trade_id — only input_snapshot{symbol,open_date,close_date}).

## Exact backfill (no fuzzy mutation) — scripts/backfill_llm_review_provenance.py + llm_review_provenance.py
- A. close_analysis: backtest_trade_id -> strategy_backtest_trades -> strategy_id, account (simulation; no real trade_instance).
- B. structured_backtest_eval: input_snapshot(symbol,open_date,close_date) -> trade_backtest_results 1:1
  -> trade_instance_id (+ strategy/account from trade_instances). 1:1 guard; never fuzzy.
- C. paper reviews: paper_trade_id -> trade_instance.
- D. fill strategy/account/source from trade_instance for any linked row.
- Unlinkable rows labeled provenance_kind + 'unlinked_imported_or_simulation' (honest, not fabricated).
Additive cols: source_system, source_trade_id, execution_broker/environment, provenance_kind/confidence/
notes/backfilled_at.

## Before -> after
- strategy_id 4 -> 2055 · account 4 -> 384 · trade_instance_id 4 -> 28 · source_system 0 -> 2078 ·
  provenance_kind 0 -> 2105 (100%).
- by provenance: simulation/exact_backtest_trade 2050 · imported_backtest/exact_trade_instance 24 ·
  imported_backtest/unlinked 25 · paper/exact 4 · imported_backtest/exact_row_no_instance 2.

## Filter validation (Part C) — 6/6 PASS (validate_llm_review_provenance_filters.py)
AI Trade Eval account filter now partitions: all 51 -> schwab_rollover_ira 21, schwab_taxable 2,
alpaca_paper 1 (no longer silently global). 24/51 structured evals trade_instance-linked; 27 unlinked
(imports without an exact tbr match) labeled. Strategy filter still limited on imports (upstream lineage gap).

## Writer-side fix (Part D)
`trade_close_llm_analyzer.run_structured_eval` now calls `resolve_review_provenance(symbol,open,close)`
and stamps trade_instance_id/strategy_id/account/source_system/provenance_* at INSERT — future structured
evals are lineage-stamped from creation (no reliance on UI inference or later backfill).

## Remaining unlinked (honest)
25 structured evals have no exact trade_backtest_results match (no tbr row for that symbol+dates) and stay
unlinked-labeled. Schwab imports lack strategy_id upstream (trade_instances.strategy_id mostly null for
imports) so strategy filtering on imported reviews is limited until the import ledger carries strategy.

## Safety
ALPACA_MODE=paper, live disabled. Writes only trade_llm_reviews (exact joins). No broker/order/proposal/
GO-WAIT/strategy/live/Phase-205 changes.
