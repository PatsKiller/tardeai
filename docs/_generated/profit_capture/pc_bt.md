# Profit-Protection Rule Backtests — quality-gated (evidence only)

run_id: ppbt_auto_20260607  |  raw measurable: 34  |  trades with intrabar path: 31  |  gate: {'quality_gated': True, 'winners_only': True, 'min_bars_analyzed': 10, 'max_mfe_r': 20.0, 'require_planned_stop': True, 'reliable_floor': 20}

**No rule applied to live trading. Where a trade has a real intrabar path, premature-exit cost is PATH-MEASURED (estimate_quality=path_measured); otherwise it is a single-peak upper bound. Confidence uses reliable n, not raw n.**

| rule | scope | raw | qual | reliable | path | avoided$ | premature$ | net$ | estimate | conf | graft |
|------|-------|-----|------|----------|------|----------|------------|------|----------|------|-------|
| trail8_after_3R | giveback | 34 | 11 | 11 | 11 | 221.04 | 0.0 | 221.04 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| income_wide_trail8_after_3R | giveback | 5 | 1 | 1 | 1 | 0.0 | 0.0 | 0.0 | path_measured | insufficient | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| position_lock50_after_3R | giveback | 1 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 | upper_bound_single_peak | insufficient | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| swing_lock50_after_2R | giveback | 18 | 7 | 7 | 7 | 7.02 | 56.98 | -49.96 | path_measured | insufficient | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| partial_tp_2R | giveback | 34 | 11 | 11 | 11 | 38.45 | 142.35 | -103.9 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| partial_tp_1_5R | giveback | 34 | 11 | 11 | 11 | 92.97 | 230.11 | -137.14 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| scalp_partial_tp_1R | giveback | 7 | 3 | 3 | 3 | 0.0 | 143.22 | -143.22 | path_measured | insufficient | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| breakeven_after_1R | risk_control | 34 | 11 | 11 | 11 | 0.0 | 159.98 | -159.98 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| trail5_after_2R | giveback | 34 | 11 | 11 | 11 | 56.67 | 263.74 | -207.07 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| scalp_fast_trail3_after_1_5R | giveback | 7 | 3 | 3 | 3 | 0.0 | 280.35 | -280.35 | path_measured | insufficient | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| lock50_after_2R | giveback | 34 | 11 | 11 | 11 | 7.02 | 289.1 | -282.08 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| lock25_after_1_5R | giveback | 34 | 11 | 11 | 11 | 0.0 | 332.71 | -332.71 | path_measured | weak | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
