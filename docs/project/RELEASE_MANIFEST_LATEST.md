# Release Manifest (auto-generated)

Status: WARN

- [WARN] repo_hygiene_report: dirty_count=10, but no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   26/26 guards green
- [PASS] npm --prefix apps/command-center-v3 run build: ✓ built in 17.96s
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 6 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

*Does not authorize live trading. Operator-approved path only.*
