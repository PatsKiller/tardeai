# Release Manifest (auto-generated)

Status: WARN_NON_LIVE_ADJACENT

_Generated: 2026-06-28T02:06:46.182427+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=15, no live-broker/secrets dirty files
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
  - `docs/diligence/current/AUDIT_LEDGER_SAMPLE.jsonl`
  - `docs/diligence/current/AUDIT_LEDGER_STATUS.md`
  - `docs/diligence/current/BROKER_WRITE_GUARD_EVIDENCE.md`
  - `docs/diligence/current/CONTROL_MATRIX.md`
  - `docs/diligence/current/CURRENT_EXECUTION_STATE.md`
  - `docs/diligence/current/KILL_SWITCH_MATRIX.md`
  - `docs/diligence/current/MATURITY_4_5_ACCEPTANCE.md`
  - `docs/diligence/current/MATURITY_SCORE_LATEST.md`
  - `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`
  - `docs/diligence/current/ORDER_LIFECYCLE.md`
  - `docs/diligence/current/RELEASE_READINESS.md`
  - `docs/diligence/current/RISK_GATE_MATRIX.md`
  - `docs/diligence/current/TEST_EVIDENCE.md`
  - `docs/project/CI_EVIDENCE_LATEST.md`
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
- other untracked-by-policy: none

**Justification:** Remaining dirty files are regenerated evidence/runtime artifacts (diligence pack, runtime caches). No live-broker, secrets, or execution-adjacent source is dirty.

*Does not authorize live trading. Operator-approved path only.*
