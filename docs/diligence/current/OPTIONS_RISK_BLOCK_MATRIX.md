# Options Hard-Risk Block Matrix

_Generated: 2026-09-05T02:44:48.328399+00:00_  
_Source: `python3 tests/test_options_hard_risk_blocks_matrix.py` over `tests/fixtures/options_risk_blocks/_fixtures.json`_

Each row is a hard block enforced on the live options path by `options_desk_enterprise.evaluate_hard_risk_blocks`. Codes are a stable contract.

| Block code | Severity | Source | Verified reason (sample) | Snapshot keys |
|------------|----------|--------|--------------------------|---------------|
| `earnings_blackout` | hard | options_desk_enterprise | earnings in 3d | in_blackout, reason |
| `ex_dividend_cc_risk` | hard | options_desk_enterprise | ex-dividend within DTE for covered call | ex_div |
| `bs_estimate_only` | hard | options_desk_enterprise | Black-Scholes-only estimate — live chain required | data_source |
| `no_resolved_occ` | hard | options_desk_enterprise | no resolved OCC contract on proposal | — |
| `oi_below_threshold` | hard | options_desk_enterprise | OI 10 below 50 | pass, issues |
| `volume_below_threshold` | hard | options_desk_enterprise | volume 1 below 5 | pass, issues |
| `spread_too_wide` | hard | options_desk_enterprise | spread 30% too wide | pass, issues |
| `quote_stale` | hard | options_desk_enterprise | quote age 999s exceeds cap | quote_age_seconds |
| `option_chain_stale` | hard | options_desk_enterprise | chain age 9999s exceeds cap | chain_age_seconds |
| `market_closed` | hard | options_desk_enterprise | session=closed | — |
| `max_contracts_per_order` | hard | options_desk_enterprise | 999 > 5 | contracts |
| `max_per_strategy_notional` | hard | options_desk_enterprise | notional $9,999,999 exceeds strategy cap | notional, strategy |
| `assignment_exercise_risk` | hard | options_desk_enterprise | assignment/exercise risk flagged | assignment_risk |
| `min_buying_power` | hard | options_desk_enterprise | buying power $100 below minimum $5,000 | buying_power, min |
| `max_net_delta_pct` | hard | options_desk_enterprise | Net delta exposure ~1000.0% exceeds cap | net_delta_pct, cap |
| `max_symbol_notional_pct` | hard | options_desk_enterprise | Top symbol concentration 90.0% exceeds cap | top_sym_pct, cap |
| `custom_enterprise_block` | hard | options_desk_enterprise | policy | — |
