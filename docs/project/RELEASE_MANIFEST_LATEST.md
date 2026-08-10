# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-08-10T15:19:50.318506+00:00_  
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
  - `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
- other untracked-by-policy: ['config/agent_maturity_catalog.json', 'scripts/cio_heartbeat.py', 'scripts/lib/cio_agent_handoff_queue.py', 'scripts/lib/cio_event_bus.py', 'scripts/lib/cio_financial_snapshot.py', 'scripts/lib/cio_run_worker.py', 'scripts/lib/data_broker/cio_portfolio.py', 'scripts/portfolio_stops.py', 'tests/test_gate_b_suite.py', '_c3c4_checkpoint_audit.py', 'config/cio_domain_capability_registry.json', 'scripts/lib/cio_action_validator.py', 'scripts/lib/cio_agent_readiness.py', 'scripts/lib/cio_domain_evidence.py', 'scripts/lib/cio_domain_registry.py', 'scripts/lib/cio_event_outbox.py', 'scripts/lib/cio_legacy_event_adapter.py', 'scripts/lib/cio_mutation_publisher.py', 'scripts/lib/cio_semantic_event_key.py']

*Does not authorize live trading. Operator-approved path only.*
