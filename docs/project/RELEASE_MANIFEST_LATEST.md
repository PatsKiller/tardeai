# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-06-28T04:28:27.001709+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=21, no live-broker/secrets dirty files
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
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
  - `docs/diligence/current/MOMENTUM_SCALP_PAPER_PATH_DIAGNOSIS.md`
  - `docs/diligence/current/MOMENTUM_SCALP_VALIDATION_TRACKER.md`
- other untracked-by-policy: ['docs/CHANGELOG.md', 'scripts/compute_scalp_lifecycle_maturity.py', 'scripts/scalp_lifecycle_funnel_report.py', 'tests/test_scalp_lifecycle_funnel_report.py', 'tests/test_scalp_lifecycle_maturity.py', 'scripts/diagnose_momentum_scalp_paper_path.py', 'scripts/momentum_scalp_validation_tracker.py', 'scripts/scalp_trade_attribution.py', 'scripts/simulate_momentum_scalp_paper_path.py', 'tests/test_momentum_scalp_paper_path_diagnosis.py', 'tests/test_momentum_scalp_paper_path_simulator.py', 'tests/test_momentum_scalp_true_trade_attribution.py', 'tests/test_momentum_scalp_validation_tracker.py', 'tests/test_release_manifest_regenerated_clean.py']

*Does not authorize live trading. Operator-approved path only.*
