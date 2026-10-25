# Page repair index (Command Center v3)

Status: ACTIVE
as_of: 2026-10-25T20:30:00Z
Measured at: local commits on wt/cursor-*-20261025; push/PR blocked until Cursor guardrails hooks sync to ledger v2
Canonical repo path: docs/ops/page-repair/INDEX.md
Authority: coordination/handoffs/codex-page-repair-20261025/PROMPT.md
Supersedes: none

Cursor assignment order: Approvals → Rulebook → Conflict rules → CIO / questions → Releases / Ops / Jobs / Health → System / Broker Access → Tier 2 N–Z.

| Page | Route | Verdict counts | PR | Status |
|---|---|---|---|---|
| Approvals | `/approvals` | BROKEN×2 (served 403; writer clock), MISSING×2 (Designs; Decided recently) → release + #2132 | local ee0b663a0 | BLOCKED push — docs audit; UI → #2132 |
| Rulebook | `/policy` | BROKEN writer clock; Approve path → #2117 | local d53565a57 | BLOCKED push — docs audit |
| Conflict rules | `/conflicts/rules` | BROKEN writer clocks (fixed locally); approval copy | local e22704081 | BLOCKED push — code+docs |
| CIO Desk | `/cio` | BROKEN cio-decision-engine lane → #2126; LAYOUT phone → #2126 | local 407503db9 | BLOCKED push — docs only |
| My questions | `/cio/questions` | BROKEN missing DeskPage/laneIds (fixed locally) | local ba5f18e73 | BLOCKED push — DeskPage wrap |
| Releases & Schedules | `/system/releases` | pending | — | next |
| Ops Controls | `/system/ops-controls` | pending (#2126 phone) | — | queued |
| Jobs & health | `/ops/jobs` | pending | — | queued |
| Health | `/health` | pending | — | queued |
| System | `/system` | pending | — | queued |
| Broker Access | `/system/broker-access` | pending (display only) | — | queued |
| Tier 2 N–Z | various | pending | — | queued |

Not in this index (other agents): Home, Watch, Portfolio, Re-Entry, TradeInView, Tier 2 A–M, Risk, Defense, Stop Management.

## Push blocker (all Cursor page-repair PRs)

`~/.cursor/hooks.json` → stale `tradeai-wt-cursor-guardrails` (ledger SCHEMA v1) cannot see live v2 grants (`git-push` / `deps` active in `bin/guard show`). Operator: sync that worktree’s hooks from hub or repoint hooks.json. Finding: agent-tmp `FINDING_stale_cursor_guardrails.md`.
