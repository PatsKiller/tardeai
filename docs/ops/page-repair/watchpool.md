# Page repair — Watchpool `/watchpool`

Status: ACTIVE
as_of: 2026-10-25T20:55:00Z
Measured at: worktree wt/cursor-watchpool-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/watchpool.md
Authority: Board 0 DeskPage; also Watch tab embed
Supersedes: none

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| Board 0 DeskPage + writer clocks | Required on standalone | `WatchpoolHub.tsx` — no DeskPage | MISSING | page chrome | Follow-up UI PR |
| Watch embed | Same data | `embedded` prop | OK (code) | WatchpoolHub | Keep both entry points |

## This PR

Docs-only. Live verification pending.

Design: `watchpool/v001` or `Design: none`.
