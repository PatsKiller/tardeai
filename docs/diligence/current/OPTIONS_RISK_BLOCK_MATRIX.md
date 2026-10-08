# Options Hard-Risk Block Matrix

_Generated: 2026-10-08T16:54:59.534431+00:00_  
_Source: `python3 tests/test_options_hard_risk_blocks_matrix.py` over `tests/fixtures/options_risk_blocks/_fixtures.json`_

Each row is a hard block enforced on the live options path by `options_desk_enterprise.evaluate_hard_risk_blocks`. Codes are a stable contract.

Modes: `live` blocks also apply to the desk's live-eligibility render; `submit` blocks fire only on the order path, where an ABSENT input fails closed (2026-09-27).

| Block code | Severity | Source | Verified reason (sample) | Snapshot keys | Mode |
|------------|----------|--------|--------------------------|---------------|------|
| `earnings_blackout` | hard | options_desk_enterprise | earnings in 3d | in_blackout, reason, cached_verdict_status | live |
| `ex_dividend_cc_risk` | hard | options_desk_enterprise | ex-dividend within DTE for covered call | ex_div | live |
| `bs_estimate_only` | hard | options_desk_enterprise | Black-Scholes-only estimate — live chain required | data_source | live |
| `no_resolved_occ` | hard | options_desk_enterprise | no resolved OCC contract on proposal | — | live |
| `oi_below_threshold` | hard | options_desk_enterprise | OI 10 below 50 | pass, issues | live |
| `volume_below_threshold` | hard | options_desk_enterprise | volume 1 below 5 | pass, issues | live |
| `spread_too_wide` | hard | options_desk_enterprise | spread 30% too wide | pass, issues | live |
| `quote_stale` | hard | options_desk_enterprise | quote age 999s exceeds cap | quote_age_seconds | live |
| `option_chain_stale` | hard | options_desk_enterprise | chain age 9999s exceeds cap | chain_age_seconds | live |
| `market_closed` | hard | options_desk_enterprise | session=closed (options trade in the regular session only) | market_session | live |
| `max_contracts_per_order` | hard | options_desk_enterprise | 999 > 5 | contracts | live |
| `max_per_strategy_notional` | hard | options_desk_enterprise | notional $9,999,999 exceeds strategy cap | notional, strategy | live |
| `assignment_exercise_risk` | hard | options_desk_enterprise | assignment/exercise risk flagged | assignment_risk | live |
| `min_buying_power` | hard | options_desk_enterprise | buying power $100 below minimum $5,000 | buying_power, min | live |
| `max_net_delta_pct` | hard | options_desk_enterprise | Net delta exposure ~1000.0% exceeds cap | net_delta_pct, cap | live |
| `max_symbol_notional_pct` | hard | options_desk_enterprise | Top symbol concentration 90.0% exceeds cap | top_sym_pct, cap | live |
| `custom_enterprise_block` | hard | options_desk_enterprise | policy | — | live |
| `quote_age_unknown` | hard | options_desk_enterprise | quote age unknown (no quote_time on the proposal's contract) | quote_time, quotes_as_of | submit |
| `chain_age_unknown` | hard | options_desk_enterprise | chain age unknown (no fetched_at on the chain this proposal  | chain_fetched_at | submit |
| `market_session_unknown` | hard | options_desk_enterprise | market session unknown (proposal carries no market_session) | — | submit |
| `buying_power_unknown` | hard | options_desk_enterprise | buying power unknown (no broker buying-power read on this pr | min | submit |
| `liquidity_unknown` | hard | options_desk_enterprise | no liquidity verdict on this proposal (enterprise.liquidity  | liquidity | submit |
| `market_closed` | hard | options_desk_enterprise | session=WEEKEND (options trade in the regular session only) | market_session | submit |
