# Page repair — My questions `/cio/questions`

Status: ACTIVE
as_of: 2026-10-25T20:25:00Z
Measured at: worktree wt/cursor-cio-questions-20261025 @ 7a17113af base + this change; served pin not re-probed (MemoryCurrent / market-hours gate)
Canonical repo path: docs/ops/page-repair/cio-questions.md
Authority: Board 0 shared DeskPage pattern (desks-redesign-20261024); Ask CIO Screens 1–5
Supersedes: none
See also: `apps/command-center-v3/src/pages/MyQuestions.tsx`; lane `cio-ask-research`; e2e `my-questions-groups.spec.ts`

## Verdict table

No real portfolio values. Live column is **code audit + fixture e2e**; phone/desktop live verify pending release.

| Element (panel/tab/field) | Approved design says | Live shows (412 / 1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| DeskPage shell + source clocks | Board 0: title, purpose, writer/as-of clocks | Page had custom title only; no `DeskPage`, no `laneIds` | BROKEN | `MyQuestions.tsx` lacked DeskPage wrap | **This PR** — wrap + `laneIds: ['cio-ask-research']` + list `as_of` |
| Thread list + filter + group-by + channel | Screens for grouping / filter | Present; e2e covers 412/390 taps | OK (code) | `MyQuestions.tsx` + `askCioGroups` | Keep; live verify after release |
| Thread detail sheet (phone) | List → full-screen sheet with ← Back | `useAskPhoneSheet` + thread route | OK (code) | existing Ask sheet path | Live verify after release |
| Empty / error / stale | Gap shown as gap | Explicit empty, error, and stale copy | OK | list.error / list.stale / mq-empty | DeskPage `gap` now also carries error/stale |
| Theme group unavailable | Honest gap when theme not available | `mq-theme-gap` | OK | group_bys availability | Leave |
| Duplicate page title | One title (DeskPage) | Had inner h2 + subtitle | LAYOUT | Duplicate chrome | **This PR** — title/purpose moved to DeskPage |

## This PR

- Wrap `MyQuestions` in `DeskPage` with source `asks` → lane `cio-ask-research`.
- Prefer list payload `as_of`; fall back to newest thread `updated_at`.
- Page-repair doc. **Live verification pending release.**

Design: `cio-questions/v001` (Ask screens under desks-redesign; repo `design/pages/...` pending #2127) or `Design: none` until that path lands.

## INDEX note

`docs/ops/page-repair/INDEX.md` is held by the Approvals page-repair claim; update that row when that claim releases or in a follow-up docs PR.
