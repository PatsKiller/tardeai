# ALERT-FATIGUE-1 — Telegram Alert Routing Fix

**Date:** 2026-05-22
**Problem:** Repeated non-actionable proposal alerts every 2-5 minutes
**Fix:** Central router suppresses proposal noise from primary group

## What Changed

1. `telegram_alert_router.py` — Added P2 patterns for ATP REVIEW ALERT,
   STOP_CROSSED_PENDING, LARGE_MOVE_BEFORE_REVIEW, PROPOSAL_REJECTED/DENIED/
   DEFERRED/BLOCKED, dry_run decisions, and "No order submitted" messages

2. `proposal_alerter.py` — Gates send through central router before sending

3. `send_telegram_proposal_alert.py` — Gates send through central router

## Primary Group Now Receives ONLY

- TRADE_OPENED / ENTRY_FILLED
- TRADE_CLOSED / EXIT_FILLED
- STOP_HIT / STOP_FILLED
- TRAILING_STOP_HIT / TRAILING_STOP_FILLED
- CRITICAL_NEWS_AUTO_CLOSE

## Suppressed From Primary

- ATP REVIEW ALERT (all types)
- STOP CROSSED PENDING
- LARGE MOVE BEFORE REVIEW
- Approval: BLOCKED
- PROPOSAL REJECTED/DENIED/DEFERRED/EXPIRED
- dry_run_approved/rejected/deferred
- "No order submitted"
- "Paper mode" status messages

## Simulation: 14/14 passed
