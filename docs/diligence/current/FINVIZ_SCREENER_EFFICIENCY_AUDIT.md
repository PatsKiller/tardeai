# Finviz Screener Efficiency Audit

**Status: PASS** | 34 screeners | window 30d  
_Generated: 2026-06-29T15:51:57.501800+00:00_  

## Recommendations

| Action | Count |
|--------|------:|
| keep | 28 |
| reduce_cadence | 6 |
| merge_duplicate | 0 |
| disable_sunset | 0 |
| promote | 0 |

## Per-screener

| Screener | Family | Cadence class | Rows | Last run | Overlap | Conv 30d | Recommendation |
|----------|--------|---------------|-----:|----------|---------|---------|----------------|
| momentum_scalp_primary_gappers | momentum_scalp | scalp_fast | — | — | needs_data | needs_data | keep |
| momentum_scalp_low_price_active_gappers | momentum_scalp | scalp_fast | — | — | needs_data | needs_data | keep |
| momentum_scalp_intraday_continuation | momentum_scalp | scalp_fast | — | — | needs_data | needs_data | keep |
| swing_smallcap_quality_trend_extension | swing | swing_daily | — | — | needs_data | needs_data | keep |
| swing_smallcap_uptrend_pullback | swing | swing_intraday | — | — | needs_data | needs_data | keep |
| bond_etf_income | bond_income | income_weekly | 5423 | 2026-06-29 10:45 | needs_data | needs_data | reduce_cadence |
| core_compounder_value | core_growth_compounder | fundamental_daily | 182 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| quality_compounders | core_growth_compounder | fundamental_daily | 329 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| roth_growth | core_growth_compounder | fundamental_daily | 399 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| core_index_broad | core_index | fundamental_daily | 4083 | 2026-06-29 10:45 | needs_data | needs_data | reduce_cadence |
| covered_call_etf | covered_call_income | income_weekly | 5423 | 2026-06-29 10:45 | needs_data | needs_data | reduce_cadence |
| covered_call_rotation | covered_call_income | income_weekly | 747 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| etf_income | covered_call_income | income_weekly | 4083 | 2026-06-29 10:45 | needs_data | needs_data | reduce_cadence |
| defense_basket | defense_thesis | swing_daily | 89 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| defense_momentum | defense_thesis | swing_daily | 73 | 2026-05-19 12:23 | needs_data | needs_data | keep |
| div_growth_quality | dividend_growth_compounder | fundamental_daily | 104 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| dividend_aristocrats | dividend_growth_compounder | fundamental_daily | 728 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| dividend_growth | dividend_growth_compounder | fundamental_daily | 135 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| taxable_qualified_div | dividend_growth_compounder | fundamental_daily | 366 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| value_income | dividend_growth_compounder | fundamental_daily | 437 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| fib_retracement_targeted | fib_retracement_bounce | swing_intraday | 230 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| high_yield_bdc_reit | high_yield_income_bdc | income_weekly | 329 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| high_yield_income | high_yield_income_bdc | income_weekly | 6411 | 2026-06-29 10:45 | needs_data | needs_data | reduce_cadence |
| ira_income_friendly | high_yield_income_bdc | income_weekly | 6411 | 2026-06-29 10:45 | needs_data | needs_data | reduce_cadence |
| income_candidates | income_add | income_weekly | 522 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| intl_dividend | international_dividend | income_weekly | 380 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| recovery_candidates | recovery_watch | scout_intraday | 161 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| reit_income_scan | reit_income | income_weekly | 188 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| sector_leaders | sector_rotation | swing_daily | 720 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| speculative_catalyst | speculative_growth | scout_intraday | 11 | 2026-06-29 09:15 | needs_data | needs_data | keep |
| tactical_momentum | speculative_growth | scout_intraday | 88 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| swing_breakout_targeted | swing_breakout | swing_daily | 78 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| oversold_reversion | swing_trade | swing_intraday | 2647 | 2026-06-29 10:45 | needs_data | needs_data | keep |
| swing_momentum | swing_trade | swing_intraday | 826 | 2026-06-29 10:45 | needs_data | needs_data | keep |

> Read-only efficiency audit. Overlap/conversion metrics need the membership+attribution join (flagged needs_data); recommendations are conservative — no scalp screen is auto-sunset. Discovery only; no broker writes.

