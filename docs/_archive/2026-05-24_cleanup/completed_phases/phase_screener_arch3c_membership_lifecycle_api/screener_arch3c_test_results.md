# SCREENER-ARCH-3C — Test Results

## ARCH-3C Tests: 23/23 PASS

| # | Test | Result |
|---|------|--------|
| 1 | backfill_screener_membership_transitions compiles | PASS |
| 2 | report_screener_membership_status compiles | PASS |
| 3 | report_ticker_catalog_status compiles | PASS |
| 4 | report_and_apply_incubator_falloff_lifecycle compiles | PASS |
| 5 | api_v2 compiles | PASS |
| 6 | entered transition works | PASS |
| 7 | present transition idempotent | PASS |
| 8 | dropped when missing from complete run | PASS |
| 9 | stale after threshold | PASS |
| 10 | expired no delete | PASS |
| 11 | reentered from dropped | PASS |
| 12 | reentered from expired | PASS |
| 13 | multi-screener symbol remains active if present in one | PASS |
| 14 | active_in_sources falloff keeps active | PASS |
| 15 | dropped retain by TTL | PASS |
| 16 | API has all three endpoints | PASS |
| 17 | API endpoints are read-only | PASS |
| 18 | no trades in scripts | PASS |
| 19 | no strategy activation | PASS |
| 20 | dashboard section exists | PASS |
| 21 | frontend build exists | PASS |
| 22 | ARCH-3B test file exists | PASS |
| 23 | ARCH-3 test file exists | PASS |

## Regression Tests

| Suite | Tests | Result |
|-------|-------|--------|
| SCREENER-ARCH-3B | 11/11 | PASS |
| SCREENER-ARCH-3 | 12/12 | PASS |
| JOURNAL-UX-1 | 11/11 | PASS |

## Frontend Build

Built in 215ms. No errors.
