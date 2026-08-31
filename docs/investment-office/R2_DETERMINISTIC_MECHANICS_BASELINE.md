# R2 Deterministic Mechanics — Build Baseline

Status:      HISTORICAL
as_of:       2026-08-14T22:33:07-04:00
Measured at: efcc51365 / not measured

Isolated additive workstream. Not wired into live Alex / CIO / retrieval /
Telegram / reports / sizing. Authority remains `READ_ONLY_ADVISORY`.

- worktree: `/home/johnclaw/tradeai-wt-research-mechanics`
- branch: `feature/research-mechanics-r2`
- BASE_SHA: `c005551a1e5da5a8d3f46d9e3018bff9bd516e7c`
- REMOTE_MAIN_AT_START: `c005551a1e5da5a8d3f46d9e3018bff9bd516e7c`
- R1_MERGE_SHA: `c005551a1e5da5a8d3f46d9e3018bff9bd516e7c` (PR #312)

Off-limits (unchanged from R1 denylist; deferred to R4):

- `scripts/lib/cio_acceptance_v4.py`, `scripts/run_cio_acceptance.py`
- `scripts/lib/cio_strategy_knowledge.py`, `scripts/lib/cio_seasonality_engine.py`
- `scripts/lib/cio_command_center.py`, `scripts/lib/cio_capital_plan.py`
- `scripts/lib/cio_financial_truth_gate.py`, `scripts/lib/cio_freshness_materiality_gate.py`
- `apps/command-center-v3/**`, `docs/investment-office/RELEASE_MANIFEST*`
- deploy/release scripts
- `scripts/rag_retrieval.py`, `scripts/lib/advisory/kb_lessons.py`
- `scripts/agent_runtime/knowledge.py`, `scripts/lib/hermes_research_backend.py`

R3 Almanac and R4 live integration are not started.
