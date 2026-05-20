# ATP-4B — Proposal Action Counter Alignment

**Status:** COMPLETE

## Fix

UNKNOWN_QUOTE and STALE_QUOTE verdicts now increment `needs_review_count` (Need Action) in addition to their own counters.

## Before/After

| Counter | Before | After |
|---------|--------|-------|
| Need Action | 0 | **2** |
| Unknown Quote | 2 | 2 |
| Ready | 0 | 0 |
| Stale Quote | 0 | 0 |
| Approvals allowed | 0 | 0 |

## Tests

6/6 pass. Frontend built 213ms.
