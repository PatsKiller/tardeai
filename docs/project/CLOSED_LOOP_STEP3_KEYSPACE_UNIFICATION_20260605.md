> **Canonical model note:** Paper trades are the first executable source and first backfilled source. The canonical learning loop is all-trades, broker/account neutral (`trade_instances`). `paper_trade_id` is a compatibility key; `trade_instance_id` is the canonical key going forward. See `CLOSED_LOOP_ALL_TRADES_ABSTRACTION_20260606.md`.

# Closed-Loop Step 3 — Keyspace Unification (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T23:46:56-04:00
Measured at: efcc51365 / not measured

## Broken join fixed
journal_trade_reviews + trade_backtest_results were keyed only to `trade_key` (SYMBOL:account:date) of the
imported **Schwab** ledger; paper_trades used a numeric id → two disconnected keyspaces, paper loop uncovered.

## Changes (additive, reversible)
1. **paper_trades.trade_key** (TEXT) = `SYMBOL:account:CLOSE_date` (fallback entry date for open) — same
   convention as journal/backtest. Backfilled all 51 rows; maintained by `unify_trade_keyspace.py`.
2. **journal_trade_reviews.paper_trade_id** + **trade_backtest_results.paper_trade_id** (BIGINT) — added.
3. **Backtest engine** (`trade_backtest_engine.run_all`): source query now UNIONs closed paper_trades
   (ticker, entry>0) with `trade_closed`, carrying `paper_trade_id`; `upsert_result` writes it. → 42 paper
   trades now in backtest scope (was 0). Verified end-to-end: INFU (paper_trade_id=55) backtested,
   trade_backtest_results row written with paper_trade_id=55, data_quality=full.
4. **Journal write endpoint** (`api_v2.journal_review_write`): on insert, resolves+stamps paper_trade_id
   when the trade_key maps 1:1 to a paper_trade (Schwab-import reviews stay unlinked, as expected).

## Backfill / coverage
- paper_trades.trade_key: 51/51. trade_backtest_results linked to paper_trade: 1 (INFU; the rest populate
  on the next scheduled backtest run — read-only analysis). journal paper_trade_id: column present.
- unify backfill of existing journal/backtest rows linked 0 — correct: all existing rows are Schwab-import
  trades (no paper_trade), confirming the prior gap. Coverage now flows via the generator changes.

## Safety
ALPACA_MODE=paper, LLM live disabled. No broker order calls, no GO/WAIT, no strategy/proposal/order, no
Phase-205 changes. All schema additive; backtest source change is read-only analysis (no execution).

## Next step
Step 4: post-exit backtest comparison — on close, join the realized paper-trade outcome to its
proposal_backtest_snapshot and record edge-realized vs edge-expected.
