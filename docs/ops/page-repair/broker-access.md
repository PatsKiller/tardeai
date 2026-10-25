# Page repair — Broker Access `/system/broker-access`

Status: ACTIVE
as_of: 2026-10-25T20:45:00Z
Measured at: worktree wt/cursor-broker-access-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/broker-access.md
Authority: Ops redesign Board 0 (`OpsDeskFrame page="broker"`); display-only broker access read model
Supersedes: none
See also: `GET /api/v2/system/broker-access` (no broker call from page); AGENTS §0 / §24.11

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage / source clocks | Board 0 frame | `OpsDeskFrame page="broker" asOf={{ positions, stops: d?.as_of }}` | OK (shell) | `BrokerAccessPage.tsx` ~L120 | Keep |
| Lane mapping | Position + stop sync lanes | `laneIds: schwab-position-sync, portfolio-broker-reconciliation, broker-stop-reconcile` | OK (code) | `OpsDeskFrame.tsx` | Live verify |
| Read-only contract | No broker routes from UI | Payload from `/api/v2/system/broker-access`; comment forbids run-sync | OK | page header + API | Never add sync button without grant |
| Token / lock / freshness panels | Gaps with reason | State chips OK/STALE/DEGRADED/PAUSED/NEEDS_REAUTH + reasons | OK (code) | BrokerAccessPage | Live verify |
| Automation controls section | Moved from Trading ATM | `#automation-controls` + ATMControlPanel | OK | ~L116 | — |
| Inner h1 vs DeskPage title | Single title | Duplicate h1 | LAYOUT / NOT NEEDED | ~L123 | Flag for operator |
| Phone layout | No sideways scroll | Table overflowX auto | LAYOUT | tables | Soften at 412 in follow-up if live probe shows clip |

## This PR

Docs only. Display-only page; no broker calls. Live verification pending.

Design: `broker-access/v001` or `Design: none` until design workflow lands.
