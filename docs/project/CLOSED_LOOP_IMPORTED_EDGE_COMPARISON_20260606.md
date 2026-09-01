# Closed-Loop Imported Trade Edge Comparison (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-05T23:59:40-04:00
Measured at: efcc51365 / not measured

> Imported trades generally lack proposal-time expected edge. Their canonical edge comparison uses per-trade backtest evidence, not fabricated proposal snapshots.

## Root gap (from all-trades cert re-audit)
Canonical `trade_edge_comparison` was paper-only (43 alpaca_paper rows). Imported Schwab trades had
per-trade backtests (`trade_backtest_results`, 58 linked by trade_instance_id) but were not feeding the
canonical edge table — because imports have no proposal-time `proposal_backtest_snapshot`.

## Implementation
`scripts/populate_imported_trade_edge_comparison.py` (additive, idempotent, --apply required). For each
CLOSED non-paper `trade_instance` with a linked `trade_backtest_results` row and no existing edge row:
- proposal_snapshot_id = NULL · expected_avg_r/win_rate = NULL (never fabricated)
- expected_edge_source = 'per_trade_backtest' · comparison_source = 'imported_trade_backtest'
- trade_backtest_result_id, realized_r (if any), realized_pnl_pct (if any)
- backtest_assessment + edge_assessment from entry/exit grade: entry_exit_optimal / better_entry_existed /
  exited_early / better_entry_and_early_exit / insufficient_backtest
- ON CONFLICT (trade_instance_id) DO NOTHING — never overwrites stronger proposal-edge (paper) rows.

## Results
- candidates: 58 (all schwab_import closed, backtested, no edge row) · written: 58
- trade_edge_comparison: 43 → **101** (alpaca_paper 43 + schwab_import 58)
- imported by assessment: better_entry_existed 22 · better_entry_and_early_exit 21 · exited_early 8 ·
  entry_exit_optimal 5 · insufficient_backtest 2
- realized: realized_pnl_pct populated from the import ledger; realized_r mostly NULL (imports lack
  r_multiple) — left NULL honestly; 9 rows have no realized fields at all.
- sample: ADBE(schwab) grade B better_entry_existed · AGMH(schwab) grade D better_entry_and_early_exit ·
  AMD(schwab) grade C exited_early.

## Proposal-edge vs per-trade-backtest comparison
- Paper rows: realized R vs proposal-time expected avg_r (edge_delta_r). Imported rows: no expected edge;
  the comparison is realized-entry/exit vs the historically-optimal entry/exit (better-entry / early-exit).
  Both are valid edge signals keyed on `trade_instance_id`; expected_edge_source distinguishes them.

## Validation (7/7 PASS — scripts/validate_trade_edge_comparison_all_trades.py)
imported represented 58; paper preserved 43; multi-source; 0 duplicate trade_instance_id; 0 fabricated
expected edge for imports; 58 per-trade-backtest comparisons; paper mode/live disabled.

## Safety
ALPACA_MODE=paper, live disabled. Writes only to trade_edge_comparison. No broker/order/stop/proposal/
GO-WAIT/strategy/live/Phase-205. No production learning graft.
