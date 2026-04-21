# OpenClaw Article Index — Planning Brief

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Market intelligence layer (complete), advisor foundation (complete)

---

## 1. Executive Summary

### What `article_index` is

A deduped, queryable historical metadata store for every article/news item consumed by the portfolio surveillance system. Each row represents one unique article with its URL, title, source, publication time, relevance score, symbols mentioned, and LLM-derived category/sentiment.

### Why it matters before notifications get smarter

Notifications need to answer "is this actually new information?" The article index enables:
- **Dedup:** "We already saw this article from Finnhub yesterday; don't notify again"
- **Frequency:** "V has had 8 articles this week vs 2 last week — elevated coverage"
- **Catalyst tracking:** "3 analyst-related articles for V in 48h — cluster event"
- **Recommendation quality:** "This draft cites a fresh catalyst, not stale news"

### How it supports both holdings and watchlists

The `portfolio_news.py` pipeline already processes articles per-ticker. Currently it only tracks portfolio holdings. The article index stores ALL articles regardless of source, with a `portfolio_symbol` field that links to held/watched tickers. Future expansion to watchlist coverage is a filter change, not a schema change.

### What it must NOT do yet

- No fulltext article storage (store title + summary only)
- No new article summarization pipeline
- No notification logic
- No sentiment model expansion
- No external-model reasoning over articles

---

## 2. Current-State Assessment

### Article/news data already fetched

| Source | Provider | Data Available |
|--------|----------|----------------|
| Finnhub | `portfolio_news.py` | title, url, published_at, summary, source |
| NewsAPI | `portfolio_news.py` | title, url, published_at, source |
| Yahoo News | `portfolio_news.py` | title, url, published_at, source |
| Brave Search | `portfolio_news.py` | title, url, context snippets |
| Polygon | `portfolio_news.py` | title, url, published_at |
| FMP | `portfolio_news.py` | title, url |
| Finviz News | `portfolio_news.py` | title, url |

### Where it currently lives

| Location | Content | Persistence |
|----------|---------|:-----------:|
| `data/portfolios/state/portfolio_news.json` | Today's scored catalysts (top 20-30) | Overwritten daily |
| `data/portfolios/state/portfolio_news_history/` | Daily JSON snapshots (90-day rolling) | 90-day files |
| `data/portfolios/state/portfolio_news_weekly.json` | Weekly synthesis | Overwritten weekly |

### Fields already present per article

Every catalyst entry already has:
- `title` (str)
- `url` (str — dedupe candidate)
- `published_at` (ISO timestamp)
- `source` (str: Yahoo, Finnhub, Benzinga, SeekingAlpha, The Motley Fool)
- `provider` (str: finnhub, newsapi, yahoo, brave, polygon, fmp)
- `symbol` (str — raw symbol from news source)
- `portfolio_symbol` (str — matched to portfolio holding)
- `llm_score` (int 0-100 — Ollama relevance score)
- `llm_category` (str: analyst, earnings, macro, sector, company_specific)
- `llm_urgency` (str: act, watch, monitor)
- `llm_summary` (str — Ollama-generated one-liner)
- `impact_tier` (str: high_impact, medium_impact, low_impact)
- `hours_old` (float)
- `is_fresh` (bool)
- `relevance_type` (str: company_specific, sector, macro)
- `portfolio_weight` (float — % of portfolio)
- `market_value` (float)

**Key insight:** The scoring and metadata are ALREADY computed by the existing pipeline. What's missing is only **historical persistence in Postgres** (currently overwritten daily with 90-day file-based rolling backup).

---

## 3. Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| Store article metadata in Postgres | Store full article text |
| Dedupe by URL | Summarization pipeline redesign |
| Preserve existing LLM scores/categories | New sentiment model |
| Index portfolio symbols per article | Notification logic |
| Support queries across 30/90/365 day windows | External model reasoning |
| Maintain backward compatibility with JSON | |

---

## 4. Proposed `article_index` Table

```sql
CREATE TABLE IF NOT EXISTS article_index (
    id serial PRIMARY KEY,
    ingested_at timestamptz DEFAULT now(),
    published_at timestamptz,
    title text NOT NULL,
    url text,
    source varchar(50) NOT NULL,
    provider varchar(30),
    symbols varchar(20)[],
    portfolio_symbol varchar(20),
    relevance_score integer,
    sentiment varchar(10),
    impact_tier varchar(20),
    llm_category varchar(30),
    llm_urgency varchar(10),
    summary text,
    data jsonb,
    dedupe_key varchar(100) NOT NULL,
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_article_published ON article_index(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_symbols ON article_index USING gin(symbols);
CREATE INDEX IF NOT EXISTS idx_article_portfolio_symbol ON article_index(portfolio_symbol);
CREATE INDEX IF NOT EXISTS idx_article_ingested ON article_index(ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_dedupe ON article_index(dedupe_key);
```

