# Phase 213I — External-Researcher Feedback Loop + Loop Drill-Down (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:08:49-04:00
Measured at: efcc51365 / not measured

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

## Scheduled daily (2026-06-07, operator-approved)
`hermes-external-feedback.timer` (systemd user): OnCalendar=*-*-* 04:00 (Persistent, +≤5min jitter) →
oneshot `hermes-external-feedback.service` runs `hermes_external_feedback_loop.py --apply --model gemma3:4b`
(TimeoutStartSec=600). enabled+active; next run ~04:00 daily; first run success. Advisory-only; honors the
HERMES_DISABLED kill-switch. Units in ~/.config/systemd/user (untracked, per convention).
Operate: `systemctl --user status|disable hermes-external-feedback.timer`.
