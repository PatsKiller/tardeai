# Pipeline Verification

Status:      ACTIVE
as_of:       2026-05-21T15:13:01-04:00
Measured at: efcc51365 / not measured

All pipeline jobs executed manually after fix on 2026-05-21.

| Job | Status | Notes |
|-----|--------|-------|
| Market regime classifier | OK | Regime: high_volatility (conf=43%) |
| Finviz screener | OK | All 27 screeners ran |
| Finviz enrichment | OK | Background |
| Portfolio orchestrator | OK | Background |
| Incubator promoter | OK | NEE promoted to PENDING #111 |
| Paper trade monitor | OK | ASPN catch-up evaluation |
| Stale proposal cleanup | OK | AMPG gap_and_go expired (RSI >= 80) |
| Quote refresh (pending) | OK | 1 target refreshed |
| Quote refresh (incubator) | OK | 23 targets refreshed |
| Paper execution sweep | OK | |
| Alpaca reconciler | OK | |

## Key Outcome
NEE (dividend_growth_compounder, score=30) promoted to PENDING proposal #111 after quote_never_checked blocker was resolved. Proposal requires operator approval — no automatic execution.

## Cron-Context Verification
DB adapter successfully connects when run without DB_* environment variables (simulating cron):
```
env -u DB_HOST -u DB_PORT -u DB_NAME -u DB_USER -u DB_PASSWORD python -c "from db_adapter import _get_conn; print(_get_conn())"
# Returns valid connection
```
