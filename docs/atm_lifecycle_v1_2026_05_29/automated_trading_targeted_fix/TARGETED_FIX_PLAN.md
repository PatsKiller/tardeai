# Automated Trading Targeted Fix Plan — 2026-05-29

## Blocker Category: A + B (Working Correctly + Correctly Blocked)

## Root Cause
No bug. ATM is active and working. Most proposals are `momentum_scalp` (intraday) which ATM correctly skips because 15-min cron cadence is too slow for sub-minute intraday execution. Non-intraday proposals (SNOW, ONDS, BLMN) were successfully approved and created paper trades.

## Proposed Fix: NONE REQUIRED
The system is operating as designed. No code patch needed.

## Strategic Options (operator decision, not bugs)
1. **Generate more non-intraday proposals** — adjust screener/incubator to surface swing, earnings, income strategies
2. **Build faster intraday execution path** — sub-minute pipeline for momentum_scalp/gap_and_go (significant new work)
3. **Manual approve via Telegram** — operator approves intraday proposals during market hours
4. **Accept current behavior** — system trades non-intraday strategies automatically, intraday requires manual approval

## DB Mutation Needed: NO
## Cron Change Needed: NO
## Operator Approval Required: NO (no fix to apply)
## Risk Level: N/A

## Apply Performed: NO
No fix was applied because no fix is needed.
