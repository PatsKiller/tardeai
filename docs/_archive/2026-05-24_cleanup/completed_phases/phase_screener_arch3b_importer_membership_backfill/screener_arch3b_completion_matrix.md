# SCREENER-ARCH-3B Completion Matrix

| # | Deliverable | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Backfill dry-run | **DONE** | 1,941 symbols, 1,941 memberships |
| 2 | Backfill apply | **DONE** | All 1,941 memberships written |
| 3 | Membership snapshot populated | **DONE** | 1,941 rows in screener_symbol_membership |
| 4 | History events populated | **DONE** | 1,941 entered events |
| 5 | Catalog status report with data | **DONE** | 5,071 classified, 5,242 watchlist |
| 6 | Membership status report with data | **DONE** | 1,941 present |
| 7 | Importer page/raw row persistence | **DEFERRED** | No per-page tracking in current importer |
| 8 | Dropped/stale detection | **DEFERRED** | Needs multi-run comparison |
| 9 | Reentered detection | **DEFERRED** | Needs multi-run comparison |
| 10 | Incubator falloff apply | **DEFERRED** | Needs dropped detection |
| 11 | API/dashboard integration | **DEFERRED** | Data exists, endpoints not added |
| 12 | Tests | **DONE** | 11/11 |
| 13 | Safety | **DONE** | Paper-only, no trades |

## Summary

**7/13 DONE, 6 DEFERRED.** The catalog is now populated with real data.
Next: multi-run dropped/reentered detection requires patching the importer
to compare current run with prior membership state.
