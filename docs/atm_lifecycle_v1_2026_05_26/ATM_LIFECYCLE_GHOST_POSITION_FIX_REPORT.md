# ATM Lifecycle — Ghost Position Data Quality Fix Report

**Date:** 2026-05-26  
**Commit:** `fee5289`  

## Executive Summary

The ATM Control Room was showing 29 "open" positions when only 13 are truly open.
16 positions had `exit_reason` set (stopped out, cancelled, closed in broker, duplicates)
but `exit_time` was NULL, causing them to appear as active operational exposures.
This inflated all dashboard counts and decision queues.

Fixed by adding `AND (exit_reason IS NULL OR exit_reason = '')` to all 5 open-position
queries in `api_v2.py`. This is a query-only fix — no positions were modified.

## Root Cause

The `paper_trades` table uses `exit_time IS NULL` as the canonical "open position" filter.
However, 16 positions were resolved (exited, cancelled, or duplicated) without recording
an `exit_time` timestamp. They had `exit_reason` set but no `exit_time`.

## Before / After

| Metric | Before | After |
|--------|--------|-------|
| Open positions | 29 | **13** |
| Time-stop overdue | 10 | **2** |
| Missing stops | 2 | **0** |
| Manual close review | 6 | **1** (INFU #9) |
| Overdue needing decisions | 10 | **0** active / 2 reviewed |

## Ghost Position Categories (16 removed from active view)

| Exit Reason | Count | Positions |
|-------------|-------|-----------|
| `cancelled_never_submitted_to_broker` | 2 | SMX #1, MNKD #2 |
| `position_closed_in_alpaca` | 3 | XMTR #3, EVC #4, FLYW #12 |
| `stop_hit` / `stop_hit_instant` | 4 | BLBD #16, FLYW #19, GCTS #22, FLYW #24 |
| `target_hit` | 2 | INFU #21, ASPN #27 |
| `duplicate_of_22` / `bogus_duplicate_no_exit_price` | 2 | GCTS #20, GCTS #23 |
| `order_canceled_by_alpaca` | 1 | EVC #6 |
| `orphan_duplicate_from_partial_fill_race` | 2 | AGNC #30, CMCSA #32 |

## Actually Open Positions (13)

| ID | Symbol | Strategy | Days | Stop | Account |
|----|--------|----------|------|------|---------|
| 5 | XMTR | swing_breakout | 0d | $72.49 | ALPACA_PAPER |
| 7 | INFU | swing_breakout | 0d | $7.97 | ALPACA_PAPER |
| 8 | INFU | swing_breakout | 0d | $7.97 | ALPACA_PAPER |
| 9 | INFU | earnings_catalyst | 15d | $7.97 | ALPACA_PAPER |
| 10 | FLYW | swing_trade | 0d | $16.63 | ALPACA_PAPER |
| 11 | FLYW | swing_trade | 0d | $16.63 | ALPACA_PAPER |
| 15 | BLBD | earnings_catalyst | 14d | $76.23 | TOS_PAPER |
| 17 | FLYW | swing_breakout | 0d | $16.63 | TOS_PAPER |
| 18 | FLYW | swing_breakout | 0d | $16.63 | ALPACA_PAPER |
| 26 | ASPN | swing_trade | 5d | $5.15 | TOS_PAPER |
| 28 | NWG | dividend_growth_compounder | 4d | $15.05 | TOS_PAPER |
| 31 | AGNC | reit_income | 0d | $9.71 | ALPACA_PAPER |
| 33 | CMCSA | dividend_growth_compounder | 0d | $23.61 | ALPACA_PAPER |

## Remaining Risks

1. **BLBD #15** (earnings_catalyst, 14d) and **INFU #9** (earnings_catalyst, 15d) are overdue intraday
2. **16 ghost positions** should have `exit_time` backfilled from broker data (future cleanup)
3. **INFU #9** is the sole remaining manual-close review item

## API Validation

| Endpoint | Field | Value | Status |
|----------|-------|-------|--------|
| /api/v2/atm/lifecycle | open_positions | 13 | PASS |
| /api/v2/atm/lifecycle | time_stop_overdue | 2 | PASS |
| /api/v2/atm/lifecycle | stop_missing_count | 0 | PASS |
| /api/v2/atm/lifecycle | stale_proposals | 27 | PASS |
| /api/v2/atm/overdue-decisions | needs_decision_count | 0 | PASS |
| /api/v2/atm/overdue-decisions | reviewed_count | 2 | PASS |
| /api/v2/atm/manual-close-review | count | 1 (INFU #9) | PASS |

## Screenshot

`screenshots/atm_control_room_ghost_fix.png`

## Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| ATM mode | not changed |
| Orders placed | NONE |
| Positions modified | NONE |
| Proposals expired by this task | NONE |

## Rollback

```bash
git revert fee5289
```
