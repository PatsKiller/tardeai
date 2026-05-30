# Hermes Source Discovery and Site Memory Design

**Date:** 2026-05-30
**Status:** DESIGN ONLY — not implemented

---

## 1. Problem

Hermes can browse the web but has no memory of which sites were useful, which URLs to revisit, or how to discover new research sources for specific tickers/strategies. Each research session starts from scratch.

---

## 2. Design Goals

1. Hermes remembers which URLs/sites produced useful research context
2. Hermes discovers new sources during research and logs them for future use
3. Sources are scored by quality, relevance, and freshness
4. Hermes can build per-ticker and per-strategy source portfolios
5. The operator can review, approve, or block sources
6. All source data lives in hermes_* staging tables (database-first)

---

## 3. Proposed Schema

### `hermes_research_sources` (new staging table)

```sql
CREATE TABLE hermes_research_sources (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    source                TEXT NOT NULL DEFAULT 'hermes' CHECK (source = 'hermes'),
    hermes_agent_name     TEXT NOT NULL,

    -- Source identity
    url                   TEXT NOT NULL,
    domain                TEXT NOT NULL,
    page_title            TEXT,
    source_type           TEXT NOT NULL CHECK (source_type IN (
        'earnings_transcript',
        'analyst_report',
        'news_article',
        'sec_filing',
        'company_investor_relations',
        'financial_data_page',
        'sector_research',
        'etf_holdings',
        'dividend_data',
        'technical_chart',
        'social_discussion',
        'youtube_channel',
        'podcast_transcript',
        'government_data',
        'industry_report',
        'other'
    )),

    -- Context
    symbol                TEXT,
    strategy_type         TEXT,
    topics                TEXT[] DEFAULT '{}',

    -- Quality
    quality_score         REAL CHECK (quality_score >= 0 AND quality_score <= 1),
    relevance_score       REAL CHECK (relevance_score >= 0 AND relevance_score <= 1),
    freshness_rating      TEXT CHECK (freshness_rating IN ('realtime','daily','weekly','monthly','quarterly','annual','static')),
    paywall               BOOLEAN DEFAULT FALSE,
    requires_auth         BOOLEAN DEFAULT FALSE,

    -- Discovery
    discovered_from       TEXT,
    discovery_method      TEXT CHECK (discovery_method IN (
        'browsing',
        'link_follow',
        'search_result',
        'trade_ai_existing',
        'operator_provided',
        'hermes_recommendation'
    )),
    discovery_research_id BIGINT REFERENCES hermes_research_intelligence(id),

    -- Usage tracking
    times_accessed        INTEGER DEFAULT 1,
    last_accessed_at      TIMESTAMPTZ DEFAULT NOW(),
    last_useful           BOOLEAN,
    cumulative_value_score REAL DEFAULT 0,

    -- Lifecycle
    status                TEXT NOT NULL DEFAULT 'discovered'
                          CHECK (status IN ('discovered','validated','approved','blocked','stale','archived')),
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    block_reason          TEXT,

    UNIQUE(url, symbol)
);

CREATE INDEX idx_hrs_domain ON hermes_research_sources(domain);
CREATE INDEX idx_hrs_symbol ON hermes_research_sources(symbol);
CREATE INDEX idx_hrs_type ON hermes_research_sources(source_type);
CREATE INDEX idx_hrs_status ON hermes_research_sources(status);
CREATE INDEX idx_hrs_quality ON hermes_research_sources(quality_score DESC);
CREATE INDEX idx_hrs_accessed ON hermes_research_sources(last_accessed_at DESC);
```

---

## 4. Source Discovery Workflow

```
Hermes Research Agent
    ↓ browses page during research
    ↓ evaluates: was this useful?
    ↓
If useful:
    ↓ INSERT into hermes_research_sources
    ↓ status='discovered'
    ↓ quality_score from content assessment
    ↓ link back to research_id that used it
    ↓
If finds links to other relevant pages:
    ↓ INSERT each as status='discovered'
    ↓ discovery_method='link_follow'
    ↓ lower initial quality_score (unverified)
    ↓
Operator dashboard shows discovered sources
    ↓ operator reviews → status='approved' or 'blocked'
    ↓
Next research session:
    ↓ Hermes queries hermes_research_sources
    ↓ WHERE symbol=X AND status IN ('approved','validated')
    ↓ ORDER BY quality_score DESC, last_accessed_at DESC
    ↓ Gets curated source list for this ticker
    ↓ Browses approved sources first
```

