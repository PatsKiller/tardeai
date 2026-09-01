# Operator Observed Failure

Status:      ACTIVE
as_of:       2026-05-19T21:01:07-04:00
Measured at: efcc51365 / not measured

- Route: /v2/paper-proposals
- Time shown: 17:30 ET
- Run state: RUN_UNDERFILLED
- Scanned: 6
- GO: 1
- Pending proposals: 0

## Root Cause

The 17:30 cron is `trade_ai_orchestrator.py --run-label 1730 --no-alerts --allow-underfilled`. This is an **intentional narrow incremental cleanup pass**, not a full after-hours candidate preparation run. It only scans symbols that have new data since the last run, which at 17:30 is typically <10 symbols.

The real after-hours coverage comes from:
- 16:00 orchestrator: 98+ symbols (today: not run yet at time of observation)
- 14:00 orchestrator: 827 symbols
- 18:00 FinViz screener: full ingestion

## Fix

Add an after-hours readiness runner that:
1. Uses the FULL active catalog (1,300+ symbols)
2. Leverages existing ARCH-4 strategy-fit audit data (30,015 evaluations)
3. Classifies each symbol's readiness for next session
4. Explains why zero proposals exist when candidates are blocked
