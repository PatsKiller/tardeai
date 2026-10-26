# Page repair — Trading `/trading`

Status: ACTIVE
as_of: 2026-10-25T20:55:00Z
Measured at: worktree wt/cursor-trading-20261025 @ 7a17113af; code read
Canonical repo path: docs/ops/page-repair/trading.md
Authority: Board 0 DeskPage; display-only (never broker order routes)
Supersedes: none
See also: Broker Access deep-link for ATM Controls

## Verdict table

| Element | Approved design says | Live shows (code) | Verdict | Root cause | Fix / owner PR |
|---|---|---|---|---|---|
| Board 0 DeskPage + writer clocks | Required | `TradingHub.tsx` — no DeskPage | MISSING | page chrome | Follow-up UI PR |
| ATM Controls | On Broker Access | Link to `/system/broker-access#automation-controls` | OK | TradingHub | Keep |
| No order / broker write from page | Absolute | Display/read only | OK | AGENTS §0 | Never add order UI |

## This PR

Docs-only. Live verification pending.

Design: `trading/v001` or `Design: none`.
