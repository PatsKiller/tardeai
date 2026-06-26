# Risk Gate Matrix

Hard blocks (live path): earnings_blackout, ex_dividend_cc_risk, bs_estimate_only, no_resolved_occ,
oi_below_threshold, volume_below_threshold, spread_too_wide, quote_stale, option_chain_stale,
market_closed, max_contracts_per_order, max_per_strategy_notional, max_net_delta_pct,
max_symbol_notional_pct, assignment_exercise_risk.

Configured in `assets/portfolio_intent.yaml` → `options_desk_settings.hard_risk_limits`.
