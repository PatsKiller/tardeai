# ALERT-1 — Telegram Proposal Decision Alerts

**Status:** COMPLETE

## Purpose

Send Telegram alerts when proposals become actionable, blocked-but-rebuildable,
or require operator decision. Prevents missed opportunities like the DWSN case
where the proposal was promoted 30 minutes before the operator saw it.

## Components

- **telegram_proposal_alert_policy.py** — Alert classification, packet builder, message formatter
- **send_telegram_proposal_alert.py** — Sender (dry-run default, --send for delivery)
- **run_scheduled_proposal_alert_dispatcher.sh** — Cron wrapper with safety guards
- **rollback_alert1_telegram_cron.sh** — Removes only ALERT-1 cron entries

## Alert Types

| Type | Emoji | Actions |
|------|-------|---------|
| ACTIONABLE_READY | check | APPROVE_PAPER, REJECT, WATCH |
| NEEDS_OPERATOR_DECISION | ? | WATCH, REJECT, OPEN_DETAILS |
| BLOCKED_NEEDS_REBUILD | warning | REBUILD, REJECT, WATCH |
| BLOCKED_EXECUTION_FAILED | X | REBUILD, REJECT |

## DWSN Example (Dry-Run)

```
X Paper Proposal: DWSN
Strategy: momentum_scalp | BLOCKED EXECUTION FAILED
Sector: Energy
Catalyst: verified — DAWSON GEOPHYSICAL Q1 2026 RESULTS
Entry: $3.91 | Stop: $3.71 | Target: $4.30
R:R: 1.95:1 | Risk: $102 | Shares: 511
Blockers: Price moved 14%, Spread 14.8%, Volume 1873
Action: REBUILD
Approval blocked
```

## Safety

- Blocked proposals never show APPROVE_PAPER action
- Ready proposals show APPROVE_PAPER (paper only)
- Token/chat ID not in docs/logs
- No trades, no orders, no live execution
- Dispatcher checks ALPACA_MODE and LLM_DISABLE

## Integration

Alert hook wired into incubator_proposal_promoter — sends Telegram on promotion.
Duplicate suppression via hash key prevents spam.

## Tests

15/15 ALERT-1 + PROMOTE-1 15/15 regression.
