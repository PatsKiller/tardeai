# ALERT-2 — Telegram Proposal Callbacks

**Status:** COMPLETE

## Purpose

Adds safe Telegram callback handling so the operator can approve, reject, rebuild,
watch, or view details directly from Telegram. Paper-only. Blocked proposals cannot approve.

## Components

- **telegram_callback_policy.py** — Callback validation, action classification, gate checks
- **handle_telegram_proposal_callback.py** — Callback handler (dry-run default, --apply to execute)
- **telegram_proposal_alert_policy.py** — Updated with `/ptapprove` and `/ptreject` command shortcuts

## Callback Actions

| Action | When Allowed | Behavior |
|--------|-------------|----------|
| APPROVE_PAPER | Only if approval_allowed, gates pass, R:R >= 2.0, pending | Calls existing paper approval flow |
| REJECT | Pending proposals | Calls existing reject flow |
| REBUILD | Always | Logs rebuild request |
| WATCH | Always | Logs watch request |
| OPEN_DETAILS | Always | Returns UI link |

## DWSN Dry-Run Results

- **REBUILD**: ALLOWED (dry-run, would execute)
- **APPROVE_PAPER**: BLOCKED — price moved 14%, spread 14.8%, volume 1,873, execution blocked, R:R 1.95

## Safety

- Approval requires all Phase 6 gates to pass
- Blocked proposals never allow APPROVE_PAPER
- No live trading actions exist
- Token/secrets never in docs/logs
- Handler defaults to dry-run

## Tests

17/17 ALERT-2 + 15/15 ALERT-1 + 20/20 Q-1 regression.
