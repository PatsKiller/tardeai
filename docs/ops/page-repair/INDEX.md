# Page repair index (Command Center v3)

Status: ACTIVE
as_of: 2026-10-25T20:55:00Z
Measured at: local commits on wt/cursor-*-20261025; push/PR blocked until Cursor guardrails hooks sync to ledger v2
Canonical repo path: docs/ops/page-repair/INDEX.md
Authority: coordination/handoffs/codex-page-repair-20261025/PROMPT.md
Supersedes: none

Cursor assignment order: Approvals → Rulebook → Conflict rules → CIO / questions → Releases / Ops / Jobs / Health → System / Broker Access → Tier 2 N–Z.

| Page | Route | Verdict counts | Local head | Status |
|---|---|---|---|---|
| Approvals | `/approvals` | BROKEN×2 (served 403; writer clock), MISSING×2 (Designs; Decided recently) → release + #2132 | a721c3804 | BLOCKED push — docs; UI → #2132 |
| Rulebook | `/policy` | BROKEN writer clock; Approve → #2117 | d53565a57 | BLOCKED push — docs |
| Conflict rules | `/conflicts/rules` | laneIds + approval copy fixed | e22704081 | BLOCKED push — code+docs |
| CIO Desk | `/cio` | defer UI → #2126 | 407503db9 | BLOCKED push — docs |
| My questions | `/cio/questions` | DeskPage + laneIds fixed | ba5f18e73 | BLOCKED push — code |
| Releases & Schedules | `/system/releases` | Board-0 OK; train data → #2134 | ae01cc6ef | BLOCKED push — docs |
| Ops Controls | `/system/ops-controls` | UI → #2124; phone → #2126 | 48543301b | BLOCKED push — docs |
| Jobs & health | `/ops/jobs` | Board-0 OpsDeskFrame OK | 1d4e1839f | BLOCKED push — docs |
| Health | `/health` | Unprotected none+planned fix | fdb709936 | BLOCKED push — code+docs |
| System | `/system` | Board-0 OK; empty asOf PARTIAL | f98efef43 | BLOCKED push — docs |
| Broker Access | `/system/broker-access` | Board-0 OK; display-only | cb92fc0f2 | BLOCKED push — docs |
| Rec Intelligence | `/rec-intel` | MISSING DeskPage | 69accd1d1 | BLOCKED push — docs |
| Reports | `/reports` | MISSING DeskPage | d8a49d1d7 | BLOCKED push — docs |
| Research Intel | `/research-intelligence` | MISSING DeskPage | c824ee74a | BLOCKED push — docs |
| Research lineage | `/closed-loop` | MISSING DeskPage | f1b92c3c8 | BLOCKED push — docs |
| Rotation | `/rotation` | MISSING DeskPage | b26e6a83d | BLOCKED push — docs |
| Strategy | `/strategy` | DeskBoard OK (Board A) | 2067a6c9f | BLOCKED push — docs |
| Trading | `/trading` | MISSING DeskPage | 2f205c2b5 | BLOCKED push — docs |
| Watchpool | `/watchpool` | MISSING DeskPage | 477b4225e | BLOCKED push — docs |
| Sectors | `/sectors` | MISSING DeskPage | 153a90307 | BLOCKED push — docs |
| Pullback/MACD | `/pullback-macd` | MISSING DeskPage | 8a45db92f | BLOCKED push — docs |

Not in this index (other agents): Home, Watch, Portfolio, Re-Entry, TradeInView, Tier 2 A–M, Risk, Defense, Stop Management.

## Push blocker (all Cursor page-repair PRs)

`~/.cursor/hooks.json` → stale `tradeai-wt-cursor-guardrails` (ledger SCHEMA v1) cannot see live v2 grants (`bin/guard show` can list active `git-push`). Operator: sync that worktree’s hooks from hub or repoint hooks.json. Finding: `$TMPDIR/FINDING_stale_cursor_guardrails.md`. Fresh Telegram request `request_id=2c12915e852ae691` (git-push 2h/20 uses) still will not unlock Cursor shell until hooks read v2.
