# Page repair — Health `/ops/health`

Status: ACTIVE
as_of: 2026-10-25T20:40:00Z
Measured at: worktree wt/cursor-health-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/health.md
Authority: Ops redesign Board 0 (`OpsDeskFrame`); health snapshot API
Supersedes: none
See also: `OpsDeskFrame` `page="health"` → lanes `health-agent`, `postgres-main-watchdog`; PR #2126 for CioHub phone chrome

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage / source clocks | Board 0 ops frame | `OpsDeskFrame page="health" asOf={{ health: health?.captured_at }}` | OK (shell) | `HealthHub.tsx` ~L124 | Keep |
| Lane mapping | Writer lanes | `laneIds: ['health-agent','postgres-main-watchdog']` | OK (code) | `OpsDeskFrame.tsx` | Live verify |
| Health payload freshness | as_of from snapshot | `health?.captured_at` passed into frame | OK (code) | HealthHub fetch | Live verify |
| Phone / tabs | Usable mobile | Hub chrome may clip (shared CioHub issue) | LAYOUT | CioHub | **#2126** if observed on phone |
| Findings / degraded sections | Honest UNAVAILABLE | Sections render from health JSON | OK (code) | HealthHub | Flag empty-with-no-reason only after live probe |

| RiskHealthStrip Unprotected | Count true no-broker-stop (none+planned) | Was `!has_stop` (lumped pending/filled/unknown) | BROKEN → fixed | `HealthHub.tsx` `isNoBrokerStop` | This PR; switch to `stopDisplay.stopCategory` after #2141 merges |

## This PR

- Board-0 OpsDeskFrame wrap already present (docs).
- **Fix:** Unprotected strip uses none+planned only (inline mirror of #2141 taxonomy; `stopDisplay.ts` remains claimed by stop-desks).
- Live verification pending release.

Design: `health/v001` or `Design: none` until design workflow lands.
