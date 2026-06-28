# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-06-28T03:30:31.998280+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=26, no live-broker/secrets dirty files
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
  - `docs/diligence/current/MATURITY_4_5_ACCEPTANCE.md`
  - `docs/diligence/current/MOMENTUM_SCALP_LIFECYCLE.md`
  - `docs/diligence/current/SCALP_LIFECYCLE_FUNNEL.md`
  - `docs/diligence/current/SCALP_LIFECYCLE_MATURITY.md`
  - `docs/diligence/current/SCALP_OUTCOME_LEARNING.md`
  - `docs/diligence/current/SOCIAL_SCALP_ROUTE_MATRIX.md`
- other untracked-by-policy: ['config/strategies/momentum_scalp.yaml', 'docs/CHANGELOG.md', 'scripts/atm_auto_approver.py', 'scripts/auto_proposal_generator.py', 'scripts/social_scalp_scanner.py', 'scripts/compute_scalp_lifecycle_maturity.py', 'scripts/migrate_discovery_trace_id.py', 'scripts/scalp_lifecycle_funnel_report.py', 'scripts/scalp_outcome_learning.py', 'scripts/social_route_policy.py', 'scripts/strategy_config_validator.py', 'tests/test_momentum_scalp_config_consistency.py', 'tests/test_momentum_scalp_expiry_enforced.py', 'tests/test_momentum_scalp_liquidity_unknown.py', 'tests/test_scalp_lifecycle_funnel_report.py', 'tests/test_scalp_lifecycle_maturity.py', 'tests/test_scalp_outcome_learning.py', 'tests/test_social_route_policy.py', 'tests/test_social_scalp_decision_alerts.py', 'tests/test_social_traceability.py']

*Does not authorize live trading. Operator-approved path only.*
