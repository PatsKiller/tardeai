# Finviz Integration + Data-Source Health Monitoring

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
**dead** (>4× or no data). Covers 19 feeds: news APIs (Yahoo/Google/Finnhub/Benzinga/Seeking Alpha),
Finviz (News/screeners/enrichment/membership/sector/industry), FRED, YouTube, web-search lanes
(DuckDuckGo/Brave), Hermes research, catalysts, SEC Form-4.

### Why this exists — the DuckDuckGo lesson
DDG silently returned `[]` (no exception) for weeks after a markup/bot-gate change. **Job-level monitors saw
`topic_ingestion` exit 0 and reported healthy** — nothing compared each *sub-source's* output to its expected
cadence. The health monitor closes that gap: it flags a source `dead` on sight when its recent volume is 0 or
its last update is far past cadence (it immediately caught DDG + Brave dead, and screener-membership 33-days
stale). This is **per-source yield monitoring**, complementary to the job/freshness monitors.

---

## 3. Fixes shipped 2026-06-20
- **DuckDuckGo**: GET→POST + desktop UA (+ ad-link filter). 0 → 10 results.
- **Screener membership**: the runner now maintains `screener_symbol_membership` every run
  (reset → present `seen++`/`miss=0` → age fall-offs `dropped`/`stale@3`/`expired@7`). Was a month stale.
- **Finviz news**: CSV parse + `v=3` ticker-tagged + multi-ticker split. 0 → 180/ticker.

## Files
- `scripts/finviz_screener_runner.py`, `finviz_enrichment.py`, `finviz_news.py`,
  `finviz_proactive_research.py`, `finviz_sector_research.py`
- `scripts/api_v2.py` → `_data_source_health`, `_sector_performance`, `_insider_activity`, `_finviz_enrichment`
- `apps/command-center-v3/src/components/` → `DataSourceHealth`, `FinvizSectorPanel`, `FinvizEnrichmentPanel`,
  `InsiderActivity`; `DetailDrawer` (chart + metrics + insider sections); `pages/SystemHub`, `pages/SectorsHub`

See also `HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`, `RESEARCH_INGEST_TICKER_AUDIT_2026_06_20.md`.
