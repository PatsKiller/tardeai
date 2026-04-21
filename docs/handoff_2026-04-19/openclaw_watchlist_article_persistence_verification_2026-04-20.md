# Watchlist Article Persistence Refinement — Verification Report

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `scripts/portfolio_news.py`, `~/.openclaw/skills/steph-wealth-advisor/scripts/advisor_memory_reader.py`

---

## 1. Changes Made

### `portfolio_news.py`
- Added secondary scoring pass for watchlist articles: scores up to 10 extra articles from watchlist symbols that weren't in the initial top-30 scoring batch
- Tagged all scored articles with `_source_family`: "portfolio" (market_value > 0) or "watchlist" (market_value = 0)
- Combined portfolio + watchlist articles in `all_scored` for broader article_index persistence

### `advisor_memory_reader.py`
- `articles` query now returns `source_family` field from JSONB
- Added scope filtering via `--status portfolio|watchlist` (reuses existing --status arg)

---

## 2. Results

### Article coverage by scope

```sql
SELECT portfolio_symbol, data->>'_source_family' AS scope, COUNT(*)
FROM article_index GROUP BY portfolio_symbol, scope ORDER BY scope, portfolio_symbol;

 portfolio_symbol |   scope   | count
------------------+-----------+-------
 BND              | portfolio |     3
 PFE              | portfolio |     3
 V                | portfolio |    18
 XLB              | portfolio |     2
 XLI              | portfolio |     4
 PLTR             | watchlist |    10
```

**PLTR now has 10 articles from watchlist scope.** The watchlist scoring batch successfully captured relevant articles for PLTR (the highest-coverage watchlist symbol today).

### Pipeline output
```
[portfolio-news] Scanning 42 tickers for news...
[portfolio-news] Found 601 raw articles from 42 tickers
[portfolio-news] ✅ 40 scored catalysts saved | 2 Brave-enriched
[article-index] ✅ 40 articles indexed
```

40 articles indexed (up from 20-30 in prior passes).

### Bridge query with scope filter
```
advisor_memory_reader.py articles --status watchlist --days 7
→ 10 articles, all PLTR

Sample:
  PLTR: Palantir Just Laid Out a 22-Point Guideline...
  PLTR: Which AI Stock Is the Best Buy Today: Nvidia...
  PLTR: Trump Praises Palantir's Technology: Is the Stock...
```

---

## 3. Provenance

Articles now include `_source_family` in their JSONB `data`:
- `"portfolio"` — article is about a currently-held position
- `"watchlist"` — article is about a user-watchlist symbol not currently held

Bridge queries can filter: `--status portfolio`, `--status watchlist`, or omit for all.

---

## 4. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Existing portfolio catalyst behavior preserved | **PASS** — top 20 `catalysts` in JSON unchanged |
| Watchlist articles materially persisted to article_index | **PASS** — PLTR has 10 articles |
| Provenance distinguishes watchlist vs portfolio | **PASS** — `_source_family` in JSONB |
| article_index dedupe still works | **PASS** — URL-based, no duplicates |
| Implementation stayed bounded to user-watchlist only | **PASS** |
