# Risk Gate Matrix

_Generated: 2026-06-28T02:06:07.289854+00:00_  
_Source: `options_desk_enterprise.evaluate_hard_risk_blocks (see OPTIONS_RISK_BLOCK_MATRIX.md)`_  
**Status: PASS**

Hard blocks on the live options path. Full fixture-verified matrix with stable codes is in `OPTIONS_RISK_BLOCK_MATRIX.md`.

Hard block codes: earnings_blackout, ex_dividend_cc_risk, bs_estimate_only, no_resolved_occ,
oi_below_threshold, volume_below_threshold, spread_too_wide, quote_stale, option_chain_stale,
market_closed, max_contracts_per_order, max_per_strategy_notional, assignment_exercise_risk,
min_buying_power, max_net_delta_pct, max_symbol_notional_pct, enterprise_block.

Configured in `assets/portfolio_intent.yaml` → `options_desk_settings.hard_risk_limits` (+ env overrides).
