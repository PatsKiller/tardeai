# ATP-ALERT-1 — Missed Proposal Telegram Escalation

**Status:** COMPLETE

## Problem

CODX moved from $2.15 to $2.43, crossing its $2.36 target while sitting in NEEDS_REVIEW with no Telegram alert. No script checked `current_price >= target` for pending proposals.

## Fix

1. **Alert evaluator** (`run_atp_alert_evaluator.py`):
   - target_crossed_before_review (URGENT)
   - large_move_before_review (HIGH) — >5% move from entry
   - stop_crossed_pending (URGENT)
   - Dedupe prevents spam
   - Safety footer on every message

2. **Q-1C integration**: Alert evaluator runs after every successful quote writeback. CODX-style conditions generate immediate URGENT Telegram.

3. **Dry-run verified**: CODX correctly produces `target_crossed_before_review [URGENT]`

## No Approval Bypass

Alerts are review-only. They do not approve, trade, or order. Approval gates remain intact.

## Tests

12/12 pass.
