# Release Manifest (auto-generated)

Status: WARN

- [WARN] repo_hygiene_report: dirty_count=1, but no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   26/26 guards green
- [WARN] command_center_v3_build: skipped or package.json missing
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 6 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

*Does not authorize live trading. Operator-approved path only.*
