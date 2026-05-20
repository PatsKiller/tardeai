> **UPDATE / SUPERSEDED STATUS — 2026-05-20**
> This diagnostic report reflects the pre-fix state. It has been superseded by DOC-RECON-1 (commit multiple).
> Current status: **FIXED**.
> Current result: all 5 workstreams fixed; smoke test findings superseded.
> Safety: no trades, no orders, no live trading.

# Post-Audit Integration Smoke Test
Generated: 2026-05-20T15:22:13.978304+00:00

**Overall health: degraded**

## Subsystem Status
| Subsystem | Status | Root Cause | Fix |
|-----------|--------|------------|-----|
| Regime Cron Staleness | unknown | unknown | snapshot is 211.1h stale (>24h) |
| LLM Overnight Fallback | error | table_not_found | None |
| Agent Queue Health | warning | worker process not running; queue backlog: 1121 queued jobs; oldest queued job is 25.0h old | start the agent job worker process |
| Count Truth Drift | error | 1 source(s) failed to query: incubator_active; 1 source(s) returned 0: proposals_pending | investigate missing/zero sources |
| Attribution Benchmark | warning | no_benchmark_tables | create attribution/benchmark tables; run the performance attribution pipeline to populate |