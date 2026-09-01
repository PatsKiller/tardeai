# A-5 Re-review Trigger Rules

Status:      ACTIVE
as_of:       2026-05-22T20:13:41-04:00
Measured at: efcc51365 / not measured

**Last review:** 2026-05-22 (FAIL/EXTEND)

## Automatic Triggers

Re-run A-5 evidence review when ANY of:

1. **Total closed trades ≥ 20** (currently 11)
2. **Any single strategy reaches 5+ closed trades** (currently max 2)
3. **Safety incident occurs** (stop failure, audit failure, unprotected position)
4. **ATM burn-in produces abnormal pattern** (>50% reject rate for 3+ consecutive days)
5. **Stop reconciliation fails** (any CRITICAL finding persists >1 hour)

## Manual Triggers

John may request re-review at any time.

## What Re-review Produces

- Updated strategy evidence funnel
- Updated strategy proof score
- Phase 8D gate check (still blocked or newly allowed)
- Agent learning gate check
- Updated maturity score if warranted
