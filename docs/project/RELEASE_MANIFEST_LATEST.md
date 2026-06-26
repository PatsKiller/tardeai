# Release Manifest (auto-generated)

Status: FAIL

- [FAIL] repo_hygiene_report: 6 live-broker/execution-adjacent dirty files; dirty_count=57
- [FAIL] python3 scripts/validate_metric_consistency.py --strict: WARN apps/command-center-v3/src/pages/StrategyHub.tsx:139: formatter={(v: number) => [`${v}%`, 'Win Rate']} />
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [FAIL] python3 scripts/validate_schwab_write_policy.py:   20/26 guards green
- [WARN] command_center_v3_build: skipped or package.json missing
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [FAIL] python3 tests/test_no_broker_write_bypass.py: 5 passed, 1 failed
- [PASS] export_diligence_evidence: diligence export script present

*Does not authorize live trading. Operator-approved path only.*
