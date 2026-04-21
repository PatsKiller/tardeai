# OpenClaw Market Intelligence + Watchlist Data-Layer Plan

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Tier 1-3 complete, OpenClaw Phase A1+A2 complete

---

## 1. Executive Summary

### What this layer is

A unified historical market-intelligence and watchlist data architecture that stores daily snapshots of ticker-level fundamentals, technical indicators, analyst data, and article metadata — for BOTH current holdings AND watchlist candidates — enabling the advisor to answer questions like "how has analyst consensus shifted on V over 3 months?" or "what happened to SCHD's yield last quarter?"

### Why it is needed before recommendation quality can be trusted

Recommendations without historical context are guesses. The advisor currently sees only today's snapshot (via ticker_enrichment_cache). To generate quality recommendations, it needs:
- **Trend detection:** "Is this RSI spike anomalous or normal for this ticker?"
- **Analyst shift detection:** "Did analysts just change their consensus, or has it been declining for weeks?"
- **Yield continuity:** "Has this dividend been growing, stagnant, or declining?"
- **Watchlist tracking:** "Has this candidate improved since we started watching it?"

### How it supports both portfolio holdings and watchlists

Same schema stores data for both held positions AND watchlist candidates. The `source_type` field distinguishes "I own this" from "I'm watching this" from "the AI suggested this."

---

## 2. Current-State Assessment

### Finviz data already captured

| Cache | Fields | Cadence | Historical? |
|-------|--------|---------|:-:|
| `finviz_quote_cache.json` | 16 fields (price, change, volume, perf periods, volatility, rvol) | Every 30min market hours | **NO** — overwritten |
| `ticker_enrichment_cache.json` | 43 fields (full Finviz: RSI, beta, ATR, SMA, float, insider, short, institutional, sector, industry, earnings) | 6-hour TTL | **NO** — overwritten |

**43 fields per ticker** already captured from Finviz Elite views 111/121/131/141/171. All overwritten on refresh — zero history preserved.

### Yahoo data already captured

| Source | What | Historical? |
|--------|------|:-:|
| `price_cache.json` + `price_cache` table | OHLCV daily prices back to 2020 | **YES** (Postgres) |
| yfinance in orchestrator | Fidelity fund returns (1M/3M/6M/1Y) | **NO** — computed live |

No fundamental data (P/E growth, revenue, margins, guidance) stored from Yahoo.

### Portfolio/watchlist state already exists

| File | Content | Entries |
|------|---------|---------|
| `watchlist.json` | User-curated watchlist: {symbol: {thesis, target_intent, added, notes}} | 5 tickers (PLTR, HII, GD, BWXT, AXON) |
| `watchlist_intelligence.json` | Pipeline output with sizing opportunities, V concentration, defense % | Derived |
| `holdings.json` | Live portfolio positions | 44 positions |

### What is missing for historical intelligence

| Missing | Impact |
|---------|--------|
| **Enrichment history** | Can't detect "RSI trending down for 2 weeks" or "institutional ownership shifting" |
| **Analyst consensus history** | Can't detect "3 downgrades this month" or "target price falling" |
| **Article metadata index** | Can't deduplicate articles or track catalyst frequency |
| **Watchlist candidate history** | Can't track "PLTR improved from $55 to $72 since we started watching" |
| **Yahoo fundamentals snapshots** | Can't track "revenue growth declining 3 quarters" |

---

## 3. Finviz Data Coverage Plan

### Field classes (43 fields currently captured)

| Class | Fields | Current | Desired Historical Cadence |
|-------|--------|---------|---------------------------|
| **Price/Volume** | price, prev_close, change_pct, volume, rvol, gap_pct, change_from_open_pct | Every 30min (quote cache) | Daily close snapshot |
| **Performance** | perf_week, perf_month, perf_quarter, perf_halfyr, perf_ytd, perf_year | 6-hr TTL | Daily snapshot |
| **Technical** | rsi, sma20_pct, sma50_pct, sma200_pct, atr, beta, trend, rsi_status, volatility_w, volatility_m | 6-hr TTL | Daily snapshot |
| **Valuation** | pe, market_cap_b | 6-hr TTL | Weekly snapshot |
| **Ownership/Short** | insider_own_pct, insider_trans_pct, inst_own_pct, inst_trans_pct, short_float_pct, short_ratio | 6-hr TTL | Weekly snapshot |
| **Float/Shares** | float_m, shares_outstanding_m, avg_vol_m, volume_base | 6-hr TTL | Weekly snapshot |
| **52-week** | week52_high_pct, week52_low_pct | 6-hr TTL | Daily snapshot |
| **Analyst** | recom (consensus), earnings_date, earnings_time | 6-hr TTL | Daily snapshot |
| **Descriptive** | company, sector, industry, country, symbol, ticker, cached_at | 6-hr TTL | Static (store once) |

