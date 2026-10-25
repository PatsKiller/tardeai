# Page repair — Approvals `/approvals`

Status: ACTIVE
as_of: 2026-10-25T20:10:00Z
Measured at: origin/main 03ad8b71d (worktree); served pin still f009f7e75 — live operator verify blocked
Canonical repo path: docs/ops/page-repair/approvals.md
Authority: desks-redesign-20261024 Board 19 Approvals + PROMPT.md method
Supersedes: none
See also: PR #2132 (Designs + Decided recently), PR #2119 (403 fix, merged), PR #2117 (policy Approve on Rulebook)

## Verdict table

No real portfolio values. Descriptions by kind only. Live column is **code + known-problem audit** until the served release carries `#2119` (governance 403) and an agent-reader or sandbox login can probe at 412 / 390 / 1440.

| Element (panel/tab/field) | Approved design says | Live shows (412 / 1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| Page reachable for operator | Authenticated GET of Approvals Center | On served `f009f7e75`: governance routes 403 (duplicate `cc_auth` import) | BROKEN (served) | Fix merged as #2119; not yet on CURRENT | Release after `03ad8b71d` (or later) that includes #2119; then re-verify |
| Source clock — Approval queue | Desk source clock with writer lane + as-of | `Writer not identified for this source` (no `laneIds`) | BROKEN | `ApprovalsHub.tsx` sources omit `laneIds` (~L27–28) | Page-local follow-up **after** #2132 merges (that PR edits the same file); candidate lanes: `approval-package-reminder` / governance queue producer — confirm before wiring |
| Tab: Designs | Operator-approved design queue (Board 19) | DESIGN tab present; queue empty / no design lifecycle UI | MISSING | Design decisions read model + UI not on main | **PR #2132** — do not duplicate |
| Aside: Decided recently | Board 19 rich “Decided recently” panel | Thin list of recent decisions + link to history | MISSING / PARTIAL | `ApprovalsHub.tsx` ~L56–57 placeholder | **PR #2132** `DecidedRecently.tsx` — do not duplicate |
| Tab: Conflicts | Conflict-kind approvals; AI rule proposals deep-link to `/conflicts/rules` | Tab + rule-proposal link exist in code | OK (code) | `isRuleProposal` + governed_href | Keep; live verify after release |
| Decision history tab | Full history | Present; times via `toLocaleString()` (zone not forced ET) | LAYOUT / STALE risk | `ApprovalsHub.tsx` history render | Follow-up: ReadableTime / ET label after #2132 |
| Notify me panel | Delivery + schedule verified | “have not been verified yet” gap copy | OK (honest gap) | Intentional gap string | Leave until notify path measured |
| Waiting / Policy / Releases / Spend / Activations / Financial tabs | Kind-filtered queues | Tabs declared; filtering by `kind` | OK (code) | `tabs` + query `kind=` | Live verify after release |

## Blockers (this PR does not change UI)

1. **Served pin** still `f009f7e75` while assignment gate is “after release `03ad8b71d` is live”. `#2119` is merged; promote/release is coordinator-owned.
2. **PR #2132** owns Approvals → Designs lifecycle and Board 19 Decided recently (`ApprovalsHub.tsx` + new components). Cursor must not edit those files while that PR is open.
3. **Source-clock `laneIds`** for the Approval queue is a page-local fix that collides with #2132’s file set — schedule after #2132 merges (or land as a review comment on #2132 if the author can add `laneIds` in the same PR).

## This PR

Docs only: records the audit and ownership so the page is not re-worked in parallel. **Live verification pending release.**

Design: `approvals/v001` (Board 19 under desks-redesign-20261024; repo `design/pages/...` pending #2127).
