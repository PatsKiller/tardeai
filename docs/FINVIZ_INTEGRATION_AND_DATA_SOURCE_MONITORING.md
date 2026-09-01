# Finviz Integration + Data-Source Health Monitoring

Status:      ACTIVE
as_of:       2026-07-07T22:03:50-04:00
Measured at: efcc51365 / not measured

_Last updated: 2026-06-20_

Full use of Finviz Elite (one `FINVIZ_API_TOKEN`, no extra creds) across screeners, technicals/fundamentals,
news, charts, sector/industry performance, and insider context — plus a per-source health monitor that
catches silent feed failures. Advisory only.

---

## 1. Finviz capabilities (all live)

| Capability | Script | Endpoint(s) | Surface | Cadence |
|---|---|---|---|---|
| **Screeners** | `finviz_screener_runner.py` | — | discovery → watchlist | 10:00, 12:00 |
| **Screener membership** | (in runner) `_update_screener_membership` | — | `screener_symbol_membership` | every run |
| **Technicals + fundamentals** (~60 fields) | `finviz_enrichment.py` | `/api/v2/finviz-enrichment?symbol=` | drawer "Finviz metrics" panel | 13:00 daily |
| **News** | `finviz_news.py` + `finviz_proactive_research.py` | — | `news_articles(source='finviz_news')` | 9:30/11:30/13:30/15:30 |
| **Charts** | (image) | `charts2.finviz.com/chart.ashx` | drawer technical chart | on-demand |
| **Sector/industry perf** | `finviz_sector_research.py` | `/api/v2/sector-performance?type=sector\|industry` | SectorsHub panel | 10:15, 16:15 |
| **Insider** | (SEC Form-4, authoritative) | `/api/v2/insider-activity?symbol=` | drawer "Insider activity" | (sec_form4 ingest) |

### Endpoint reference URLs (Finviz Elite, `&auth=$FINVIZ_API_TOKEN`)
- Screener export: `export.ashx?v=…&f=…`
- Enrichment: `export.ashx` (5 views × batches of 20) → `data/state/ticker_enrichment_cache.json` (5k tickers)
- News (ticker-TAGGED Stock): `news_export.ashx?v=3` — **CSV** (`"Title","Source","Date","Url","Category","Ticker"`), `Ticker` is comma-sep for multi-ticker headlines
- Group performance: `grp_export.ashx?g=sector|industry&v=152` — CSV (Name/Change/P-E/Yield/Volume/Stocks)
- Chart image: `charts2.finviz.com/chart.ashx?t=TICKER&ty=c&ta=1&p=d&s=l`

### Notes / gotchas
- **News was broken**: `news_export.ashx` returns **CSV**, not JSON — `finviz_news.py` parsed 0 for months.
  Also `?t=TICKER` returns *untagged* market/blog news; `?v=3` returns ticker-tagged Stock news. Fixed.
- **Insider**: Finviz has **no clean insider CSV export** (`insidertrading_export.ashx` 404s; the HTML table is
  JS-rendered/fragile). We surface **SEC Form-4** (`sec_form4`, already ingested) — the authoritative source.
- **Enrichment storage**: the ~60 fields live in `ticker_enrichment_cache.json` (not a DB table); the endpoint
  mtime-caches it. Only a subset (price/rvol/float/atr/sector) is mirrored to the IER.

---

## 2. Data-Source Health Monitor

`/api/v2/data-source-health` → **System hub → Data Sources** tab. Per-source: last update, recent volume,
and status vs expected cadence — **live** (within cadence) / **slow** (1–2× late) / **stale** (2–4×) /
**dead** (>4× or no data). Covers news APIs (Yahoo RSS/Google/Finnhub/Benzinga/Seeking Alpha),
Finviz (News/screeners/enrichment/membership/sector/industry), FRED, YouTube, web-search lanes
(DuckDuckGo/Yahoo search — Brave retired 2026-07-07, see §4), Hermes research, catalysts, SEC Form-4.

### Why this exists — the DuckDuckGo lesson
DDG silently returned `[]` (no exception) for weeks after a markup/bot-gate change. **Job-level monitors saw
`topic_ingestion` exit 0 and reported healthy** — nothing compared each *sub-source's* output to its expected
cadence. The health monitor closes that gap: it flags a source `dead` on sight when its recent volume is 0 or
its last update is far past cadence (it immediately caught DDG + Brave dead, and screener-membership 33-days
stale). This is **per-source yield monitoring**, complementary to the job/freshness monitors.

### Age by INGEST time, not publish date (bug fix 2026-06-21, commit 3f9f0f9a)
The recovery test exposed a latent monitor bug: it aged news feeds by `max(published_at)`, but several
sources (DuckDuckGo, etc.) don't populate `published_at`. A feed producing fresh rows therefore read as
`dead` (`age=None`) — the exact false-negative the monitor exists to prevent. Fixed to age by
`max(created_at)` — when the feed last *delivered to us*, which is the correct freshness signal.

