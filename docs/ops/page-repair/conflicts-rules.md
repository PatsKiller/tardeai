# Page repair — Conflict rules `/conflicts/rules`

Status: ACTIVE
as_of: 2026-10-25T20:15:00Z
Measured at: worktree wt/cursor-conflicts-rules-20261025 @ 03ad8b71d; live API GET rulebook (served f009f7e75)
Canonical repo path: docs/ops/page-repair/conflicts-rules.md
Authority: conflict matrix page + PROMPT.md method; producers #2111 / #2110
Supersedes: none
See also: PR #2111 conflict-resolver, PR #2110 rule proposals, Watch conflict chips

## Verdict table

No real portfolio values. Live column mixes hermetic e2e + one GET of the public rulebook view (ledger gap only).

| Element (panel/tab/field) | Approved design says | Live shows (412 / 1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| Source clocks — rulebook / ledger | Desk clocks with writer lanes | No `laneIds` → “Writer not identified” | BROKEN | `ConflictRules.tsx` sources omitted `laneIds` | This PR — `conflict-resolver` |
| Source clock — AI proposals | Writer for proposal lane | Absent as a source | MISSING | Same | This PR — `conflict-rule-proposals` |
| Approval line in status banner | Plain words | Would `JSON.stringify` an object approval | BROKEN | `ConflictRules.tsx` Body banner | This PR — `approvalWords()` |
| Open conflicts / ledger counts | Live counts or honest gap | Gap: “conflict ledger not yet produced” | OK (honest gap) | Ledger producer not live | **PR #2111** (+ #2121/#2123) — do not duplicate |
| Proposed rules / decisions | Approve/edit/reject when store active | `decisions_enabled=false`; activation pending copy | OK (honest gap) | Proposal store not activated | **PR #2110** / activation — do not duplicate |
| Matrix rules / tiers / never-auto / scale / concentration / lifecycle | Full matrix in plain words | Present in view + e2e | OK (code) | `ConflictRules.tsx` Body | Keep; re-verify after release |
| Phone: one column, sheet ← Back, ≥44 px taps | Board mobile rules | e2e at 412/390 | OK (hermetic) | e2e `conflict-rules.spec.ts` | Live verify pending release |
| ET times on proposal sides | Readable ET, not raw ISO | `conflictTime` used | OK (code) | `watchConflictPresentation.conflictTime` | Keep |

## This PR

Page-local only: wire `laneIds`, plain-language approval, page-repair doc, unit + e2e assertions. Does not schedule `conflict-resolver` or activate proposal decisions.

Design: `conflicts-rules/v001` (matrix page; Design: none if no v001 folder yet — using page id `conflicts-rules`).

Live verification pending release (and after #2111 for writer clocks to show ACTIVE runs).
