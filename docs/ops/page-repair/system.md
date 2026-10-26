# Page repair — System `/system`

Status: ACTIVE
as_of: 2026-10-25T20:45:00Z
Measured at: worktree wt/cursor-system-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/system.md
Authority: Ops redesign Board 0 (`OpsDeskFrame page="system"`)
Supersedes: none
See also: `OpsDeskFrame` lanes `platform-maintenance-nightly`, `postgres-main-watchdog`, `portfolio-server-watchdog`; PR #2126 phone chrome

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage / source clocks | Board 0 ops frame | `OpsDeskFrame page="system" asOf={{}}` | OK (shell) | `SystemHub.tsx` ~L132 | Keep; enrich asOf from QCT when measured |
| Lane mapping | Writer lanes | `platform` + `server` laneIds in OpsDeskFrame | OK (code) | `OpsDeskFrame.tsx` | Live verify |
| Tabs (Overview / Pipeline / Brokers / …) | All present | `SYSTEM_TABS` + deep links | OK | `systemTabModel` | — |
| Empty asOf `{}` | Per-section clocks | Frame gets empty asOf object | PARTIAL | ~L132 | Flag: pass QCT / pipeline as_of when available (page-local follow-up) |
| Phone tabs / chrome | Usable at 412 | Shared CioHub / hub chrome | LAYOUT | hub chrome | **#2126** |
| Admin write controls | Guarded | AdminConfirmModal + token | OK (code) | Admin tab | Never call broker from System |

## This PR

Docs only. Board-0 wrap present. Live verification pending.

Design: `system/v001` or `Design: none` until design workflow lands.
