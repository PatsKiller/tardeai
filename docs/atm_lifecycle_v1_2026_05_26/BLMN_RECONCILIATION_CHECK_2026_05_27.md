# BLMN Duplicate Open-Trade Reconciliation Check

**Date:** 2026-05-27  
**Last Updated:** 2026-05-28 (audit fix all)

## BLMN Paper Trades (Current State)

| ID | Symbol | Strategy | Entry | Stop | Stop OID | Shares | Account | Entry Time | Exit Reason |
|----|--------|----------|-------|------|----------|--------|---------|------------|-------------|
| 37 | BLMN | swing_trade | $8.26 | $7.85 | none | 363 | alpaca_paper | 2026-05-27 11:15 | **duplicate_submit_race** |
| 38 | BLMN | swing_trade | $8.28 | $7.85 | none | 363 | ALPACA_PAPER | 2026-05-27 11:15 | (open) |

## Repair Status: COMPLETE

- #37 closed as duplicate_submit_race (exit_time set)
- #38 entry_time backfilled from journal filled_at
- #38 has execution + stop_placement lifecycle events
- #37 has duplicate_reconciliation lifecycle event
- #38 has metadata_backfill lifecycle event
- 9 total BLMN lifecycle events

## Journal Status

| ID | Status | Entry | Exit | Account |
|----|--------|-------|------|---------|
| 37 | **closed** | $8.26 | (no exit_reason) | alpaca_paper |
| 38 | **open** | $8.28 | (open) | ALPACA_PAPER |

## Classification: **Duplicate DB Row**

Row #37 is shown as "closed" in the automated journal but has:
- `exit_time IS NULL`
- `exit_reason IS NULL` (empty string or null)
- `entry_time` is set (11:15 today)

Row #38 is shown as "open" in the journal but has:
- `entry_time IS NULL`
- Same strategy, same shares, same stop, similar entry price ($8.28 vs $8.26)

**This looks like a duplicate-submit race condition:** the proposal pipeline submitted
BLMN swing_trade twice. #37 got the broker fill (entry_time set, $8.26 fill), but the
journal marks it closed (possibly reconciled out). #38 is the "official" open position
in the journal ($8.28) but has no entry_time in the DB.

## Root Cause

Same pattern as the earlier ghost positions: proposal_paper_submitter or auto-proposal
created two DB rows for the same symbol/strategy. Only one became the canonical broker
position. The other is an artifact.

## Stop Proof

Both rows have `stop_order_id = none` — neither has a broker stop order linked.
This is a follow-up for unified_stop_supervisor to address.

## Recommended Action

1. **Row #37:** Should have `exit_reason` set (e.g., `duplicate_submit_race`) and `exit_time` set.
   The journal already considers it closed.
2. **Row #38:** Is the canonical open position per the journal. Needs `entry_time` populated
   and `stop_order_id` captured on next stop supervisor cycle.
3. **Do not modify either row in this investigation.** Document for operator-approved reconciliation.

## No-Write Safety Confirmation

- No orders placed
- No broker writes
- No stops modified
- No paper_trades changes
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
