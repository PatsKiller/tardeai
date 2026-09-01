# Monday Morning Pre-ATM State

Status:      HISTORICAL
as_of:       2026-05-23T19:19:59-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-23 (Sunday evening)

## Holdings
Total: $1,201,120.25 / 47 positions

## Pipeline
30/31 healthy, 1 warning, 0 critical. Last cycle: 05:11 PM Saturday.

## Agent Worker Queue
- queued: 158 (90 from last 24h, rest older)
- completed: 6,293 all-time
- expired: 1,690 (stale >48h, cleaned this session)
- processing: 9
- Drain rate: ~5 jobs per 10-min cron cycle (~90s per LLM call on Arc B50)
- Estimated drain time: ~5h for remaining 158 jobs
- Backlog guard added: auto-queue skipped when >50 pending

## 7 Triggered Stops — VERIFY AT SCHWAB
RTX, LHX, LMT, NOC, LDOS, KBR, PFLT — all schwab_taxable
Total at-risk value: ~$12,500
These are notional/planned stops (no broker GTC orders). Price below stop level.
See docs/_findings/triggered_stops_2026-05-24_pre_schwab_check.md

## Fixes Shipped This Session
- Risk page: TRIGGERED count now correct (7 positions, was 0)
- Agent dashboard: Alex/Aegis stats enriched from home tables
- Command freshness: weekend-aware, uses pipeline_runs
- Worker backlog guard: auto-queue skips when >50 pending
- 1,690 stale jobs expired

## Known Cosmetic Items (defer to post-burn-in)
- Agent pipeline page: LLM budget may show $0 (cost tracking gap)
- Watchdog amber 20h (schedule expectation may differ from registry)
