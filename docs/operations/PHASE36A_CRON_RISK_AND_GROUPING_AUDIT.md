# Phase 36A — Cron Risk and Grouping Audit

**Date:** 2026-06-01
**Status:** COMPLETE — read-only audit

---

## Cron Job Distribution by Time (187 total)

| Hour (ET) | Jobs | Category |
|-----------|------|----------|
| 6:00–6:59 | 19 | Pre-market prep |
| 7:00–7:59 | 28 | **Market open peak** |
| 8:00–8:59 | 18 | Morning scans |
| 9:00–9:59 | 9 | Market open |
| 9–16 (hourly) | 7 | Intraday recurring |
| 10:00 | 10 | Mid-morning |
| 11:00 | 4 | Late morning |
| 12:00 | 6 | Midday |
| 16:00–16:59 | 12 | Market close |
| 17:00–19:59 | 15 | After-hours |
| 20:00–21:00 | 11 | Evening |
| Hourly (*) | 7 | Always-on |
| Other | ~41 | Misc/weekend |

## Job Groups

### 1. Pre-Market Prep (6:00–7:00 ET, ~47 jobs)

| Sub-group | Jobs | Write Targets | Lock? | Risk |
|-----------|------|--------------|-------|------|
| Quote refresh | 11 | ticker_prices, price_cache | flock | LOW |
| Screener runs | 7+6=13 | screener tables, incubator | flock | MEDIUM — 7 AM peak |
| News ingestion | 3 | news_articles, catalyst_events | flock | LOW |
| Watchpool alerts | 5 | watchlist tables | flock | LOW |
| Research cycle | 5 | agent results, intelligence | flock | MEDIUM |
| System health | 3 | health tables | some | LOW |
| Governance | 4 | governance tables | some | LOW |
| Morning brief | 1 | Telegram delivery | dedupe | LOW |
| Agent router | 3 | agent queues | flock | MEDIUM |

### 2. Intraday (9:00–16:00 ET, ~43 jobs)

| Sub-group | Jobs | Write Targets | Risk |
|-----------|------|--------------|------|
| Hourly reprice | 7 | price tables | LOW |
| Data gap resolver | ~4 | various pipeline | LOW |
| Intelligence scans | ~6 | agent results | MEDIUM |
| Proposal enrichment | ~4 | proposals | LOW |
| Quote refresh | ~11 | price tables | LOW (repeats) |
| Stale sweeper | 3 | proposals | LOW |

### 3. Market Close / Evening (16:00–21:00 ET, ~38 jobs)

| Sub-group | Jobs | Write Targets | Risk |
|-----------|------|--------------|------|
| Close reconciliation | ~4 | reconciliation tables | LOW |
| Evening digest | ~4 | Telegram/file | LOW |
| Weekly review (Fri) | ~2 | reports | LOW |
| Deep LLM window | ~2 | LLM results | LOW |
| Nightly calibration | ~3 | scoring tables | LOW |
| Config sync | ~3 | config tables | LOW |
| Overnight sweep | ~2 | stale proposal cleanup | LOW |

### 4. Maintenance / Always-On (~14 jobs)

| Sub-group | Jobs | Write Targets | Risk |
|-----------|------|--------------|------|
| Drive sync | ~2 | Google Drive | LOW |
| Telegram polling | ~2 | callback handler | LOW |
| Hourly tasks | 7 | various | LOW |
| Maturity board | 2 | maturity tables | LOW |

### 5. Weekend (~10 jobs)

| Sub-group | Jobs | Write Targets | Risk |
|-----------|------|--------------|------|
| Weekly learning | ~3 | digest tables | LOW |
| Price cache | ~2 | price tables | LOW |
| Version check | ~1 | version file | LOW |
| Other | ~4 | various | LOW |

---

## Risk Summary

| Risk Level | Count | Key Concern |
|-----------|-------|------------|
| HIGH | 0 | No single job is high-risk alone |
| MEDIUM | ~20 | 7 AM peak congestion, agent router overlap, screener contention |
| LOW | ~167 | Well-locked, well-logged |

## Key Metrics

| Metric | Value |
|--------|-------|
| Jobs using flock | 57 (30%) |
| Jobs using market_day_gate | 14 (7%) |
| Scripts scheduled multiple times | 11+ (quote refresh, screener, watchpool) |
| Peak hour jobs | 28 at 7 AM ET |
| Lock files | ~20 documented |
