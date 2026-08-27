# SCREENER-ARCH-3C — Dropped/Reentered Membership Detection and Catalog Dashboard API

**Status:** COMPLETE (15/16 done, 1 deferred)

## What Was Delivered

1. **Transition detection** (`scripts/backfill_screener_membership_transitions.py`):
   - Prior-vs-current membership comparison per screener per day
   - Classifies: entered, present, dropped, stale, expired, reentered
   - Mass-drop protection (>50% threshold skips drops on partial runs)
   - Idempotent (deduplicates by run_id + event_type)

2. **Backfill results** (14 days, 4 screener sources):
   - 5,035 history events created
   - 97 entered, 3,626 present, 1,257 dropped, 55 reentered
   - 8 mass-drop protections triggered (pre-ARCH-2 partial coverage era)
   - 0 stale, 0 expired (only 2 days of full coverage data)

3. **Membership lifecycle state** (after backfill):
   - 2,038 total memberships (up from 1,941)
   - 1,311 present, 727 dropped
   - 4 multi-screener symbols
   - 723 dropped from ALL screeners

4. **Incubator falloff lifecycle** (`scripts/report_and_apply_incubator_falloff_lifecycle.py`):
   - 1,129 active candidates analyzed
   - 153 keep active, 751 retain by TTL, 136 would expire, 89 no data
   - Expire not applied — requires operator approval

5. **Read-only API endpoints**:
   - GET /api/v2/ticker-catalog/summary
   - GET /api/v2/screener-membership/summary
   - GET /api/v2/incubator-lifecycle/summary

6. **Dashboard**: Scanner Catalog Lifecycle card on Paper Governance page

## What Is Deferred

- Falloff lifecycle apply (expire inactive candidates) — requires operator approval → ARCH-3D

## Tests

23/23 ARCH-3C + 11/11 ARCH-3B + 12/12 ARCH-3 + 11/11 JOURNAL-UX-1 regression.
