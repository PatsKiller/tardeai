# Page repair index (Command Center v3)

Status: ACTIVE
as_of: 2026-10-25T20:10:00Z
Measured at: origin/main 03ad8b71d; served pin f009f7e75 (lagging)
Canonical repo path: docs/ops/page-repair/INDEX.md
Authority: coordination/handoffs/codex-page-repair-20261025/PROMPT.md
Supersedes: none

Cursor assignment order: Approvals → Rulebook → Conflict rules → CIO / questions → Releases / Ops / Jobs / Health → System / Broker Access → Tier 2 N–Z.

| Page | Route | Verdict counts | PR | Status |
|---|---|---|---|---|
| Approvals | `/approvals` | BROKEN×2 (served 403; writer clock), MISSING×2 (Designs; Decided recently) → owned by release + #2132 | (this train) | BLOCKED — docs audit; live verify after release; UI → #2132 |
| Rulebook | `/policy` | pending | — | next |
| Conflict rules | `/conflicts/rules` | pending | — | queued |
| CIO Desk | `/cio` | pending | — | queued |
| My questions | `/cio/questions` | pending | — | queued |
| Releases & Schedules | `/system/releases` | pending | — | queued (#2120/#2134 data) |
| Ops Controls | `/system/ops-controls` | pending | — | queued (#2126 phone) |
| Jobs & health | `/ops/jobs` | pending | — | queued |
| Health | `/health` | pending | — | queued |
| System | `/system` | pending | — | queued |
| Broker Access | `/system/broker-access` | pending | — | queued (display only) |
| Tier 2 N–Z | various | pending | — | queued |

Not in this index (other agents): Home, Watch, Portfolio, Re-Entry, TradeInView, Tier 2 A–M, Risk, Defense, Stop Management.