### Column rationale

| Column | Why first-class |
|--------|----------------|
| `published_at` | Time-range queries ("articles this week") |
| `title` | Display in bridge skill / Steph queries |
| `url` | Dedupe primary key source |
| `source` | Filter by publisher (Yahoo vs Finnhub) |
| `provider` | Filter by feed (which API) |
| `symbols` | Array for multi-symbol articles (GIN index) |
| `portfolio_symbol` | Matched holding (primary symbol for this article) |
| `relevance_score` | LLM-scored 0-100 relevance |
| `impact_tier` | High/medium/low filtering |
| `llm_category` | analyst/earnings/macro/sector filtering |
| `llm_urgency` | act/watch/monitor filtering |
| `summary` | LLM one-liner for display |
| `data` | Full raw metadata (brave_context, hours_old, etc.) |
| `dedupe_key` | Prevents same article twice |

### Multi-symbol representation

One row per article. `symbols` is a Postgres array (e.g., `{'V','MA'}` for an article about both Visa and Mastercard). `portfolio_symbol` is the primary matched holding.

### Dedupe strategy

`dedupe_key` = MD5 hash of `url` when URL is available. For articles without URLs, use `MD5(title + source + published_at[:10])`.

---

## 5. Ingestion Model

### From `portfolio_news.json` (existing daily pipeline output)

| Field | Maps to |
|-------|---------|
| `title` | `title` |
| `url` | `url` + source for `dedupe_key` |
| `published_at` | `published_at` |
| `source` | `source` |
| `provider` | `provider` |
| `symbol` | Element of `symbols[]` |
| `portfolio_symbol` | `portfolio_symbol` |
| `llm_score` | `relevance_score` |
| `impact_tier` | `impact_tier` |
| `llm_category` | `llm_category` |
| `llm_urgency` | `llm_urgency` |
| `llm_summary` | `summary` |
| Everything else | `data` JSONB |

### Cadence

After `portfolio_news.json` is written by the daily pipeline, bulk-insert today's catalysts into `article_index`. URL-based dedupe prevents re-inserting the same article across days.

### Failure behavior

Non-blocking. If article_index write fails, the existing `portfolio_news.json` and history files continue as before.

### Initial scope

**Portfolio holdings only** for first pass. The pipeline already limits news collection to held symbols. Watchlist article coverage is a future expansion (requires adding watchlist symbols to the news fetch list).

---

## 6. Relationship to Recommendations and Escalations

### How article_index supports future features (NOT implemented now)

| Feature | How article_index helps |
|---------|------------------------|
| Escalation enrichment | "V concentration escalation + 3 bullish analyst articles this week" |
| Recommendation rationale | "ALLOCATION_REVIEW for V — supported by 5 recent catalysts" |
| Daily summary enrichment | "Top catalyst: Visa analyst upgrade (Bank of America, $410 target)" |
| Notification quality | "Is this article actually new, or the same Finnhub story from yesterday?" |
| Watchlist intelligence | "PLTR has had 12 articles in 7 days — elevated coverage" |

These integrations are deferred to future phases. The article_index simply makes the data queryable.

---

## 7. Coverage Strategy

### First pass: portfolio holdings only

Current `portfolio_news.py` already scopes to held symbols (40+ tickers). This is the natural first coverage set.

### Future expansion (deferred)

| Coverage | When | How |
|----------|------|-----|
| User watchlist symbols | After watchlist enrichment expansion | Add watchlist syms to news fetch list |
| AI-generated watchlist | After AI watchlist generation | Same |
| Analyst-curated | After analyst watchlist | Same |
| Screener candidates | Much later | Separate news pipeline |

---

## 8. Dedupe / Identity Strategy

### Primary dedupe: URL-based

```python
dedupe_key = hashlib.md5(url.encode()).hexdigest()[:20] if url else hashlib.md5(f"{title}|{source}|{published_at[:10]}".encode()).hexdigest()[:20]
```

### Handling repeated syndicated articles

Same article syndicated across Yahoo, Finnhub, Benzinga:
- Different URLs → different `dedupe_key` → stored as separate rows
- This is CORRECT because each source may have different metadata, different timing
- Queries can group by title similarity later if needed

### Same article updated after publication

- Same URL → same `dedupe_key` → ON CONFLICT DO UPDATE
- Updated metadata (score, summary) replaces previous version
- `ingested_at` updates to latest; `published_at` stays original

### Article revisions

Overwrite (update), not version. One row per URL. The `data` JSONB can include an `update_count` field if tracking revisions becomes needed.

---