### Storage decision per class

| Class | Store historically? | Cadence | Reason |
|-------|:---:|---------|--------|
| Price/Volume | **YES** | Daily | Trend detection, anomaly detection |
| Performance | **YES** | Daily | Period-return continuity |
| Technical | **YES** | Daily | RSI trend, SMA cross detection |
| Valuation | **YES** | Weekly | P/E trend for quality assessment |
| Ownership/Short | **YES** | Weekly | Insider/institutional shift detection |
| Float/Shares | No | — | Changes rarely, not analytically useful historically |
| 52-week | **YES** | Daily | Proximity-to-high/low trend |
| Analyst | **YES** | Daily | Consensus shift detection (most valuable!) |
| Descriptive | No | — | Static metadata, store once |

---

## 4. Yahoo Enhancement Plan

### What to capture from Yahoo (not yet stored)

| Data | Source | Cadence | Storage | Complements/Overrides |
|------|--------|---------|---------|----------------------|
| Forward P/E | yfinance `.info` | Weekly | Postgres | Complements Finviz trailing P/E |
| Revenue growth (YoY) | yfinance `.financials` | Quarterly | Postgres | Not in Finviz |
| Net margin | yfinance `.financials` | Quarterly | Postgres | Not in Finviz |
| Dividend history (actual payments) | yfinance `.dividends` | Monthly | Postgres | Complements dividend_calendar |
| Analyst mean/median target | yfinance `.analyst_price_targets` | Weekly | Postgres | Validates Finviz "recom" field |
| Shares outstanding trend | yfinance `.info` | Monthly | Postgres | Detects dilution |

### Priority for first implementation

1. **Analyst targets** (weekly) — most immediately useful for recommendation quality
2. **Forward P/E** (weekly) — growth assessment
3. Revenue/margin — quarterly (can wait)
4. Dividend history — already partially covered by `dividend_history` table

---

## 5. Historical Storage Strategy

### Daily snapshots (high-value, moderate volume)

| Entity | What | Rows/day | Storage |
|--------|------|----------|---------|
| Finviz enrichment snapshot | 30+ fields per ticker, all holdings + watchlist | ~50 rows × 30 fields | Postgres JSONB |
| Analyst consensus | target, recom, upgrades/downgrades | ~50 rows | Postgres columns |
| Technical indicator snapshot | RSI, SMA, beta, ATR, trend | ~50 rows | Part of enrichment snapshot |

### Event-driven (lower volume, high value)

| Entity | What | Trigger | Storage |
|--------|------|---------|---------|
| Article metadata | title, url, source, symbols, relevance, sentiment | On news ingestion | Postgres |
| Earnings events | date, EPS estimate, actual, surprise | On earnings | Postgres |
| Analyst rating changes | upgrade/downgrade, firm, old/new target | On change detection | Postgres |

### Proposed approach: One daily enrichment snapshot + separate analyst table

Rather than 7 separate tables for each Finviz field class, store **one daily JSONB snapshot per ticker** with all enrichment fields. This is simpler to maintain and the JSONB supports queries on individual fields when needed.

---

## 6. Watchlist Architecture

### Three watchlist sources

| Source | Owner | Write Path | Persistence |
|--------|-------|-----------|-------------|
| **User-added** | John (manual) | Command Center modal → API → Postgres + JSON | Permanent until removed |
| **AI-generated** | Portfolio advisor agent | Pipeline → Postgres | Expires after 30 days if not promoted |
| **Analyst-curated** | Manual review of analyst upgrades/targets | Manual or semi-automated | Permanent until removed |

### Unified watchlist model

```sql
CREATE TABLE IF NOT EXISTS watchlist_items (
    id serial PRIMARY KEY,
    symbol varchar(20) NOT NULL,
    source_type varchar(20) NOT NULL,    -- 'user'|'ai_generated'|'analyst_curated'
    thesis text,
    target_intent varchar(30),           -- 'growth'|'income'|'defense'|'speculative'|'swing'
    added_date date NOT NULL,
    added_by varchar(30) NOT NULL,       -- 'john'|'portfolio_agent'|'manual_review'
    confidence numeric(3,2),             -- AI-generated items have confidence
    status varchar(20) DEFAULT 'active', -- 'active'|'promoted'|'removed'|'expired'
    notes text,
    data jsonb,                          -- extra context (AI rationale, analyst firm, etc.)
    expires_at date,                     -- AI items expire; user items don't
    UNIQUE(symbol, source_type)
);
```

### Provenance fields

Every watchlist entry records:
- `source_type`: who put it there
- `added_by`: specific actor
- `added_date`: when
- `confidence`: how confident (AI items)
- `thesis`: why it's interesting
- `data`: any supporting evidence

