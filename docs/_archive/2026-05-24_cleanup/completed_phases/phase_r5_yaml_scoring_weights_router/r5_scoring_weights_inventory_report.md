# YAML Scoring Weights Inventory

With weights: 9 | Fallback: 14

| Strategy | Has Weights | Total | Keys |
|----------|-------------|-------|------|
| bond_income | No | 0 |  |
| cash_or_stable | No | 0 |  |
| core_growth_compounder | No | 0 |  |
| core_index | No | 0 |  |
| covered_call_income | No | 0 |  |
| defense_thesis | No | 0 |  |
| dividend_growth_compounder | No | 0 |  |
| earnings_catalyst | Yes | 100 | earnings_quality, options_activity, technical_setup, analyst_sentiment, catalyst |
| earnings_post_momentum | Yes | 100 | beat_magnitude, gap_hold_quality, guidance_direction, technical_setup, sector_alignment |
| earnings_pre_buildup | Yes | 100 | options_activity, analyst_revisions, technical_setup, catalyst_quality, earnings_history |
| fib_retracement_bounce | Yes | 100 | fib_level_precision, trend_strength, volume_pattern, rsi_quality, sector_alignment |
| gap_and_go | Yes | 70 | gap, rvol, catalyst, float, price_action |
| high_yield_income_bdc | No | 0 |  |
| income_add | Yes | 100 | dividend_safety, yield_quality, technical_entry, income_gap_impact, ssdi_impact |
| international_dividend | No | 0 |  |
| momentum_scalp | Yes | 55 | catalyst, rvol, price_action, float, price_range |
| recovery_watch | No | 0 |  |
| reit_income | No | 0 |  |
| sector_rotation | Yes | 100 | relative_strength, momentum, breadth, macro_alignment, volume |
| speculative_growth | No | 0 |  |
| swing_breakout | Yes | 100 | technical_setup, volume_pattern, sector_momentum, fundamental_quality, catalyst |
| swing_trade | No | 0 |  |
| tax_loss_harvest | No | 0 |  |