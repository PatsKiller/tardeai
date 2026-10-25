# Page repair — CIO Desk `/cio`

Status: ACTIVE
as_of: 2026-10-25T20:25:00Z
Measured at: worktree wt/cursor-cio-20261025 @ 7a17113af; code read of `CioHub.tsx`; served pin not re-probed under MemoryCurrent / market-hours gate
Canonical repo path: docs/ops/page-repair/cio.md
Authority: desks-redesign-20261024 Board 17 (CIO Overview + Capital); PROMPT.md method
Supersedes: none
See also: PR #2126 (`CioHub.tsx` laneIds — removes wrong `cio-decision-engine` mapping); Home CIO record same PR

## Verdict table

No real portfolio values. Live column is **code + in-flight PR ownership** until #2126 releases and phone/desktop can be re-verified.

| Element (panel/tab/field) | Approved design says | Live shows (412 / 1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage + source clocks | Board 0 / 17: CIO evaluations + holdings clocks | `DeskPage` present; CIO evaluations `laneIds: ['cio-decision-engine']` → "Writer PAUSED" / wrong writer | BROKEN | `CioHub.tsx` ~L2155–2157 maps evaluations to paused lane | **PR #2126** — do not duplicate; Cursor must not edit `CioHub.tsx` while open |
| Overview / Capital tabs | Board 17 Overview + Capital | Tabs present (`overview`, `capital-policy`, Decisions, …) | OK (code) | `TABS` / `TAB_LABEL` in `CioHub.tsx` | Live verify after release |
| Phone chrome / tab row | One scrolling page; tabs not clipped under fixed chrome | Tab row clipped under fixed chrome (site-wide) | LAYOUT | Phone shell fixed chrome ~35–40% | **PR #2126** phone shell scroll |
| Conflicts strip on Overview/Capital | Honest conflict findings | `W7Conflicts` when `pageTruth` present | OK (code) | conditional render ~L2161 | Depends on conflict producer PRs (#2111/#2121/#2123) for live data |
| Holdings source | Writer identified | `schwab-position-sync` + `snaptrade-sync` laneIds | OK (code) | sources array | Live verify freshness after release |
| Decision gap copy | Point to Decisions tab | `decisionGap` set | OK | DeskPage prop | — |

## Blockers (this PR does not change UI)

1. **PR #2126** owns `CioHub.tsx` (lane mapping) and phone-shell scroll. Editing the same file here would conflict.
2. Live operator verify needs served release after #2126 + MemoryCurrent under 1.2 GB outside 04:00–16:15 ET Mon–Fri.
3. Conflict strip data quality is owned by conflict producer/resolver trains, not this page PR.

## This PR

Docs only: records the audit and ownership so CIO Desk is not re-worked in parallel. **Live verification pending release of #2126.**

Design: `cio/v001` (Board 17 under desks-redesign-20261024; repo `design/pages/...` pending #2127).

## INDEX note

`docs/ops/page-repair/INDEX.md` is held by the Approvals page-repair claim; update that row when that claim releases.
