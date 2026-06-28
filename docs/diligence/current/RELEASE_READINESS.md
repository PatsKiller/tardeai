# Release Readiness

_Generated: 2026-06-28T01:26:49.915661+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_  
**Status: WARN_NON_LIVE_ADJACENT**

Release readiness must be PASS or explicitly justified WARN with no live-adjacent dirty files.

```json
{
  "blockers": [],
  "checks": [
    {
      "detail": "dirty_count=15, no live-broker/secrets dirty files",
      "name": "repo_hygiene_report",
      "returncode": null,
      "status": "WARN"
    },
    {
      "detail": "Ambiguous label hits: 0",
      "name": "python3 scripts/validate_metric_consistency.py --strict",
      "returncode": 0,
      "status": "PASS"
    },
    {
      "detail": "validator present; run with /api/v2/symbol-cards export during deployment",
      "name": "symbol_card_quality_validator",
      "returncode": null,
      "status": "PASS"
    },
    {
      "detail": "  27/27 guards green",
      "name": "python3 scripts/validate_schwab_write_policy.py",
      "returncode": 0,
      "status": "PASS"
    },
    {
      "detail": "command-center-v3 present, build script defined, dist/index.html built",
      "name": "frontend_smoke",
      "returncode": null,
      "status": "PASS"
    },
    {
      "detail": "}",
      "name": "python3 scripts/execution_state.py --json",
      "returncode": 0,
      "status": "PASS"
    },
    {
      "detail": "central readiness resolver present",
      "name": "execution_readiness",
      "returncode": null,
      "status": "PASS"
    },
    {
      "detail": "}",
      "name": "python3 scripts/brokers/kill_switches.py --status",
      "returncode": 0,
      "status": "PASS"
    },
    {
      "detail": "11 passed, 0 failed",
      "name": "python3 tests/test_no_broker_write_bypass.py",
      "returncode": 0,
      "status": "PASS"
    },
    {
      "detail": "diligence export script present",
      "name": "export_diligence_evidence",
      "returncode": null,
      "status": "PASS"
    }
  ],
  "dirty_classification": {
    "live_adjacent": [],
    "other": [],
    "runtime_generated": [
      "docs/diligence/current/AUDIT_LEDGER_SAMPLE.jsonl",
      "docs/diligence/current/CONTROL_MATRIX.md",
      "docs/diligence/current/CURRENT_EXECUTION_STATE.md",
      "docs/diligence/current/KILL_SWITCH_MATRIX.md",
      "docs/diligence/current/ORDER_LIFECYCLE.md",
      "docs/diligence/current/RELEASE_READINESS.md",
      "docs/diligence/current/RISK_GATE_MATRIX.md",
      "docs/diligence/current/TEST_EVIDENCE.md",
      "docs/project/RELEASE_MANIFEST_LATEST.md",
      "docs/diligence/current/AUDIT_LEDGER_STATUS.md",
      "docs/diligence/current/BROKER_WRITE_GUARD_EVIDENCE.md",
      "docs/diligence/current/HEALTH_MONITORING_MATRIX.md",
      "docs/diligence/current/MATURITY_4_5_ACCEPTANCE.md",
      "docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md",
      "docs/project/CI_EVIDENCE_LATEST.md"
    ]
  },
  "generated_at": "2026-06-28T01:26:49.886485+00:00",
  "manifest_path": "docs/project/RELEASE_MANIFEST_LATEST.md",
  "notes": [
    "This gate is read-only.",
    "It does not authorize broker execution.",
    "PASS or WARN_NON_LIVE_ADJACENT means ready for review/release, not that live trading is enabled."
  ],
  "ok": true,
  "status": "WARN_NON_LIVE_ADJACENT"
}
```
