# Page repair — Releases & Schedules `/system/releases`

Status: ACTIVE
as_of: 2026-10-25T20:40:00Z
Measured at: worktree wt/cursor-releases-20261025 @ 7a17113af; code read; live probe deferred (MemoryCurrent / market-hours)
Canonical repo path: docs/ops/page-repair/releases.md
Authority: Ops redesign Board 0 frame (`OpsDeskFrame`); PROMPT known problem “release train not measured”
Supersedes: none
See also: PR #2120 (merged data path), PR #2134 (watchdog + truthful release-train lane registry), `OpsDeskFrame` `page="releases"` → lane `release-train-claim`

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage / source clocks | Board 0 ops frame with writer lanes | `OpsDeskFrame page="releases"` with `laneIds: ['release-train-claim','n8n-pilot-dispatch']`; `asOf.train` from `generated_at` | OK (shell) | `OpsDeskFrame.tsx` + `ReleasesSchedules.tsx` ~L210 | Keep |
| Release train “not measured” | Measured train / receipts | Known problem: wrong lane mapping + run receipts not read | BROKEN (data) | registry / receipts | **#2120 / #2134** — do not duplicate page-local fiction |
| Next windows / queue / history sections | Freshness chip per section; UNAVAILABLE with reason | `Section` + `Fresh` + honest UNAVAILABLE copy | OK (code) | `ReleasesSchedules.tsx` | Live verify after #2134 |
| Tabs train / n8n / jobs | All present | Present | OK | `TABS` | — |
| Inner page h1 | Single title from DeskPage | Inner `<h1>Releases & schedules</h1>` duplicates DeskPage title | LAYOUT / NOT NEEDED | ~L213 | Flag for operator: keep until design says remove |
| STOP RELEASES control | On Coordination, not here | Comment + link pattern | OK | intentional | — |

## This PR

Docs only. UI/data owned by #2134 (+ #2120). **Live verification pending release.**

Design: `releases/v001` or `Design: none` until design workflow lands.