---

## 5. Source Memory Integration

### Per-Ticker Source Portfolio

When Hermes researches a ticker, it first checks for known sources:

```sql
SELECT url, domain, source_type, quality_score, last_accessed_at
FROM hermes_research_sources
WHERE symbol = 'AAPL'
  AND status IN ('approved', 'validated')
ORDER BY quality_score DESC, last_accessed_at DESC
LIMIT 10;
```

This gives Hermes a curated starting point instead of searching blindly.

### Cross-Ticker Source Reuse

Good sources discovered for one ticker may apply to others:

```sql
-- Find sources useful across multiple symbols
SELECT domain, source_type, COUNT(DISTINCT symbol) AS symbols_served,
       AVG(quality_score) AS avg_quality
FROM hermes_research_sources
WHERE status IN ('approved', 'validated')
GROUP BY domain, source_type
HAVING COUNT(DISTINCT symbol) >= 3
ORDER BY avg_quality DESC;
```

### Source Staleness Detection

```sql
-- Flag sources not accessed in 30 days
UPDATE hermes_research_sources
SET status = 'stale', updated_at = NOW()
WHERE status IN ('approved', 'validated')
  AND last_accessed_at < NOW() - INTERVAL '30 days';
```

---

## 6. Quality Scoring

When Hermes accesses a source during research, it scores it:

| Factor | Weight | Assessment |
|--------|--------|------------|
| Content relevance to query | 30% | Did this page answer the research question? |
| Data freshness | 20% | How recent is the data on this page? |
| Source credibility | 20% | Is this a known reputable source? |
| Unique information | 15% | Did this provide info not available elsewhere? |
| Accessibility | 15% | No paywall, fast load, structured content |

`quality_score = weighted_sum / 100` (0.0–1.0)

After each access, `cumulative_value_score` is updated:

```
cumulative_value_score = (cumulative_value_score * (times_accessed - 1) + quality_score) / times_accessed
```

---

## 7. Seed Sources

Initial source list to bootstrap Hermes research (operator-approved):

| Domain | Type | Coverage |
|--------|------|----------|
| finance.yahoo.com | financial_data_page | All tickers — quotes, financials, news |
| seekingalpha.com | analyst_report | Earnings, analysis (may paywall) |
| finviz.com | technical_chart | Screeners, charts, fundamentals |
| macrotrends.net | financial_data_page | Historical financials, ratios |
| earningswhispers.com | earnings_transcript | Earnings calendar, estimates |
| dividenddata.com | dividend_data | Dividend history, ex-dates |
| sec.gov/cgi-bin/browse-edgar | sec_filing | 10-K, 10-Q, 8-K filings |
| fred.stlouisfed.org | government_data | Economic indicators |
| etfdb.com | etf_holdings | ETF holdings, comparisons |
| tradingview.com | technical_chart | Charts (may need login) |

These would be inserted as `status='approved'` with `discovery_method='operator_provided'`.

---

## 8. Dashboard Integration (future)

A "Hermes Sources" panel in the Command Center could show:

- Discovered sources pending review
- Approved source portfolio per ticker/strategy
- Source quality leaderboard
- Stale sources needing refresh
- Blocked sources with reasons

---

## 9. Implementation Phases

| Phase | Scope | Requires |
|-------|-------|----------|
| **Design** (this doc) | Architecture only | Done |
| **Phase 1**: Create table | `hermes_research_sources` migration | Operator approval |
| **Phase 2**: Seed sources | Insert operator-approved seed URLs | Operator approval |
| **Phase 3**: Agent integration | Hermes logs sources during research | Agent workflow design |
| **Phase 4**: Source-first research | Hermes checks sources before browsing | Agent workflow update |
| **Phase 5**: Dashboard | Source management UI in Command Center | Dashboard approval |

---

## 10. Safety

- hermes_research_sources is a hermes_* staging table — same security model
- Source URLs are public web pages only — no internal/private URLs
- Paywall/auth-required pages are flagged but not bypassed
- Operator can block any source
- No source data goes to production tables without promotion
- Browser runs headless, local-only, no cloud proxy
