# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-06-28T21:34:55.521605+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=18, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   27/27 guards green
- [PASS] frontend_smoke: command-center-v3 present, build script defined, dist/index.html built
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - `data/state/system_versions_latest.json`
- other untracked-by-policy: ['config/strategies/bond_income.yaml', 'config/strategies/cash_or_stable.yaml', 'config/strategies/core_growth_compounder.yaml', 'config/strategies/core_index.yaml', 'config/strategies/covered_call_income.yaml', 'config/strategies/defense_thesis.yaml', 'config/strategies/dividend_growth_compounder.yaml', 'config/strategies/earnings_post_momentum.yaml', 'config/strategies/fib_retracement_bounce.yaml', 'config/strategies/high_yield_income_bdc.yaml', 'config/strategies/international_dividend.yaml', 'config/strategies/recommendation_schema.yaml', 'config/strategies/reit_income.yaml', 'config/strategies/sector_rotation.yaml', 'config/strategies/strategy_schema.yaml', 'config/strategies/swing_breakout.yaml', 'config/strategies/tax_loss_harvest.yaml']

*Does not authorize live trading. Operator-approved path only.*
