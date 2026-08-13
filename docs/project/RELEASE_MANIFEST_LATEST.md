# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-08-13T01:52:49.052056+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=23, no live-broker/secrets dirty files
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
  - `data/runtime/file_integrity_manifest.json`
  - `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`
- other untracked-by-policy: ['apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx', 'config/advisory_desk.yaml', 'config/agent_maturity_catalog.json', 'config/llm_process_registry.json', 'config/systemd/agent_runtime/README.md', 'config/systemd/agent_runtime/tradeai-agent-runtime@.service', 'config/systemd/user/cio-governed-bridge.service', 'config/systemd/user/tradeai-advisory-shadow-session.service', 'config/systemd/user/tradeai-holdings-agent-enqueue.service', 'docs/advisory/desk-v1/DATA_INTEGRITY_AUDIT_2026-08-12.md', 'scripts/agent_runtime/agents/definitions.py', 'scripts/agent_runtime/monitoring.py', 'scripts/agent_runtime_live_providers.py', 'scripts/api_v3_cio.py', 'scripts/deploy_portfolio_server.sh', 'scripts/gate_d_bundle_2_advisory_canary.py', 'scripts/lib/data_broker/advisory_desk.py', 'tests/test_agent_runtime_lane_d_agents.py', 'tests/test_agent_runtime_monitoring.py', 'tests/test_gate_b_suite.py', 'scripts/sync_cio_process_caps.py']

*Does not authorize live trading. Operator-approved path only.*
