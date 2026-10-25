# Page repair — Pullback/MACD `/pullback-macd`

Status: ACTIVE
as_of: 2026-10-25T20:55:00Z
Measured at: worktree wt/cursor-pullback-macd-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/pullback-macd.md
Authority: Board 0 DeskPage; also Watch tab embed
Supersedes: none

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| Board 0 DeskPage + writer clocks | Required on standalone | `PullbackMacdHub.tsx` — no DeskPage | MISSING | page chrome | Follow-up UI PR |
| Watch embed | Same data | `embedded` prop | OK (code) | PullbackMacdHub | Keep both |

## This PR

Docs-only. Live verification pending.

Design: `pullback-macd/v001` or `Design: none`.
