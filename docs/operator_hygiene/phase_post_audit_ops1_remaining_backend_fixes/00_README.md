# POST-AUDIT-OPS-1 — Remaining Backend Audit Defects

**Status:** DIAGNOSED — all 5 workstreams audited and classified

## Summary

| Workstream | Status | Root Cause | Next Action |
|-----------|--------|------------|-------------|
| REGIME-CRON-1 | Stale (211h) | Cron runs but snapshot not updating since May 11 | Investigate classifier write path |
| LLM-FIX-1 | Table not found | `overnight_recovery_verdicts` table does not exist | Create table + wire overnight generator |
| AGENT-FIX-1 | Worker not running | Agent job worker process not running, 1121 queued | Restart worker process |
| COUNT-TRUTH-1 | Scope drift | Different pages use different filters (expected) | Label counts with scope |
| ATTR-1 | No tables | No attribution/benchmark tables exist | Create tables + run attribution pipeline |

## Key Findings

- **Regime**: Cron fires daily at 06:30/16:05. Logs show successful collection/classification. But the snapshot in `market_regime_snapshots` hasn't been updated since May 11. The classifier may be writing to a file instead of DB, or the API reads from a different source.

- **Overnight**: The `overnight_recovery_verdicts` table doesn't exist. Template fallback is because there's nowhere to write/read real LLM verdicts.

- **Agent**: Queue is NOT stuck — 1763 completed, but worker process is currently not running. 1121 jobs queued, oldest 25h old.

- **Counts**: 10 closed paper trades, 13 open (includes positions), 23 strategy configs. Drift between pages is scope-based (different WHERE filters), not a bug.

- **Attribution**: No benchmark/attribution tables at all. The N/A display is correct — there's no data to compute from.

## Reports Generated

6 diagnostic reports + 1 integration smoke test, all with JSON + MD output.