### Query needs

- "Show all watchlist items by source"
- "Show AI-suggested items with confidence > 0.7"
- "What's been on the watchlist for >30 days without promotion?"
- "Show watchlist items where enrichment shows improving fundamentals"

---

## 7. Command Center UX Direction

### Minimum CC changes

| Feature | Priority | Effort |
|---------|:---:|--------|
| **User-added watchlist modal** | HIGH | 2-3 hours |
| Source-type badges (user/AI/analyst) | MEDIUM | 1 hour |
| Freshness/last-updated labels | LOW | 30 min |
| AI-generated watchlist tab | DEFERRED | Later |

### User-added watchlist modal design

Fields:
- Symbol (required)
- Thesis (optional, text)
- Intent (dropdown: growth, income, defense, speculative, swing)
- Notes (optional)

Save via `POST /api/watchlist/add` → writes to `watchlist_items` + `watchlist.json` (dual-write for CC compatibility)

### What should remain deferred

- AI-generated watchlist display (need agent to generate first)
- Analyst-curated display (need ingestion pipeline first)
- Historical watchlist performance tracking chart

---

## 8. Recommended Tables / Entities

### `ticker_snapshot_daily` — Daily enrichment snapshot

```sql
CREATE TABLE IF NOT EXISTS ticker_snapshot_daily (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    source varchar(20) DEFAULT 'finviz',
    rsi numeric(5,2),
    beta numeric(5,3),
    sma20_pct numeric(6,2),
    sma50_pct numeric(6,2),
    sma200_pct numeric(6,2),
    perf_week_pct numeric(6,2),
    perf_month_pct numeric(6,2),
    perf_ytd_pct numeric(6,2),
    week52_high_pct numeric(6,2),
    week52_low_pct numeric(6,2),
    analyst_recom varchar(10),
    data jsonb,                         -- all 43 fields as JSONB for full history
    created_at timestamptz DEFAULT now(),
    UNIQUE(snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_ticker_snapshot_date ON ticker_snapshot_daily(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_snapshot_symbol ON ticker_snapshot_daily(symbol);
```

**Purpose:** Daily record of every enriched ticker. Enables "RSI trend for V over past 30 days."  
**Cadence:** Once per pipeline run (after enrichment completes).  
**Dedup:** UNIQUE(snapshot_date, symbol). Same-day reruns upsert.  
**Volume:** ~50-80 tickers × 1/day = ~20K rows/year.

### `analyst_consensus_history`

```sql
CREATE TABLE IF NOT EXISTS analyst_consensus_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    mean_target numeric(10,2),
    recom_score numeric(4,2),           -- 1.0=Strong Buy, 5.0=Strong Sell
    buy_count integer,
    hold_count integer,
    sell_count integer,
    source varchar(20) DEFAULT 'finviz',
    data jsonb,
    UNIQUE(snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_analyst_date ON analyst_consensus_history(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_symbol ON analyst_consensus_history(symbol);
```

**Purpose:** Track analyst consensus shifts. "Did mean target drop this month?"  
**Cadence:** Daily (extract from enrichment cache).  
**Volume:** ~50 tickers/day = ~12K rows/year.

### `article_index`

```sql
CREATE TABLE IF NOT EXISTS article_index (
    id serial PRIMARY KEY,
    ingested_at timestamptz DEFAULT now(),
    published_at timestamptz,
    title text NOT NULL,
    url text,
    source varchar(50) NOT NULL,
    symbols varchar(20)[],
    relevance_score numeric(3,2),
    sentiment varchar(10),
    catalyst_type varchar(30),
    summary text,
    data jsonb,
    UNIQUE(url)
);
CREATE INDEX IF NOT EXISTS idx_article_published ON article_index(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_symbols ON article_index USING gin(symbols);
```

**Purpose:** Dedup articles, track catalyst frequency, enable "what news has V had this month?"  
**Cadence:** Event-driven (on news ingestion).  
**Dedup:** UNIQUE(url) prevents same article indexed twice.  
**Volume:** ~50 articles/day = ~12K/year.

### `watchlist_items`

(Schema shown in Section 6 above)

**Purpose:** Unified watchlist with provenance.  
**Cadence:** User-driven + AI-generated.  
**Volume:** 10-50 items total (small).

---

## 9. Recommended Smallest Implementation Slice

### Choice: `ticker_snapshot_daily` table + writer

**Why this first:**
1. The enrichment data already exists (`ticker_enrichment_cache.json` — 43 fields, 84 tickers)
2. No new API calls needed — just persist what's already being computed
3. Immediately enables "RSI trend" / "analyst consensus shift" / "performance trend" queries
4. Same proven dual-write pattern as all prior tasks
5. Unlocks historical context for recommendation quality

