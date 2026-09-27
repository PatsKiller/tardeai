# Release Manifest (auto-generated)

Status: FAIL

_Generated: 2026-09-27T00:09:17.081237+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [PASS] repo_hygiene_report: working tree clean
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [FAIL] python3 scripts/validate_schwab_write_policy.py:   source-only mode: DB-state posture guards are proven by the deployed CI-equivalent run (docs/project/CI_EVIDENCE_LATEST.md), not this sandbox.
- [WARN] frontend_smoke: dist/index.html (run: npm --prefix apps/command-center-v3 run build)
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [FAIL] python3 tests/test_no_broker_write_bypass.py:   [PASS] schwab_transport calls execution_readiness
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - (none)
- other untracked-by-policy: none

*Does not authorize live trading. Operator-approved path only.*
