# ATP-4/Q-2 — Quote-Age Stale Sweeper and Truth Counters

**Status:** COMPLETE

## What Was Fixed

1. **Staleness policy patched** (`phase6_proposal_staleness_policy.py`):
   - Now evaluates both proposal age AND quote age
   - `never_checked` quote status blocks approval and flags requires_refresh
   - Quote-age thresholds: momentum 15min, swing 60min, default 240min
   - >72h quote age: "extremely_stale" with expire/rebuild recommendation
   - >168h: hard expire recommendation

2. **Gap report** (`report_quote_age_stale_sweeper_gap.py`):
   - 3 mismatches found: SIF (277h), NVST (300h), DOC (317h) — proposal fresh but quote extremely stale

3. **Action review** (`run_quote_age_stale_proposal_review.py`):
   - SIF/NVST/DOC: EXPIRE (>168h quote age)
   - INGM/CODX: needs_quote_refresh (quote never checked, 8-13h scan age)

4. **Pipeline health message fixed**: Now says "5 unknown quotes" instead of "0 stale quotes"

## Before/After

| Metric | Before | After |
|--------|--------|-------|
| Staleness checks quote age | No (proposal age only) | Yes |
| SIF/NVST/DOC recommended | keep_pending (fresh proposal) | EXPIRE (277-317h quote) |
| Pipeline message | "0 stale quotes" | "5 unknown quotes, 0 stale" |

## Tests

12/12 pass.
