# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-09-30T01:50:45.713501+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=7, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   27/27 guards green
- [WARN] frontend_smoke: dist/index.html (run: npm --prefix apps/command-center-v3 run build)
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - `docs/project/RELEASE_MANIFEST_LATEST.md`
- other untracked-by-policy: ['linux_launchers/run_pg_backup.sh', 'scripts/lib/research_lane_health.py', 'scripts/ops/spine_llm_organic_metric.py', 'tests/test_research_lane_health.py', 'tests/test_spine_gaps_close_20260929.py', 'scripts/ops/stamp_organic_llm_volume.py']

*Does not authorize live trading. Operator-approved path only.*
