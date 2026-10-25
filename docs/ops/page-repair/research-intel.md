# Page repair — Research Intel `/research-intelligence`

Status: ACTIVE
as_of: 2026-10-25T20:55:00Z
Measured at: worktree wt/cursor-research-intel-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/research-intel.md
Authority: Board 0 DeskPage; CURSOR_ASSIGNMENT Tier 2
Supersedes: none

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| Board 0 DeskPage + writer clocks | Required | `ResearchIntelligenceHub.tsx` — own chrome, no DeskPage | MISSING | large hub | Follow-up UI PR (careful wrap) |
| Phone / memory | Prefer sandbox probe | Hermes-adjacent memory risk | — | PROMPT Hermes note | Do not heavy-probe |

## This PR

Docs-only. Live verification pending.

Design: `research-intel/v001` or `Design: none`.
