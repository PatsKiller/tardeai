# Release Readiness

```json
{
  "blockers": [],
  "checks": [
    {
      "detail": "dirty_count=7, but no live-broker/secrets dirty files",
      "name": "repo_hygiene_report",
      "returncode": 0,
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
      "detail": "  26/26 guards green",
      "name": "python3 scripts/validate_schwab_write_policy.py",
      "returncode": 0,
      "status": "PASS"
    },
    {
      "detail": "skipped or package.json missing",
      "name": "command_center_v3_build",
      "returncode": null,
      "status": "WARN"
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
      "detail": "6 passed, 0 failed",
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
  "manifest_path": "docs/project/RELEASE_MANIFEST_LATEST.md",
  "notes": [
    "This gate is read-only.",
    "It does not authorize broker execution.",
    "A PASS means the repo is ready for review/release, not that live trading is enabled."
  ],
  "ok": true,
  "status": "WARN"
}
```
