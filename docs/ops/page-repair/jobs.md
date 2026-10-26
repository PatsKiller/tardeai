# Page repair — Jobs `/ops/jobs`

Status: ACTIVE
as_of: 2026-10-25T20:40:00Z
Measured at: worktree wt/cursor-jobs-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/jobs.md
Authority: Ops redesign Board 0 (`OpsDeskFrame`); JobsHealth body
Supersedes: none
See also: `OpsDeskFrame` `page="jobs"` → lanes `jobs-health-tick`, `pipeline-health-monitor`; ReleasesSchedules jobs tab shares JobsHealth

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage / source clocks | Board 0 ops frame | `JobsPage` wraps `<OpsDeskFrame page="jobs"><JobsHealth /></OpsDeskFrame>` | OK (shell) | `JobsPage.tsx` L2–9 | Keep |
| Lane mapping | Writer lanes for jobs health | `laneIds: ['jobs-health-tick','pipeline-health-monitor']` | OK (code) | `OpsDeskFrame.tsx` | Live verify freshness from registry |
| JobsHealth body | Cadence / silence / receipt truth | Shared component (also Releases `?tab=jobs`) | OK (code) | `JobsHealth.tsx` | Flag data gaps only if live probe shows STALE/UNAVAILABLE without reason |
| Duplicate entry points | One jobs surface | `/ops/jobs` + Releases tab=jobs | LAYOUT / NOT NEEDED? | Product choice | Flag — do not remove without design |

## This PR

Docs only. No page-local UI change required for Board-0 shell (already present). Live verification pending.

Design: `jobs/v001` or `Design: none` until design workflow lands.
