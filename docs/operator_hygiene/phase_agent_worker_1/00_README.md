# AGENT-WORKER-1 — Agent Queue Health Restoration

**Status:** COMPLETE

## Architecture (confirmed)

The agent worker is **cron-triggered batch processing**, not a persistent daemon. No "worker not running" is expected — that diagnosis was misleading.

| Schedule | Window | Limit | Throughput |
|----------|--------|-------|------------|
| */15 6-19 M-F | Market hours | 5/run | ~20/hr |
| */5 20-23 M-F | Overnight | 5/run | ~60/hr |
| */5 0-5 Tu-Sa | Late night | 5/run | ~60/hr |
| */10 * * Sa-Su | Weekend | 5/run | ~30/hr |

All entries use `flock` (no overlap) + `timeout 12m` (safety cap).

## Bug Found: `InFailedSqlTransaction` causing stuck jobs

**Root cause:** `_get_sentiment_social_context()` queried `fused_signals.overall_signal` — column doesn't exist (actual column: `direction`). Although this function uses its own DB connection, the error pattern cascaded: when the main transaction was poisoned by *other* uncaught errors during the processing pipeline, the completion UPDATE at line 1875 failed with `InFailedSqlTransaction`, leaving jobs permanently stuck in `processing` status.

**Fixes applied:**
1. Fixed `overall_signal` → `direction` in fused_signals query (+ added `fused_score`, `severity`)
2. Added transaction health check + rollback recovery before the critical completion UPDATE
3. Reset 125 stuck processing jobs back to queued

## Queue Health (post-fix)

| Metric | Value |
|--------|-------|
| completed | 6,081 |
| queued | 1,269 |
| failed | 1,850 |
| stuck | 0 (was 125) |
| throughput 24h | 490 |
| avg daily (7d) | 258 |
| backlog ETA | ~5 days |

## New Script

`scripts/run_agent_queue_health.py` — Read-only health report with optional `--reset-stuck` flag.

## Smoke Test

```
[watchlist-agent] Processing 2 jobs...
  ✓ AVAV (steph): SELL conf=68%
  ✓ BAH (maria): HOLD conf=61%
[watchlist-agent] Done: 2/2 completed
```
