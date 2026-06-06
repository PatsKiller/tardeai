# Closed-Loop Step 4 — Post-Exit Backtest (Edge) Comparison (2026-06-05)

## Gap fixed (from certification audit)
"No post-exit comparison of realized outcome vs the matched backtest cohort." Proposal-time backtest
snapshots existed (`proposal_backtest_snapshots`, 40% of closed trades) but were never compared to the
realized result after close.

## Change (additive, read-only analysis)
New table `paper_trade_edge_comparison` (UNIQUE per paper_trade_id) + `scripts/compute_edge_comparison.py`:
for each CLOSED paper_trade that had a proposal_backtest_snapshot, record
- expected edge: win_rate, avg_r, expectancy, sample_size, backtest_quality (from the snapshot);
- realized: outcome_verdict, r_multiple, pnl_pct, hold_time_min (from the paper_trade);
- `r_delta` = realized_r − expected_avg_r and an `edge_assessment`:
  `outperformed_backtest` (Δ>+0.25R) / `in_line_with_backtest` (±0.25R) / `underperformed_backtest`
  (Δ<−0.25R) / `no_expected_edge` (snapshot had no samples) / `phantom_no_outcome` (no real fill).
Idempotent upsert; runs post-close (on demand or cron). Never fabricates an expected edge.

## Result (17 closed trades with a snapshot)
- compared (real expected edge present): **2** — 1 in_line, 1 underperformed (CMCSA dividend_growth:
  expected +0.21R, realized −1.07R → Δ −1.28R, LOSS).
- no_expected_edge: **14** (snapshots were NO_DATA / INSUFFICIENT — the backtest had no historical
  samples at proposal time; flagged, not invented).
- phantom_no_outcome: **1** (no real fill).

The low "compared" count reflects upstream backtest-snapshot data quality (most snapshots are NO_DATA),
not a comparison bug. As the backtest corpus grows (Step 3 now feeds paper-trade backtests in), more
snapshots will carry a real expected edge and this comparison populates automatically.

## Safety
ALPACA_MODE=paper, LLM live disabled. No broker order calls, no GO/WAIT, no strategy/proposal/order, no
Phase-205 changes. Additive table + read-only analysis (no execution path touched).

## Next step
Step 5: persist shadow scores to a DB table keyed to the candidate, and set
proposal_outcome_chain.outcome_fed_back when a lesson/score is derived (close the loop-closure flag).
