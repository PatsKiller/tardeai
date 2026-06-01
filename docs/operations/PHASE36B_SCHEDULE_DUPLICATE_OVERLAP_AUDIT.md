# Phase 36B — Schedule Duplicate and Overlap Audit

**Date:** 2026-06-01
**Status:** COMPLETE — read-only audit

---

## Scripts Scheduled Multiple Times

| Script/Log | Occurrences | Risk |
|-----------|-------------|------|
| proactive_quote_refresh | 11 | LOW — different time slots, flock-guarded |
| finviz_screener | 7 | MEDIUM — 7 AM peak congestion |
| screener_pm | 6 | MEDIUM — overlaps with finviz_screener |
| watchpool_alerts | 5 | LOW — different time slots |
| atp2_research_cycle | 5 | MEDIUM — multiple LLM calls, resource contention |
| watchlist_agent_jobs | 4 | LOW |
| system_health_agent | 3 | LOW |
| stale_proposal_sweeper | 3 | LOW — idempotent |
| news_ingestion | 3 | LOW — flock-guarded |
| agent_router_cron | 3 | MEDIUM — dispatches other agents |
| agent_intelligence_cron | 3 | MEDIUM — LLM resource contention |

## Same-Time Collisions

| Time | Jobs | Risk |
|------|------|------|
| 8:00 AM Mon-Fri | 8 | MEDIUM — most crowded slot |
| 7:00 AM Mon-Fri | 4 | MEDIUM — market open prep |
| 7:15 AM Mon-Fri | 4 | LOW — staggered |
| 7:30 AM Mon-Fri | 4 | LOW — staggered |

## Jobs Missing Lock Files

- ~130 of 187 do NOT use flock (70%)
- Most are lightweight reads or Telegram sends, but some write to DB
- Recommendation: add flock to all DB-writing jobs

## Jobs Missing market_day_gate

- 173 of 187 run without market_day_gate (93%)
- Many are market-hours-only jobs that should skip weekends/holidays
- Low actual risk (most check internally) but inconsistent

## Jobs Writing Same Target

| Target | Writers | Risk |
|--------|---------|------|
| ticker_prices / price_cache | quote_refresh (11×) | LOW — upsert |
| screener tables | finviz + screener_pm (13×) | MEDIUM |
| agent results | router + intelligence + research (9×) | MEDIUM |
| proposals | enrichment + sweeper + ATM (7×) | LOW — different operations |

## Recommendations (No Changes in Phase 36)

1. Consolidate finviz_screener + screener_pm into single pipeline (13→1)
2. Consolidate agent_router + agent_intelligence into single dispatch (6→1)
3. Add flock to remaining 130 jobs without it
4. Standardize market_day_gate usage
5. Stagger 8:00 AM jobs across 8:00–8:10 window
