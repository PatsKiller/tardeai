# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-07-27T16:13:27.977164+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=13, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   source-only mode: DB-state posture guards are proven by the deployed CI-equivalent run (docs/project/CI_EVIDENCE_LATEST.md), not this sandbox.
- [WARN] frontend_smoke: dist/index.html (run: npm --prefix apps/command-center-v3 run build)
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`
  - `docs/project/CI_EVIDENCE_LATEST.md`
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
- other untracked-by-policy: ['config/active_trader.stage0.example.yaml', 'docs/implementation/ACTIVE_TRADER_CURRENT_GUARDRAILS.md', 'docs/implementation/ACTIVE_TRADER_ROUTE_API_DB_MAP.md', 'docs/implementation/ACTIVE_TRADER_STAGE0_BASELINE.md', 'scripts/active_trader/flags.py', 'scripts/active_trader/read_api.py', 'scripts/moomoo/preflight.py', 'scripts/operator_packets/packet_f_moomoo_stage0.py', 'tests/test_active_trader_stage0.py', 'tests/test_moomoo_stage0_preflight.py']

*Does not authorize live trading. Operator-approved path only.*
