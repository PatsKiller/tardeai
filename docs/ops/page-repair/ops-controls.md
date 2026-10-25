# Page repair — Ops Controls `/ops/controls`

Status: ACTIVE
as_of: 2026-10-25T20:40:00Z
Measured at: worktree wt/cursor-ops-controls-20261025 @ 7a17113af; code read; claim conflict with open PR #2124
Canonical repo path: docs/ops/page-repair/ops-controls.md
Authority: Ops redesign Board 0; CURSOR_ASSIGNMENT known problem “phone clip”
Supersedes: none
See also: **PR #2124** (`cursor/ops-controls-repair` — owns `OpsControls.tsx` UI); PR #2126 (CioHub phone/lane);

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| OpsDeskFrame + lane clocks | Board 0 frame | `OpsDeskFrame page="controls"` → `laneIds: ['control-applier']`; `asOf.applier` from heartbeat | OK (shell) | `OpsDeskFrame.tsx` + `OpsControls.tsx` ~L962 | Keep |
| Phone clip / mobile layout | Usable on phone | Known problem: phone clip | BROKEN / LAYOUT | CioHub phone + page chrome | **#2126** (phone); page-local layout → **#2124** |
| Controls / applier UI | Actionable ops controls | Large surface; open repair PR already claims `OpsControls.tsx` | CONFLICT | Parallel claim | **Defer UI to #2124** — this agent does not edit `OpsControls.tsx` |
| Source clocks vs “now” | Writer lanes, not wall clock | OpsDeskFrame SourceClocks for `control-applier` | OK (code) | Board 0 | Live verify after #2124 |

## This PR

Docs only. **Do not touch `OpsControls.tsx` while #2124 holds the claim.** Phone tabs → #2126.

Design: `ops-controls/v001` or `Design: none` until design workflow lands.
