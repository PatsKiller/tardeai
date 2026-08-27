# Journal/Backtest Linkage Validation — 2026-05-29

## Table Relationship Map

```
paper_trade_proposals
  ├─ .paper_trade_id ──→ paper_trades.id (20 linked, no FK constraint)
  ├─ .outcome_trade_id ──→ paper_trades.id (5 linked, no FK constraint)
  ├─ .source_signal_id ──→ strategy_signals.id (logical)
  └─ proposal_* satellites (via proposal_id, no FK constraints)

paper_trades
  ├─ .proposal_id ──→ paper_trade_proposals.id (33 linked — 13 MORE than reverse)
  └─ source for /api/v2/automated-journal

trade_closed (no migration, imported externally)
  └─ source for /api/v2/journal, /api/v2/journal/report

trade_transactions (no migration, imported externally)
  └─ paired via paired_trade_transactions materialized view
  └─ feeds `trades` unified view

strategy_backtest_runs
  └─ .run_id (UNIQUE) ←── strategy_backtest_trades.run_id (JOIN, no FK)
  └─ .run_type distinguishes champion vs replay_trades vs replay_proposals

strategy_backtest_trades
  ├─ .run_id ──→ strategy_backtest_runs.run_id (JOIN, no FK)
  └─ NO source_trade_id linking back to originating paper_trades/trade_closed

trade_backtest_results
  └─ .trade_key (symbol:account:close_date) ──→ trade_closed (composite match, no FK)

lifecycle_trace
  ├─ .proposal_id ──→ paper_trade_proposals.id
  ├─ .paper_trade_id ──→ paper_trades.id
  └─ lifecycle_trace_events.trace_id ──→ lifecycle_trace.trace_id (ACTUAL FK)
```

## Validation Results

| Check | Result | Notes |
|-------|--------|-------|
| paper_trades → strategy_backtest_trades link | **WARN** | No source_trade_id FK. Only informal match by symbol+date+price |
| trade_transactions → backtest replay link | **WARN** | No FK. Enterprise backtester reads from trades view but doesn't store source row ID |
| proposals → backtests link | **WARN** | No FK. proposal_backtest_snapshots stores snapshot data, not a FK to strategy_backtest_trades |
| Missing FK constraints | **WARN** | All core relationships are logical-only, no database-enforced integrity |
| Orphan rows possible | **WARN** | 13 paper_trades have proposal_id not reflected in proposals.paper_trade_id |
| Journal P&L includes champion sims | **PASS** | Journal reads from trade_closed and paper_trades only, never strategy_backtest_trades |
| Automated journal includes champion sims | **PASS** | Reads from paper_trades only (api_v2.py:15412) |
| Journal backtest summary safe | **PASS** | trade_backtest_results populated from trade_closed only |
| Backtesting page implies sims are real | **WARN** | When "All Run Types" selected, no per-trade labeling distinguishes hypothetical from real |

## Missing Links
1. **No `source_trade_id` on strategy_backtest_trades** — cannot trace replay result → originating real trade
2. **No `source_proposal_id` on strategy_backtest_trades** — cannot trace replay result → originating proposal
3. **No FK constraints** on paper_trades.proposal_id, paper_trade_proposals.paper_trade_id, run_id joins
4. **Bidirectional inconsistency**: 33 paper_trades reference proposals but only 20 proposals reference paper_trades back
5. **trade_closed has no migration** — schema is inferred from queries
6. **trade_transactions has no migration** — purely import data with no relational links

## Champion Simulation Isolation
| Source | Champion-safe? | Method |
|--------|---------------|--------|
| /api/v2/journal | PASS | Reads trade_closed only |
| /api/v2/automated-journal | PASS | Reads paper_trades only |
| /api/v2/journal/report | PASS | Reads trade_closed only |
| /api/v2/journal/backtest-summary | PASS | Reads trade_backtest_results (from trade_closed) |
| /api/v2/backtesting/trades | WARN | Default filter=replay_trades is safe; "All" mixes |

## Is Journal Safe for Reporting?
**YES** — journal is clean. Journal P&L, win rates, and trade counts come exclusively from paper_trades and trade_closed. No strategy_backtest_trades rows contaminate journal metrics. Champion simulations are fully isolated in the backtesting subsystem.

## Is Backtesting Page Safe?
**MOSTLY** — default view (replay_trades) is clean. Mixed view ("All Run Types") lacks per-trade source labeling.

## Recommended Next Patches
1. Add `source_trade_id` / `source_proposal_id` columns to strategy_backtest_trades
2. Add FK constraints to core relationships (or at minimum, an orphan detection query in governance)
3. Reconcile bidirectional proposal/paper_trade ID links (13 orphans)
4. Add `is_hypothetical` or `source_type` enum to strategy_backtest_trades (currently inferred from broker IS NULL)
5. Track trade_closed and trade_transactions in migration system
