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

---

## Momentum-scalp real-time carve-out (2026-07-08)

**Problem:** Operator stopped receiving live momentum-scalp GO/WAIT alerts (`social_scalp_scanner`)
around 2026-07-01. Root cause: the scanner's social-only + route-actionability gates (added 2026-06-27)
downgrade nearly all setups to WAIT, and the long-standing `suppress_wait: true` then dropped every WAIT
to `P2_DASHBOARD_ONLY` — so the operator saw nothing (GO went 1–6/day through 06-30 → 0 from 07-01).

**Fix:** `telegram_alert_router.classify_alert` now has a scalp carve-out *before* the WAIT sink: a
"Social Scalp Setup"/"Social Mention" message with `Score ≥ scalp_realtime_min_score` (default 25, /55)
returns `P0_INTERRUPT` (real-time); below the floor → dashboard-only. Config
(`operator_alert_policy.yaml → rules`): `scalp_realtime_enabled` (default true), `scalp_realtime_min_score`
(default 25). Scalp messages don't match `_GO_PATTERN`, so the 3/hour GO rate-limit does not apply. Volume
at the default floor is ~1–4 distinct symbols/day (measured), not a flood. Revert with
`scalp_realtime_enabled: false`; raise the floor to reduce volume.
