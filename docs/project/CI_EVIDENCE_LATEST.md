# CI Evidence — Release Readiness Proof

**Status: PASS**  
_Generated: 2026-09-05T02:44:49.172885+00:00_  
_Source: `python3 scripts/run_release_ci_equivalent.py --json`_  
_Steps: 17 passed / 0 failed / 0 warn in 41.81s_

No broker writes are performed — every step is a read-only validator or test.

| Step | Status | Exit | Duration (s) | Command | Detail |
|------|--------|------|--------------|---------|--------|
| execution_state | PASS | 0 | 0.26 | `python3 scripts/execution_state.py --json` | } |
| release_readiness | PASS | 0 | 21.92 | `python3 scripts/validate_release_readiness.py --json --skip-build` | } |
| schwab_write_policy | PASS | 0 | 9.33 | `python3 scripts/validate_schwab_write_policy.py --source-only` |   source-only mode: DB-state posture guards are proven by th |
| no_broker_write_bypass | PASS | 0 | 8.37 | `python3 tests/test_no_broker_write_bypass.py` | 11 passed, 0 failed |
| execution_readiness | PASS | 0 | 0.3 | `python3 tests/test_execution_readiness.py` | 20 passed, 0 failed |
| evidence_bound_approval | PASS | 0 | 0.11 | `python3 tests/test_evidence_bound_approval.py` | 13 passed, 0 failed |
| intraday_window_fail_closed | PASS | 0 | 0.07 | `python3 tests/test_intraday_window_fail_closed.py` | 23 passed, 0 failed |
| order_lifecycle | PASS | 0 | 0.1 | `python3 tests/test_order_lifecycle.py` | 24 passed, 0 failed |
| reconcile_orders | PASS | 0 | 0.04 | `python3 tests/test_reconcile_orders.py` | 12 passed, 0 failed |
| audit_ledger | PASS | 0 | 0.26 | `python3 tests/test_audit_ledger.py` | 15 passed, 0 failed |
| options_hard_risk_blocks_matrix | PASS | 0 | 0.36 | `python3 tests/test_options_hard_risk_blocks_matrix.py` | 87 passed, 0 failed |
| options_hard_risk_blocks | PASS | 0 | 0.17 | `python3 tests/test_options_hard_risk_blocks.py` | 5 passed, 0 failed |
| llm_governance_no_override | PASS | 0 | 0.19 | `python3 tests/test_llm_governance_no_override.py` | 4 passed, 0 failed |
| kill_switches_status | PASS | 0 | 0.12 | `python3 scripts/brokers/kill_switches.py --status` | } |
| journal_ai_critique | PASS | 0 | 0.1 | `python3 tests/test_journal_ai_critique.py` | 25 passed, 0 failed |
| audit_ledger_coverage | PASS | 0 | 0.05 | `python3 scripts/audit_ledger.py --coverage --release-mode review --json` | } |
| frontend_smoke | PASS | 0 | 0.06 | `python3 -c import sys;sys.path.insert(0,'scripts');import validate_release_readiness as v;c=v.frontend_smoke();print(c.status,c.detail);sys.exit(0 if c.status!='FAIL' else 1)` | WARN dist/index.html (run: npm --prefix apps/command-center- |
