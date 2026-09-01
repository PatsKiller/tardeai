# Brave Search API Usage Audit — May 2026

Status:      HISTORICAL
as_of:       2026-05-24T11:04:01-04:00
Measured at: efcc51365 / not measured

## Current Status
- **Plan:** Free tier ($5.00/month credit)
- **Requests this month:** 1,000 (limit reached, 100%)
- **Spend:** $5.00 / $5.00
- **Cycle:** 74% through (day 23/31)
- **Projected:** ~1,300 requests at current pace (capped at 1,000)
- **Rate limited:** Yes — new requests throttled until cycle reset

## Why 1,000 Requests Were Used So Fast

### Caller Scripts (in order of request volume)

| Script | Cron Schedule | Brave Calls Per Run | Estimated Monthly Volume |
|--------|--------------|--------------------|-----------------------|
| `scripts/portfolio_news.py` | Not directly cron'd, called by news_ingestion | ~47 (1 per holding) + watchlist symbols | ~200-300/month |
| `scripts/topic_ingestion.py` | Manual/on-demand via `/api/v2/topics/run` | ~10-17 per run (1 per topic search query) | ~100-200/month |
| `scripts/catalyst_intelligence.py` | Called per-symbol by agent pipeline | 1 per symbol analysis | ~200-400/month |
| `scripts/web_news_fetcher.py` | Called by various enrichment scripts | 1-2 per query with DDG fallback | ~100-200/month |
| `scripts/aegis_transcript_discovery.py` | Part of Aegis overnight/surveillance | 1 per discovery query | ~30-60/month |

### Root Cause of Fast Consumption

1. **portfolio_news.py** processes ALL 47 portfolio holdings + watchlist symbols per run. Each symbol = 1 Brave API call. With 3 news ingestion crons/day (6:30 AM, 12:30 PM, 6:30 PM) and ~50 symbols, that's **~150 calls/day** from news alone.

2. **catalyst_intelligence.py** is called per-symbol by the agent pipeline (`process_watchlist_agent_jobs.py`). With 1,800+ queued jobs processing, each agent analysis triggers a Brave search for context. A drain batch of 50 jobs = 50 Brave calls.

3. **topic_ingestion.py** runs 17 topic searches when triggered manually. Each topic has 1-3 search queries = ~30-50 calls per full topic run.

4. **No request budgeting.** The `brave_search.py` module has a 5-minute in-memory cache (`_cache_ttl = 300`) but no daily/monthly budget tracking. The cache only helps within a single process — it doesn't persist across cron invocations.

### Volume Calculation
- 3 news runs/day × ~50 symbols × 22 weekdays = **3,300 potential calls/month** from news alone
- Agent pipeline processing adds 200-400 more
- Topic ingestion adds 100-200 more
- **Total potential: ~3,800-4,000 calls/month** vs 1,000 limit

## What Happens When Limit Is Reached

- Brave API returns rate-limit errors
- `brave_search.py` returns empty results
- Callers fall back to other sources:
  - `web_news_fetcher.py` has DuckDuckGo fallback (`_ddg_search()`)
  - `topic_ingestion.py` has DuckDuckGo fallback (`search_duckduckgo()`)
  - `portfolio_news.py` uses Google News RSS as primary, Brave as supplement
  - `catalyst_intelligence.py` proceeds without web context (LLM still works)

## Available Alternative Search Sources

| Source | Status | Script | Notes |
|--------|--------|--------|-------|
| Google News RSS | Active, free | news_ingestion.py | Primary news source, no API key needed |
| DuckDuckGo HTML scrape | Active, free | topic_ingestion.py, web_news_fetcher.py | Rate-limited by DDG, no API key |
| Finviz Elite News | Active, paid | finviz_news.py | Uses FINVIZ_API_TOKEN, separate budget |
| YouTube transcript | Active, free | topic_ingestion.py | Uses yt-dlp, cookie-based |
| Brave Search API | EXHAUSTED | brave_search.py | 1,000/month free tier |

## Recommendations

### Immediate (No Cost)
1. **Add daily request budget** to `brave_search.py`: Track calls in a file/DB, cap at 30/day (900/month with buffer)
2. **Reduce news_ingestion Brave calls**: Only search Brave for top 10-15 highest-priority symbols, not all 47+
3. **Increase cache TTL**: Change from 5 min to 60 min for news queries (news doesn't change that fast)
4. **Skip Brave on weekends**: Market is closed, news volume is low — use RSS + DDG only

### If Budget Available
- **Brave Pro plan ($15/month):** 5,000 requests — covers current usage
- **Brave Business ($50/month):** 20,000 requests — room for growth
- **Serper API:** $50/month for 2,500 queries with Google results quality

### Architecture Fix
- Add a `search_budget.json` file tracking daily/monthly Brave calls
- `brave_search.py` checks budget before making API call
- If over budget, return empty and let callers use fallback
- Log budget exhaustion as a `system_health` alert
