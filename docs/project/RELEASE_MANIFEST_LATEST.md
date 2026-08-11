# Release Manifest (auto-generated)

Status: FAIL

_Generated: 2026-08-10T22:35:40.149239+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=19, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [FAIL] python3 scripts/validate_schwab_write_policy.py:   24/26 guards green
- [PASS] frontend_smoke: command-center-v3 present, build script defined, dist/index.html built
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
- other untracked-by-policy: ['config/cio_domain_capability_registry.json', 'config/llm_process_registry.json', 'docs/atm_audit_2026_05_26/designer_review/alert_routing_direct_sender_audit.md', 'scripts/cio_wake_dispatch_entrypoint.py', 'scripts/lib/cio_advisory_schema.py', 'scripts/lib/cio_agent_readiness.py', 'scripts/lib/cio_governed_model_bridge.py', 'scripts/lib/cio_run_worker.py', 'scripts/lib/cio_wake_backlog_policy.py', 'scripts/lib/cio_wake_dispatcher.py', 'scripts/lib/cio_wake_jobs.py', 'tests/test_gate_d_advisory_contract.py', 'tests/test_gate_d_backlog_policy.py', 'tests/test_gate_d_terminal_closure.py', 'scripts/gate_d_bundle_2_advisory_canary.py', 'scripts/lib/cio_advisory_readiness.py', 'tests/fixtures/advisory_mock_outputs/', 'tests/test_gate_d_evidence_gate.py']

*Does not authorize live trading. Operator-approved path only.*
