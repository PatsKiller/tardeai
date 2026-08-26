# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-08-26T17:50:58.111960+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=32, no live-broker/secrets dirty files
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
  - `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`
  - `docs/project/CI_EVIDENCE_LATEST.md`
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
- other untracked-by-policy: ['apps/command-center-v3/src/App.tsx', 'apps/command-center-v3/src/components/NavRail.tsx', 'docs/_evidence/r20-r24/MOCK_INVENTORY.json', 'docs/convergence/CONTROL_PLANE_API_V1_BASELINE.json', 'docs/convergence/UI_ROUTE_INVENTORY.json', 'scripts/control_plane_api.py', 'tests/test_r20_r24_qa_probes.py', '.githooks/', 'apps/command-center-v3/src/pages/control-plane/', 'docs/_evidence/r20-r24/HOST_RUNTIME_CHECKLIST.json', 'docs/_evidence/r20-r24/PARITY_REVIEW.json', 'docs/_evidence/r21/R21_1_HANDOFF_REVIEW.json', 'docs/_evidence/r22/REMAINING_MOCKS.json', 'docs/_evidence/r23/WORKSTREAM_HANDOFF.json', 'docs/_evidence/r24/WORKSTREAM_HANDOFF.json', 'docs/convergence/COMMAND_CENTER_CUTOVER_PLAN.md', 'docs/convergence/CONTROL_PLANE_API_V1_1.md', 'fixtures/control_plane/dry_run/', 'fixtures/control_plane/replay/', 'scripts/ai_local_acceptance.sh', 'tests/test_r20_r24_convergence.py', 'tests/test_r22_control_plane_fixtures.py', 'tests/test_r22_pages.py', 'tests/test_r23_control_plane_pages.py', 'tests/test_r23_side_by_side_boundary.py', 'tests/test_r24_audit_page.py', 'tests/test_r24_control_plane_guards.py', 'tests/test_r24_learning_page.py', 'tests/test_r24_maturity_page.py']

*Does not authorize live trading. Operator-approved path only.*
