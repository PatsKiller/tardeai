# Ghost Position Data Quality Fix

**Date:** 2026-05-26  

## Discovery

Operator audit revealed that the ATM Control Room was showing 29 "open" positions
when only 13 are truly open. The system was using `exit_time IS NULL` as the sole
filter for open positions, but 16 positions had `exit_reason` set (indicating they
were closed, cancelled, stopped out, or duplicates) without a corresponding `exit_time`.

## Root Cause

The `paper_trades` table has positions where:
- `exit_time` is NULL (no timestamp recorded)
- But `exit_reason` is set (position is actually resolved)

These are **ghost positions** — they appear open but are not.

## Ghost Position Breakdown (16 total)

| exit_reason | Count | Examples |
|------------|-------|---------|
| `cancelled_never_submitted_to_broker` | 2 | SMX #1, MNKD #2 |
| `position_closed_in_alpaca` | 3 | XMTR #3, EVC #4, FLYW #12 |
| `stop_hit` / `stop_hit_instant` | 3 | BLBD #16, FLYW #19, GCTS #22 |
| `target_hit` | 2 | INFU #21, ASPN #27 |
| `duplicate_of_22` / `bogus_duplicate` | 2 | GCTS #20, GCTS #23 |
| `order_canceled_by_alpaca` | 1 | EVC #6 |
| `orphan_duplicate_from_partial_fill_race` | 2 | AGNC #30, CMCSA #32 |
| `stop_hit` (FLYW dividend) | 1 | FLYW #24 |

## Impact on Dashboard

| Metric | Before (ghost-inclusive) | After (fixed) |
|--------|------------------------|---------------|
| Open positions | 29 | **13** |
| Time-stop overdue | 10 | **2** |
| Missing DB stops | 2 | **0** |
| Manual close review | 6 | **1** (INFU #9) |
| Overdue decisions needing action | 10 | **2** (both reviewed) |

## Fix Applied

All 5 queries in `api_v2.py` that filter by `exit_time IS NULL` now also require
`(exit_reason IS NULL OR exit_reason = '')`.

## Remaining Data Hygiene

The 16 ghost positions should eventually have their `exit_time` backfilled from
broker data or set to the time the exit_reason was recorded. This is a future
cleanup task, not a safety issue — the dashboard now correctly excludes them.

## Safety

No positions modified. No orders placed. Query-only fix.
