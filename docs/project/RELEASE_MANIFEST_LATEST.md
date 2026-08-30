# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-08-30T21:48:37.817726+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=9, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   source-only mode: DB-state posture guards are proven by the deployed CI-equivalent run (docs/project/CI_EVIDENCE_LATEST.md), not this sandbox.
- [PASS] frontend_smoke: command-center-v3 present, build script defined, dist/index.html built
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - (none)
- other untracked-by-policy: ['scripts/ai_local_acceptance.sh', 'scripts/lib/research_lane_health.py', 'scripts/run_cio_hardening_ci.py', 'config/lane_registry.json', 'docs/ops/LANE_REGISTRY_AND_RETIREMENT_CONVENTION.md', 'docs/ops/lane_retirement_annotations.proposed.txt', 'scripts/check_lane_registry.py', 'scripts/lib/lane_registry.py', 'tests/test_lane_registry.py']

*Does not authorize live trading. Operator-approved path only.*
