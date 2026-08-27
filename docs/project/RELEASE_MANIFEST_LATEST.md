# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-08-27T22:32:54.769333+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=9, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   source-only mode: DB-state posture guards are proven by the deployed CI-equivalent run (docs/project/CI_EVIDENCE_LATEST.md), not this sandbox.
- [WARN] frontend_smoke: dist/index.html (run: npm --prefix apps/command-center-v3 run build)
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - (none)
- other untracked-by-policy: ['.github/workflows/cio-production-hardening-ci.yml', 'scripts/backfill_lineage_identity.py', 'scripts/health_agent.py', 'scripts/lib/cio_investment_product.py', 'scripts/lib/cio_notification_outbox.py', 'scripts/lib/cio_run_worker.py', 'scripts/check_dark_contracts.py', 'tests/test_checkin_dedupe.py', 'tests/test_remediation_map_integrity.py']

*Does not authorize live trading. Operator-approved path only.*
