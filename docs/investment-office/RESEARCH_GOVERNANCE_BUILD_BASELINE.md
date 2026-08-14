# Research Governance — Build Baseline

Parallel workstream (book/research knowledge infusion) isolated from the
production-hardening CIO remediation agent.

- branch: `feature/research-governance-v1`
- worktree: `/home/johnclaw/tradeai-wt-research-governance`
- base_sha: `9783faf1c1e8ef89a52d5e1e6d4e676669a776af`
- base captured at worktree creation (2026-08-14, live `origin/main`)
- authority: `READ_ONLY_ADVISORY`

Rule: `origin/main` is moving under the parallel remediation agent. Re-read it
at any rebase/integration checkpoint; never trust a remembered SHA.

Off-limits (deferred to PR-R4 integration):
- scripts/lib/cio_acceptance_v4.py, scripts/run_cio_acceptance.py
- scripts/lib/cio_strategy_knowledge.py, scripts/lib/cio_seasonality_engine.py
- scripts/lib/cio_command_center.py, scripts/lib/cio_capital_plan.py
- scripts/lib/cio_financial_truth_gate.py, scripts/lib/cio_freshness_materiality_gate.py
- apps/command-center-v3/**, docs/investment-office/RELEASE_MANIFEST*, deploy/release scripts
- scripts/rag_retrieval.py, scripts/lib/advisory/kb_lessons.py,
  scripts/agent_runtime/knowledge.py, scripts/lib/hermes_research_backend.py
