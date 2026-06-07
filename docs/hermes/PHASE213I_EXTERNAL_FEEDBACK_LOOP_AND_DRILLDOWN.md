# Phase 213I — External-Researcher Feedback Loop + Loop Drill-Down (2026-06-07)

## External-researcher feedback loop (closes self-learning gap #2)
`scripts/hermes_external_feedback_loop.py` (advisory, dry-run default, `--apply`): for each scored-eligible
`hermes_external_research` row (status=sent, usefulness_score NULL), rates usefulness 0–1 via local gemma3
(intrinsic actionability/specificity/grounding) enhanced by the symbol's realized pnl AFTER the research
date when available; writes `usefulness_score` + a note in `learning_candidate`; emits per-lane usefulness
aggregate. NEVER touches broker/scoring — the per-lane usefulness is advisory input to lane routing only.
Verified: AAPL=0.30, GCTS=0.70, grok avg=0.50. Run manually (schedule optional, operator-approved).

## Self-learning audit now includes it
`audit_hermes_self_learning_loops.py`: **11 loops** (added `external_researcher_feedback`), 9 feed prompts,
**0 mutate scoring** (still PARTIAL by design — scoring graft stays operator-gated). Gap #2 removed; remaining
gaps: research_backlog table, shadow-efficacy < graft sample.

## Loop drill-down (all loops)
Each loop in the audit carries `process_steps` + `status_col`. New endpoint
`GET /api/v2/hermes/loop-detail?loop=NAME` returns: process steps, counts (total/queued/completed/last),
and recent items with timestamps (id/status/symbol/etc). Command Center → System → Hermes →
"Self-Learning & Research Lanes" card now lists all 11 loops; click any loop to expand its steps,
queue/completed counts, and recent timestamped items. Read-only.