### Recovery verified (2026-06-21)
Firing the now-fixed jobs flipped the monitor `3 DEAD / 2 SLOW / 14 LIVE` → `1 DEAD / 18 LIVE`:
DuckDuckGo (ran topic_ingestion → 10 results saved) and Screener membership (ran a screener → membership
maintained) both went **dead → live**. Brave read dead — correctly: its free tier was exhausted (returned 0
items), so the monitor was honest, not buggy. Brave was later **retired** (§4) once the paid tier also 402'd.

---

## 2b. Finviz surfacing — where it shows (verified)

Finviz appears everywhere a symbol is rendered:

**Inline strip on card faces** (one shared `/api/v2/finviz-strip-map` call — mtime-cached, universe =
watchlist ∪ open proposals ∪ held): RSI (band-colored ≥70 red / ≤30 green) + perf Week/Month/YTD +
vs-50d-SMA (sign-colored).
- Watchlist cards (`WatchlistHub`) — **verified 200/200 covered**
- Portfolio holding cards (`PortfolioHub`) — **verified 38/38 held covered**
- Broker-proposal rows (`BrokerProposals`, compact RSI/W/YTD) — **verified via a temporary test proposal**:
  a non-watchlist/non-held ticker (KO) went `strip-map: False → True` purely because the proposal existed,
  the `/api/v2/broker-proposals` endpoint returned it, and `fvMap[symbol]` resolved → strip renders. Test
  proposal was placed on a `schwab_taxable` (no-trading-API) account so it could not route, then deleted
  (0 rows left). 2026-06-21.

**Detail drawer** (click any card): Finviz technical chart → grouped metrics panel
(`/api/v2/finviz-enrichment`: Technicals/Performance/Valuation/Fundamentals/Ownership) → insider Form-4.

## 3. Fixes shipped 2026-06-20
- **DuckDuckGo**: GET→POST + desktop UA (+ ad-link filter). 0 → 10 results.
- **Screener membership**: the runner now maintains `screener_symbol_membership` every run
  (reset → present `seen++`/`miss=0` → age fall-offs `dropped`/`stale@3`/`expired@7`). Was a month stale.
- **Finviz news**: CSV parse + `v=3` ticker-tagged + multi-ticker split. 0 → 180/ticker.

## 4. Topic-search lane changes 2026-07-07 (Brave retired · YouTube throttled · Yahoo added)

Two `topic_ingestion` web/video lanes were reading **dead** on the board — both were external quota/billing
exhaustion, **not code bugs** (confirmed against the live `/api/v2/data-source-health` endpoint; a stale
`health_agent_status.json` had earlier misattributed this to "Yahoo", which was never dead — **Yahoo RSS was
live throughout**).

- **Brave (topic) → HTTP 402 Payment Required** (account credits exhausted; last row 2026-07-02).
  **Retired**: `search_brave_news` no-ops behind `TOPIC_BRAVE_ENABLED` (default off) and its board SPEC
  (`topic_brave_news`) was removed. Re-enable = set `TOPIC_BRAVE_ENABLED=1` **and** re-add the SPEC line.
- **YouTube (topic API) → HTTP 429** "Search Queries per day" quota exhausted (GCP project 204441234483;
  `search.list` = 100 units/call, default 10k/day ≈ 100 searches; dead 2026-06-21→07-07 because one run burned
  the whole budget then 429'd all day). **Throttled**: persistent daily budget
  `data/portfolios/state/youtube_search_budget.json`, cap `YOUTUBE_SEARCH_DAILY_CAP` (default 80), per-query
  cache, and a 429 circuit-break for the rest of the day. Recovers on its own after the midnight-Pacific reset.
- **Yahoo Finance search added** as the free/keyless replacement for Brave → DB source `topic_yahoo_search`,
  board row "Yahoo search (topic)". Uses `query1/query2.finance.yahoo.com/v1/finance/search` with host
  rotation. Finance/ticker-oriented (strong for symbol topics; Google News RSS + DDG cover the general side).
  **Gotcha**: Yahoo's `providerPublishTime` is epoch seconds — converted to ISO before `_save_article`, else
  the `timestamptz` insert on `published_at` silently rejects every row.

Pipeline order is now `[1/5] YouTube → [2/5] Google News → [3/5] Yahoo search → [4/5] Brave (retired no-op) →
[5/5] DuckDuckGo`. Board after fix: Yahoo search **live**, Brave off-board, DDG live, YouTube dead until the
next quota reset.

## Files
- `scripts/topic_ingestion.py` → `search_yahoo_news`, `search_brave_news` (gated), `_youtube_search` +
  `_yt_budget_*` quota guard, `process_topic` SOURCE 3/4/5 blocks
- `scripts/finviz_screener_runner.py`, `finviz_enrichment.py`, `finviz_news.py`,
  `finviz_proactive_research.py`, `finviz_sector_research.py`
- `scripts/api_v2.py` → `_data_source_health`, `_sector_performance`, `_insider_activity`, `_finviz_enrichment`
- `apps/command-center-v3/src/components/` → `DataSourceHealth`, `FinvizSectorPanel`, `FinvizEnrichmentPanel`,
  `InsiderActivity`; `DetailDrawer` (chart + metrics + insider sections); `pages/SystemHub`, `pages/SectorsHub`

See also `HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`, `RESEARCH_INGEST_TICKER_AUDIT_2026_06_20.md`.
