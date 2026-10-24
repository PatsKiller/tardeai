# Health page: one finding population and verified repair evidence

Date: 2026-10-24. Owner: W4. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: preparatory source; shared DeskPage landing and final mobile proof pending.
Approved references: desks boards 0 and 16; site audit Health P2 items.

This continuation preserves W9's handed-off Health changes from `34139b362`.
It uses the same Health snapshot headline in Overview and Ops Command, keeps
other tabs available when a source fails, URL-syncs tabs, mounts the common Jobs
component and fetches tab-specific evidence only when that tab is visible.

`scripts/lib/health_surface.py` normalizes existing read models. It changes no
kill-switch state or collector score. A derived execution-state finding that
mirrors an already-reported kill switch becomes related evidence of the actual
control finding, so the control is counted once. Distinct controls and accounts
remain separate. The normalized population supplies the counts and headline.

Remediation history is read from the existing raw journals so adapters cannot
drop dry-run, mode or recheck fields. Preview/shadow/dry-run events cannot count
as repairs. A health-agent repair needs an explicit successful recheck; an
inspector repair needs verified evidence and no failed exit code. Exit zero
alone is unverified. Missing history yields unavailable counts; bounded or
partially unreadable history carries coverage gaps and lower-bound counts.

| UI element | API/field | Existing source | Writer |
| --- | --- | --- | --- |
| Overview / Ops Command counts | `/api/v2/health` `counts/headline/findings` | Health snapshot selected by existing dashboard; normalized once by `health_surface.get_health` | Health agent; read-only adapter |
| Jobs tab | `/api/v2/jobs-health` | Existing registry, run receipts and wrapper events | Same model as `/ops/jobs`; see W4_JOBS_HEALTH_20261024.md |
| Recorded events | `/api/v2/health/remediation` `stats.total_events_24h` | Raw agent/inspector journals, timestamp-filtered to the observed 24h | Health agent / inspector |
| Verified repairs | same, `stats.verified_fixes_24h` | `ok` + `verified_by_recheck`, or inspector `verified`; excludes preview modes | Same writers |
| Preview events | same, `stats.preview_events_24h` | `dry_run`, `mode`, or explicit command dry-run flag | Same writers |
| Verification rate | same, `stats.success_rate` | Verified real repairs / observed non-preview attempts | Read-only adapter |
| Coverage notice | same, `coverage.status/gaps` | Bounded raw journal reads; no mtime health inference | Read-only adapter |

The proposed API delegation hunks are kept separately for the W2 route owner.
The W5 frame must land before final frame integration. No publication readiness
or live UI acceptance is claimed by this preparatory checkpoint.
