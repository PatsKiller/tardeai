# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-10-09T14:05:13.102927+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json --skip-build`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=13, no live-broker/secrets dirty files
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
  - (none)
- other untracked-by-policy: ['apps/command-center-v3/src/components/opportunity/OpportunityModal.tsx', 'config/opportunity_conviction.yaml', 'docs/INDEX.md', 'docs/ops/INVESTMENT_COMMAND_CENTER_2026-10-08.md', 'scripts/api_v2.py', 'scripts/api_v3_opportunities.py', 'scripts/cio_opportunity_curator.py', 'scripts/lib/data_broker/catalyst_record.py', 'scripts/lib/symbol_thesis_priority.py', 'scripts/run_cio_hardening_ci.py', 'scripts/run_symbol_thesis_acquisition.py', 'scripts/symbol_news_curation_monitor.py', 'tests/test_opportunity_actions_20261009.py']

*Does not authorize live trading. Operator-approved path only.*
