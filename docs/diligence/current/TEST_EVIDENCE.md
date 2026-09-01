# Test Evidence

Status:      ACTIVE
as_of:       2026-06-27T22:07:55-04:00
Measured at: efcc51365 / not measured

_Generated: 2026-06-28T02:06:07.290359+00:00_
_Source: `python3 scripts/run_release_ci_equivalent.py --json (data/runtime/ci_evidence_latest.json)`_
**Status: PASS**

Read-only test + validator suite. Required scenarios: live globally prohibited, policy on / DB arm off, desk approval missing, quote stale after approval, kill switch after approval, LLM cannot override a hard block, no broker write bypass, release blocked by live-adjacent dirty file, like-to-like evidence hashes, intraday window fail-closed, reconciliation taxonomy.

```json
{
  "ok": true,
  "status": "PASS",
  "generated_at": "2026-06-28T01:59:47.506499+00:00",
  "total_steps": 17,
  "passed": 17,
  "failed": 0,
  "warned": 0,
  "total_duration_s": 79.49,
  "source_only": false,
  "steps": [
    {
      "step": "execution_state",
      "command": "python3 scripts/execution_state.py --json",
      "returncode": 0,
      "duration_s": 0.68,
      "status": "PASS",
      "optional": false,
      "detail": "}"
    },
    {
      "step": "release_readiness",
      "command": "python3 scripts/validate_release_readiness.py --json --skip-build",
      "returncode": 0,
      "duration_s": 36.43,
      "status": "PASS",
      "optional": false,
      "detail": "}"
    },
    {
      "step": "schwab_write_policy",
      "command": "python3 scripts/validate_schwab_write_policy.py",
      "returncode": 0,
      "duration_s": 18.12,
      "status": "PASS",
      "optional": false,
      "detail": "  27/27 guards green"
    },
    {
      "step": "no_broker_write_bypass",
      "command": "python3 tests/test_no_broker_write_bypass.py",
      "returncode": 0,
      "duration_s": 16.5,
      "status": "PASS",
      "optional": false,
      "detail": "11 passed, 0 failed"
    },
    {
      "step": "execution_readiness",
      "command": "python3 tests/test_execution_readiness.py",
      "returncode": 0,
      "duration_s": 1.42,
      "status": "PASS",
      "optional": false,
      "detail": "20 passed, 0 failed"
    },
    {
      "step": "evidence_bound_approval",
      "command": "python3 tests/test_evidence_bound_approval.py",
      "returncode": 0,
      "duration_s": 0.34,
      "status": "PASS",
      "optional": false,
      "detail": "13 passed, 0 failed"
    },
    {
      "step": "intraday_window_fail_closed",
      "command": "python3 tests/test_intraday_window_fail_closed.py",
      "returncode": 0,
      "duration_s": 0.23,
      "status": "PASS",
      "optional": false,
      "detail": "23 passed, 0 failed"
    },
    {
      "step": "order_lifecycle",
      "command": "python3 tests/test_order_lifecycle.py",
      "returncode": 0,
      "duration_s": 0.29,
      "status": "PASS",
      "optional": false,
      "detail": "24 passed, 0 failed"
    },
    {
      "step": "reconcile_orders",
      "command": "python3 tests/test_reconcile_orders.py",
      "returncode": 0,
      "duration_s": 0.14,
      "status": "PASS",
      "optional": false,
      "detail": "12 passed, 0 failed"
    },
    {
      "step": "audit_ledger",
      "command": "python3 tests/test_audit_ledger.py",
      "returncode": 0,
      "duration_s": 0.46,
      "status": "PASS",
      "optional": false,
      "detail": "12 passed, 0 failed"
    },
    {
      "step": "options_hard_risk_blocks_matrix",
      "command": "python3 tests/test_options_hard_risk_blocks_matrix.py",
      "returncode": 0,
      "duration_s": 2.02,
      "status": "PASS",
      "optional": false,
      "detail": "87 passed, 0 failed"
    },
    {
      "step": "options_hard_risk_blocks",
      "command": "python3 tests/test_options_hard_risk_blocks.py",
      "returncode": 0,
      "duration_s": 0.86,
      "status": "PASS",
      "optional": false,
      "detail": "5 passed, 0 failed"
    },
    {
      "step": "llm_governance_no_override",
      "command": "python3 tests/test_llm_governance_no_override.py",
      "returncode": 0,
      "duration_s": 1.07,
      "status": "PASS",
      "optional": false,
      "detail": "4 passed, 0 failed"
    },
    {
      "step": "kill_switches_status",
      "command": "python3 scripts/brokers/kill_switches.py --status",
      "returncode": 0,
      "duration_s": 0.29,
      "status": "PASS",
      "optional": false,
      "detail": "}"
    },
    {
      "step": "journal_ai_critique",
      "command": "python3 tests/test_journal_ai_critique.py",
      "returncode": 0,
      "duration_s": 0.27,
      "status": "PASS",
      "optional": false,
      "detail": "25 passed, 0 failed"
    },
    {
      "step": "audit_ledger_coverage",
      "command": "python3 scripts/audit_ledger.py --coverage --release-mode review --json",
      "returncode": 0,
      "duration_s": 0.19,
      "status": "PASS",
      "optional": true,
      "detail": "}"
    },
    {
      "step": "frontend_smoke",
      "command": "python3 -c import sys;sys.path.insert(0,'scripts');import validate_release_readiness as v;c=v.frontend_smoke();print(c.status,c.detail);sys.exit(0 if c.status!='FAIL' else 1)",
      "returncode": 0,
      "duration_s": 0.18,
      "status": "PASS",
      "optional": true,
      "detail": "PASS command-center-v3 present, build script defined, dist/index.html built"
    }
  ],
  "note": "Read-only CI-equivalent release proof. No broker writes performed."
}
```
