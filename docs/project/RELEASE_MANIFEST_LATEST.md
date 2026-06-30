# Release Manifest (auto-generated)

Status: WARN

_Generated: 2026-06-30T03:22:38.605932+00:00_  
_Source: `python3 scripts/validate_release_readiness.py --json`_

## Checks

- [WARN] repo_hygiene_report: dirty_count=11, no live-broker/secrets dirty files
- [PASS] python3 scripts/validate_metric_consistency.py --strict: Ambiguous label hits: 0
- [PASS] symbol_card_quality_validator: validator present; run with /api/v2/symbol-cards export during deployment
- [PASS] python3 scripts/validate_schwab_write_policy.py:   source-only mode: DB-state posture guards are proven by the deployed CI-equivalent run (docs/project/CI_EVIDENCE_LATEST.md), not this sandbox.
- [PASS] npm --prefix apps/command-center-v3 run build: ✓ built in 17.77s
- [PASS] frontend_smoke: command-center-v3 present, build script defined, dist/index.html built
- [PASS] python3 scripts/execution_state.py --json: }
- [PASS] execution_readiness: central readiness resolver present
- [PASS] python3 scripts/brokers/kill_switches.py --status: }
- [PASS] python3 tests/test_no_broker_write_bypass.py: 11 passed, 0 failed
- [PASS] export_diligence_evidence: diligence export script present

## Dirty-file classification

- live-adjacent (would FAIL): none
- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):
  - `docs/diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`
- other untracked-by-policy: ['config/hermes_research_budget.yaml', 'docs/CHANGELOG.md', 'docs/HERMES_GOVERNANCE_PANEL.md', 'docs/HERMES_RESEARCH_BUDGET_POLICY.md', 'docs/HERMES_RESEARCH_SCOPE_AUDIT.md', 'scripts/auto_research.py', 'scripts/iterate_research_topics.py', 'scripts/llm_router.py', 'scripts/migrate_synthesis_source_provenance.py', 'tests/test_hermes_paid_guard_and_provenance.py']

*Does not authorize live trading. Operator-approved path only.*
