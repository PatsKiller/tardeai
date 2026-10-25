# Page repair — Rulebook `/policy`

Status: ACTIVE
as_of: 2026-10-25T20:16:00Z
Measured at: origin/main 03ad8b71d (worktree); served pin still f009f7e75 — live operator verify blocked
Canonical repo path: docs/ops/page-repair/policy.md
Authority: Approvals Center / Rulebook boards + PROMPT.md method
Supersedes: none
See also: PR #2117 (in-app policy Approve / versions), PR #2119 (403 fix, merged), docs/ops/page-repair/approvals.md

## Verdict table

No real portfolio values. Live column is **code + known-problem audit** until the served release includes `#2119` and `/policy` can be opened as the operator at 412 / 390 / 1440.

| Element (panel/tab/field) | Approved design says | Live shows (412 / 1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| Page reachable for operator | Authenticated Rulebook | On served `f009f7e75`: governance 403 | BROKEN (served) | Same as Approvals — #2119 merged | Release / promote; then re-verify |
| Source clock — Committed policy | Writer + as-of for the committed document | Static gap only; **Writer not identified** | BROKEN | `PolicyHub.tsx` ~L43 — no `laneIds` / `asOf` | Follow-up **after** #2117 merges (that PR edits `PolicyHub.tsx`); candidate: document SHA as as-of + governance lane once named |
| Section filter + paged rules | Sections, 40-rule pages, plain words, evidence | Present in code | OK (code) | `PolicyHub.tsx` | Live verify after release |
| Agree / Question / Disagree | Record feedback; question → CIO; disagree → Approvals | Present; phone sheet ← Back | OK (code) | `PolicyHub.tsx` response sheet | Keep |
| In-app Approve version (AGENTS.md ratification) | Approve version X from CC | Not on main Rulebook surface | MISSING | Policy versions UI | **PR #2117** — do not duplicate |
| Enforcement audit panel | Last audit measured | “Not measured” / job link | PARTIAL | Audit producer cadence | Measure after release; job link → ops-controls |
| Evidence JSON dump in details | Readable evidence | Raw `JSON.stringify(rule.evidence)` | LAYOUT | `PolicyHub.tsx` evidence `<pre>` | Follow-up after #2117 (same file) — plain list, not raw JSON |

## Blockers (this PR does not change UI)

1. Served pin lag / `#2119` not promoted — same gate as Approvals.
2. **PR #2117** owns `PolicyHub.tsx` (Approve version + versions fixture). Do not edit that file while open.
3. Source-clock `laneIds` and evidence formatting collide with #2117’s file set — land after merge or as a review ask on #2117.

## This PR

Docs only. **Live verification pending release.**

Design: `policy/v001` (Rulebook boards under desks-redesign-20261024).
