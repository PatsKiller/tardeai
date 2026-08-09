# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-08-08T22:08:16.181260+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=12, no live-broker/secrets dirty files
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
  - `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`
- other untracked-by-policy: ['scripts/claude_escalation_handler.py', 'docs/architecture/cio/CIO_OPERATOR_COMMUNICATION_POLICY.md', 'docs/architecture/cio/CIO_QUALITY_METRICS.md', 'docs/architecture/cio/CIO_RUN_BUDGETS.md', 'docs/architecture/cio/PHASE_2_AUTHORITY_FINAL.md', 'docs/architecture/cio/PHASE_2_CANARY_MATRIX.md', 'docs/architecture/cio/PHASE_2_COST_REPORT.md', 'docs/architecture/cio/PHASE_2_FINAL_ACCEPTANCE.md', 'docs/architecture/cio/PHASE_2_RUNTIME_STATE.md', 'docs/operations/CIO_PRODUCTION_SCHEDULES.md', 'docs/operations/CIO_RESTART_PROCEDURES.md']

*Does not authorize live trading. Operator-approved path only.*