**What to build:**
1. Create `ticker_snapshot_daily` table
2. After enrichment cache is written in orchestrator, bulk-insert today's snapshot
3. Add `snapshots` query type to advisor_memory_reader (Steph can ask "show me V's RSI over 30 days")

**Estimated effort:** 2 hours (same pattern as action_signals_history)

**Why NOT watchlist first:**
- Watchlist changes require CC modal work (UI)
- `watchlist.json` already works for current needs
- Historical enrichment is more immediately useful for recommendation quality

---

## 10. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Overcollecting noisy fields** | MEDIUM | Store full JSONB in `data` column but only promote 10 key fields to queryable columns. |
| **Storing too much without query value** | LOW | 50 tickers × 365 days = 18K rows/year. Trivial for Postgres. Cost of storage << cost of missing data. |
| **Stale watchlist entries** | LOW | AI-generated items expire after 30 days. User items persist until manually removed. |
| **Confusing AI vs analyst watchlist** | MEDIUM | `source_type` field clearly labels provenance. CC displays source badges. |
| **Missing provenance** | MEDIUM | All tables require `source` field. No anonymous writes. |
| **Recommendation quality without history** | HIGH | This is exactly what this plan solves. Recommendation drafts should NOT be trusted until 14-30 days of snapshot history exist. |
| **Finviz rate limiting** | LOW | Already handled by existing enrichment pipeline (6-hr TTL, 100 req/hr). Snapshot just persists what's already cached. |

---

## 11. Architect Recommendation

### Best next implementation slice

**`ticker_snapshot_daily` — persist enrichment data historically.** This is the single highest-ROI addition because it:
- Costs nothing (data already cached)
- Enables trend detection immediately
- Supports analyst shift detection
- Provides historical context for recommendation drafts
- Same pattern as 12 prior successful tasks

### What remains deferred

| Deferred | Until |
|----------|-------|
| `analyst_consensus_history` (separate table) | After snapshot proves useful (or extract from snapshot JSONB) |
| `article_index` | Phase B (new ingestion pipeline needed) |
| `watchlist_items` (Postgres) | After CC modal work |
| Yahoo fundamentals | Phase B (new API integration) |
| AI-generated watchlist | After recommendation drafts are flowing |

### Should this come before or after recommendation-draft implementation?

**Can be parallel.** Recommendation drafts work with today's data (escalations + observations). Historical snapshots enrich FUTURE recommendations. Build both — drafts for immediate value, snapshots for growing intelligence depth.

**Recommended order:**
1. `ticker_snapshot_daily` (this plan) — start accumulating history NOW
2. Recommendation drafts (from escalations) — gives immediate advisory value
3. `analyst_consensus_history` — fast-follow once snapshots prove the pattern
4. `article_index` — requires news pipeline changes
5. Watchlist Postgres + CC modal — requires UI work

---

## Appendix

### Proposed Finviz field classes for snapshot

**Queryable columns (promoted):**
- `rsi`, `beta`, `sma20_pct`, `sma50_pct`, `sma200_pct`
- `perf_week_pct`, `perf_month_pct`, `perf_ytd_pct`
- `week52_high_pct`, `week52_low_pct`
- `analyst_recom`

**JSONB `data` column (full snapshot):**
All 43 fields stored as JSONB for complete historical record.

### Proposed source precedence rules

| Data Type | Primary Source | Fallback |
|-----------|---------------|----------|
| Live price | Finviz quote cache | Yahoo (via price_cache) |
| Technical indicators | Finviz enrichment | None |
| Analyst consensus | Finviz `recom` field | Yahoo analyst targets |
| Fundamentals (P/E) | Finviz | Yahoo `.info` |
| Dividend history | Pipeline dividend_calendar | Yahoo `.dividends` |
| Revenue/growth | Yahoo `.financials` | None (Finviz doesn't provide) |

### Sample watchlist_items row

```json
{
  "symbol": "PLTR",
  "source_type": "user",
  "thesis": "AI/defense data analytics — direct AI WWIII exposure",
  "target_intent": "growth_speculative",
  "added_date": "2026-04-03",
  "added_by": "john",
  "confidence": null,
  "status": "active",
  "notes": "",
  "expires_at": null
}
```

### Sample CC modal fields for user-added watchlist

| Field | Type | Required | Notes |
|-------|------|:---:|-------|
| Symbol | text input + autocomplete | Yes | Validates against Finviz/Yahoo |
| Thesis | textarea | No | Why watching |
| Intent | dropdown | No | growth, income, defense, speculative, swing |
| Notes | textarea | No | Freeform |

---

*Market intelligence + watchlist plan created 2026-04-20. Awaiting architect approval before implementation.*
