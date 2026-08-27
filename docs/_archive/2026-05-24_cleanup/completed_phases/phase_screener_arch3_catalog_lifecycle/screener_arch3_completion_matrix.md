# SCREENER-ARCH-3 Completion Matrix

| # | Deliverable | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Catalog data model design | **DONE** | Leverages incubator_universe + ticker_strategy_classifications |
| 2 | Membership tables created | **DONE** | screener_symbol_membership + _history |
| 3 | Migration dry-run | **DONE** | Non-destructive, idempotent |
| 4 | Migration apply | **DONE** | Tables + indexes created |
| 5 | Falloff lifecycle policy | **DONE** | Pure functions: active/retain/expire/review |
| 6 | Ticker catalog status report | **DONE** | 1,139 incubator, 4,872 classified, 5,043 watchlist |
| 7 | No silent deletion rule | **DONE** | No "delete" action in policy |
| 8 | TTL-based retention | **DONE** | Per-strategy horizon TTL |
| 9 | Importer persistence (write memberships) | **DEFERRED** | Needs screener runner patch |
| 10 | Recent run backfill | **DEFERRED** | Needs membership write logic |
| 11 | Dropped/reentered event history | **DEFERRED** | Tables ready, write logic needed |
| 12 | Membership status report | **DEFERRED** | Needs populated data |
| 13 | API/dashboard integration | **DEFERRED** | Needs populated data |
| 14 | Tests | **DONE** | 12/12 |
| 15 | Safety | **DONE** | Paper-only, non-destructive |

## Summary

**8/15 DONE, 5 DEFERRED** (require importer patch to populate membership tables).

The tables and policy are ready. The next step is patching the screener runner
to write membership records on each run, then backfilling from recent runs.
This is the SCREENER-ARCH-3B follow-up.