## 9. Recommended Smallest Implementation Slice

### Choice: portfolio_news → article_index (existing pipeline output only)

**Why this first:**
1. Data already exists (`portfolio_news.json` has 20-30 scored catalysts per day)
2. All metadata (LLM score, category, urgency, summary) is already computed
3. No new API calls needed
4. Same proven dual-write pattern
5. Immediately enables "what news has V had this month?" queries

**What to build:**
1. Create `article_index` table
2. After `portfolio_news.json` is written, bulk-insert today's catalysts
3. URL-based dedupe prevents re-inserting same articles across days
4. Add `articles` query type to `advisor_memory_reader.py`

**Estimated effort:** 1.5-2 hours

**Volume estimate:** 20-30 articles/day × 365 = ~8-10K rows/year. Trivial.

---

## 10. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Duplicate noisy news** | MEDIUM | URL-based dedupe. Same syndicated article gets separate rows per source (intentional). |
| **Storing low-value metadata** | LOW | Only scored catalysts (top 20-30) stored, not all 156 raw articles. Pre-filtered by LLM scoring. |
| **Symbol mis-assignment** | LOW | `portfolio_symbol` comes from existing pipeline matching logic (already validated). |
| **Stale articles appearing as new** | LOW | `published_at` preserved from source. `hours_old` in data JSONB. Queries can filter by recency. |
| **DB bloat** | VERY LOW | 10K rows/year, ~500 bytes/row = 5MB/year. |
| **Confusing article presence with conviction** | MEDIUM | Article index is DATA (what was published). Recommendations are JUDGMENT. Never conflate. |

---

## 11. Architect Recommendation

### Best next implementation slice

**`portfolio_news.json` catalysts → `article_index`** — persist today's scored catalysts with URL-based dedupe. Same pattern as all prior tasks. ~1.5 hours.

### What remains deferred

| Deferred | Until |
|----------|-------|
| Watchlist article coverage | After watchlist enrichment expansion |
| Article frequency escalation | After article_index accumulates 7+ days |
| Notification content from articles | Phase E |
| Full article text storage | Likely never needed (titles + summaries sufficient) |
| Sentiment model expansion | Phase D (external models) |

### Should this come before notification planning?

**Yes.** Notifications need article context for quality. The index must exist before notification content can reference specific articles.

### Should this come before richer recommendation logic?

**Yes.** Richer recommendations should cite specific catalysts. The index makes this possible.

---

## Appendix

### Sample article_index row

```json
{
  "id": 1,
  "ingested_at": "2026-04-20T21:08:00",
  "published_at": "2026-04-20T05:30:58+00:00",
  "title": "Visa's (V) Strong Moat To Bring Further Upside In The Stock",
  "url": "https://finnhub.io/api/news?id=6111db7e...",
  "source": "Yahoo",
  "provider": "finnhub",
  "symbols": ["V"],
  "portfolio_symbol": "V",
  "relevance_score": 75,
  "impact_tier": "medium_impact",
  "llm_category": "analyst",
  "llm_urgency": "watch",
  "summary": "Bank of America's analyst upgrade on Visa highlights its strong moat...",
  "data": {"hours_old": 19.58, "is_fresh": false, "portfolio_weight": 3.4, "market_value": 40812.2, "recency_tier": "h12_to_72h"},
  "dedupe_key": "a3f7b2c9e1d45678ab"
}
```

### Sample dedupe_key strategy

```python
import hashlib
if url:
    dedupe_key = hashlib.md5(url.encode()).hexdigest()[:20]
else:
    dedupe_key = hashlib.md5(f"{title}|{source}|{published_at[:10]}".encode()).hexdigest()[:20]
```

### Sample article-to-symbol mapping

Article about "Visa and Mastercard payment volumes":
- `symbols = ['V', 'MA']`
- `portfolio_symbol = 'V'` (the one we hold)
- Both V and MA would be found via GIN index on `symbols`

### Sample future query examples

```sql
-- Articles for V in last 30 days
SELECT title, source, published_at, relevance_score
FROM article_index
WHERE 'V' = ANY(symbols) AND published_at >= now() - interval '30 days'
ORDER BY published_at DESC;

-- Article frequency by symbol this week
SELECT portfolio_symbol, COUNT(*) AS articles
FROM article_index
WHERE published_at >= now() - interval '7 days'
GROUP BY portfolio_symbol ORDER BY articles DESC;

-- High-impact analyst articles
SELECT title, portfolio_symbol, published_at
FROM article_index
WHERE impact_tier = 'high_impact' AND llm_category = 'analyst'
ORDER BY published_at DESC LIMIT 10;
```

---

*Article index plan created 2026-04-20. Awaiting architect approval before implementation.*
