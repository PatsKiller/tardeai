# Data Architecture Audit — 2026-07-31

**Status:** Findings complete. Remediation tracked via [`config/data_registry.yaml`](../config/data_registry.yaml)
and the Data Management page (`/v3/data` — System hub → Data). This document is the permanent record of
*what was actually happening* the day the audit was run; treat it as historical evidence, not a live status
board — for live status, read the registry + `/api/v2/data/coverage`.

**Scope:** every data type used across the site (technical/price data on stocks and holdings, 20-day/50-day
levels, support/resistance, analyst information, catalysts, news/social, research intelligence) — where it
comes from, how many sources feed it, how it is aggregated on the server, and every place (page + alert) that
consumes it.

---

## 1. Executive summary

The system ingests from **~30 external sources** through **~55 primary ingestion scripts**, but there is
**no shared data broker** — each domain (quotes, technicals, catalysts, portfolio aggregates) has multiple
independent producers that were built at different times for different call sites, and never consolidated.
Concretely:

| Problem | Scale | Worst offenders |
|---|---|---|
| Parallel "last price" pipelines | 6+ | Finviz repricer, Alpaca→Finviz→Yahoo ingest, `market_quote_provider.get_best_quote` waterfall, ~40 ad-hoc `yfinance` callers, SnapTrade overlay, Schwab sync |
| Independent RSI/SMA/ATR computation | 8–10 modules | `indicator_engine`, `ohlc_charts`, `pullback_macd_screener`, `holding_protection_advisor`, `holdings_gain_guardian`, `technicals_gap_backfill`, `fund_technicals_enrich`, `trade_backtest_engine`, plus Finviz-scraped values |
| Daily-close OHLCV stored redundantly | 3 stores | `price_cache` (JSON+DB), `ticker_prices`, `market_ohlcv_bars` — all yfinance-fed at times |
| Catalyst "verified" definitions | 10 distinct definitions | scoring relevance, impact tiers, 2 typed taxonomies, social-route rule, Hermes types, Ollama types, warrior exception, strategy gate, RVOL/gap proxy |
| Analyst data feeds | 4 separate endpoints | `pro-analyst/pills`, `analyst-detail`, `reports/analyst/*`, `symbol-cards.analyst` — no shared authority ranking |
| Support/resistance products | 2 products + 1 fallback | closed-session prefs cache, trade-plan proposal fields, and ad-hoc text-parse fallback on Re-Entry |
| Redundant `holdings.json` reads | ~83 in `api_v2.py` alone (~200 repo-wide) | `/overview`, `/portfolio/holdings`, `/risk`, `/portfolio/book-map` each independently re-read and re-aggregate |
| Alerts fetching data ad hoc | 17 scripts | `holdings_gain_guardian`, `portfolio_live_monitor`, `watchlist_entry_planner`, `pullback_macd_screener`, `ask_alerts`, `ipo_lockup_alert`, `open_trade_monitor` |

**Net effect:** the same symbol can show a different price, a different RSI, a different "has a catalyst"
answer, and a different analyst rating depending on which page or which alert you're looking at — not
because any one path is wrong, but because there are 3–10 independently-maintained paths per data type and
no single source of truth enforces agreement.

**What already exists and should NOT be rebuilt:**
- `state/hermes/outcome_bus.json` — a versioned read model with atomic publish, history, single writer, many
  readers. This is exactly the pattern a data broker needs; it is being generalized, not replaced.
- `data_source_health` table + `scripts/lib/data_source_report.py` + System hub "Data Sources" tab +
  `scripts/source_maturity.py` — passive per-source liveness/maturity scoring already exists.
- `data/runtime/*_latest.json` + `warm_caches.py` — cron materialization pattern already used by
  trade-ai/rotation/defense/symbol-cards.
- `market_quote_provider.get_best_quote` — the canonical multi-provider quote waterfall already exists
  (Alpaca → Schwab → Polygon → Finnhub → FMP → yfinance → Finviz cache); it is simply not universally used.
- `config/agents_data_sources.yaml` — an agent-facing (Alex/Maria/Steph/Risk/Aegis) view of which sources
  feed which agent, narrower in scope than the full registry below but a useful precedent.
- `scripts/lib/analyst_rating_canonical.py` — already documents that Finviz `recom` (1–5) is NOT Street
  consensus and points callers to `pro_analyst_pills_latest.json` — i.e., the analyst-source confusion below
  was already partially recognized in-repo.

---

## 2. External source inventory (~30 sources, ~55 ingestion scripts)

### Brokers
| Source | Transport | Provides | Primary scripts | Lands in |
|---|---|---|---|---|
| Schwab | REST OAuth | positions, transactions, L1 quotes, L2 stream | `schwab_position_sync.py`, `schwab_transaction_ingest.py`, `schwab_stream_daemon.py`, `schwab_transport.py` | `holdings.json`, `trade_transactions`, `schwab_stream_quotes/book` |
| Alpaca | REST | paper positions/orders, live read, market snapshots/bars | `alpaca_paper_adapter.py`, `alpaca_live_read_sync.py`, `market_quote_provider.py`, `external_market_data_ingest.py` | `paper_trades`, `holdings.json`, `market_quotes` |
| SnapTrade (Fidelity bridge) | SnapTrade SDK | positions/NAV, activity | `snaptrade_sync.py`, `snaptrade_activity_ingest.py` | `holdings.json`, `trade_transactions` |
| Moomoo/Futu | Local OpenD TCP | positions + cash (read-only) | `moomoo_live_read_sync.py`, `moomoo/client.py` | `holdings.json` |

### Market data / fundamentals
| Source | Scripts | Notes |
|---|---|---|
| Finviz Elite | `finviz_screener_runner.py`, `finviz_enrichment.py`, `finviz_ingestion.py`, `finviz_news.py`, `finviz_sector_research.py`, `finviz_market_movers.py` | 7 capabilities: screeners, ~60-field enrichment, news, charts, sector perf, insider fallback |
| yfinance/Yahoo | `external_market_data_ingest.py`, `pro_analyst_fetch.py`, `price_db_sync.py`, ~40 more | Widest blast radius; most-duplicated fetch surface |
| Alpaca market data | `market_quote_provider.py`, `market_data_snapshot_loader.py` | Primary tier in quote waterfall |
| Polygon | `market_data_snapshot_loader.py`, `discovery_sources/polygon_source.py` | OHLCV, options flow, news |
| Finnhub | `news_ingestion.py`, `market_quote_provider.py` | Quotes + company news |
| FMP | `sync_dividend_data.py`, `economic_calendar.py` | Dividends, calendar, quote fallback |
| Alpha Vantage | `external_market_data_ingest.py` | Fundamentals OVERVIEW + scored news |
| FRED | `fred_data_ingest.py` | Macro series |
| SEC EDGAR | `sec_data_ingest.py` | Form 4 insider |

### News & social
Yahoo RSS, Google News RSS, Finviz news, Benzinga, NewsAPI, StockTwits, Reddit, X (optional), YouTube (Data
API + transcripts), DuckDuckGo, SearXNG (local meta-search), Brave (retired, gated off).

### LLM / research lanes
Grok (OAuth proxy `:8645`), ChatGPT (OAuth proxy `:8646`), Claude (metered, escalation only), local Ollama
(`:11434`) — all feed `hermes_external_research` / `hermes_research_intelligence`.

### Analyst data
Yahoo consensus (`pro_analyst_fetch.py`), Hermes LLM-filled coverage for thin-Yahoo names
(`hermes_analyst_coverage.py`), ETF look-through proxy, and a metadata-only source-maturity registry.

### Telegram
Inbound commands/callbacks (`telegram_command_handler.py`), outbound alerts (`telegram_transport.py` via
`telegram_alert.py` chokepoint).

### Overlapping ingestion (same domain, independently pulled)
- **News**: `news_ingestion.py` + `finviz_proactive_research.py` + `topic_ingestion.py` +
  `catalyst_enrichment.py`/`catalyst_news_sources.py` + Alpha Vantage NEWS_SENTIMENT + `hermes_news_bridge.py`.
- **Quotes**: Alpaca/Finviz/yfinance inside `external_market_data_ingest.py`, PLUS the independent
  `market_quote_provider.py` waterfall, PLUS `run_proactive_quote_refresh.py`, PLUS `price_db_sync.py`.
- **Social**: `social_ingest.py` vs `social_monitor.py` vs `aegis_social_sentiment.py`.
- **YouTube**: cron `youtube_transcript_ingest.py` vs `topic_ingestion.py` vs `hermes_youtube_discovery.py`.
- **Analyst consensus**: Yahoo via `pro_analyst_fetch.py` vs Hermes LLM fill vs ETF proxy.

---

## 3. Technical/price data: producers and duplication

### Quote ("last price") paths
| # | Path | Function | Writes to |
|---|---|---|---|
| 1 | Canonical waterfall | `market_quote_provider.get_best_quote` (Alpaca→Schwab→Polygon→Finnhub→FMP→yfinance→Finviz cache) | via proactive refresh |
| 2 | Portfolio reprice | `portfolio_repricer._fetch_finviz` | `holdings.json` prices, `finviz_quote_cache.json` |
| 3 | External ingest | `ingest_quotes` (Alpaca→Finviz→yfinance) | `market_quotes` |
| 4 | Finviz enrichment export | `finviz_enrichment.enrich_tickers` | `ticker_enrichment_cache.json` |
| 5 | Portfolio technical scrape | `portfolio_technical.get_technical_data` | `technical_snapshot.json` |
| 6 | Yahoo price history | `portfolio_price_cache.py` | `price_cache.json` + DB `price_cache` |
| 7 | Daily ticker prices | `price_db_sync.py` | `ticker_prices` |
| 8 | Ad-hoc yfinance | ~40 individual scripts | usually none (local var) |

### Indicators — duplicate producers
| Indicator | Modules computing it | Divergence |
|---|---|---|
| RSI(14) | `indicator_engine`, `ohlc_charts`, `pullback_macd_screener`, `holding_protection_advisor`, `holdings_gain_guardian`, `technicals_gap_backfill`, `fund_technicals_enrich`, `trade_backtest_engine`, Finviz scrape | 8+ implementations, different bar sources |
| SMA 20/50/200 | `indicator_engine`, screeners, `holdings_gain_guardian`, Finviz `%` distances | Same value computed N ways |
| MACD | `indicator_engine` (real MACD), `ohlc_charts`, `pullback_macd_screener`, **`portfolio_technical` approximates MACD via SMA20 vs SMA50** | **Formula mismatch, not just duplication** |
| ATR(14) | 10+ modules (`indicator_engine`, `fib_swing_engine`, screeners, protection advisor, gain guardian, chart patterns, scalp modules, defense) | Mixed Finviz $ATR vs computed |
| RVOL | Finviz session RVOL vs `premarket_rvol` Yahoo recompute vs `scalp_ignition_scorer` RVOL_tod (1m Alpaca profile) | **3 different definitions sharing one name** |
| Support/Resistance | `materialize_watchlist_strategy_cards` (20d H/L), `portfolio_technical` (SMA-as-levels), `lib/reentry_resistance` (hold/breakout) | **3 algorithms, one concept** |
| Re-entry levels | `lib/reentry_resistance.py`, `lib/reentry_shared_context.py`, `lib/reentry_rotation_alerts.py` | Multiple surfaces, shared refresh via `watch_alerts_eval.py` |
| VWAP | `indicator_engine`, `compute_intraday_vwap.py`, `ohlc_charts`, `pullback_macd_screener` | Session vs daily-ish variants |

### OHLCV / daily-close storage (3 overlapping stores)
`price_cache` (JSON+DB) · `ticker_prices` (DB) · `market_ohlcv_bars` (DB, multi-timeframe) — all populated
from yfinance at various points, with different readers (perf history/options vs S-R/re-entry vs proposal
technical snapshots).

### Holdings (`data/portfolios/state/holdings.json`)
- **Writers** (must go through `holdings_guard.protected_holdings_write`, `MIN_TOTAL ≈ $1M`): Schwab sync,
  SnapTrade merge, Alpaca live read, Moomoo live read, `/api/import`, repricer.
- **Readers**: ~200+ files repo-wide; ~83 independent loads inside `api_v2.py` alone.

---

## 4. Catalyst data: 10 definitions, 1 concept

| # | Definition | Location | What counts |
|---|---|---|---|
| D1 | Research-priority proxy (price action, not news) | `research_scheduler.catalyst_signals` | RVOL≥5 or \|gap\|≥10, or recent `momentum_catalyst` research |
| D2 | Headline relevance → `catalyst_verified` | `scoring.py` | ticker/company match, score ≥0.3 |
| D3 | Impact-tier news enrichment | `catalyst_enrichment.py` | high/medium/low/noise keyword buckets |
| D4 | Typed event taxonomy | `news_to_catalyst.py` + `catalyst_classifier.py` | earnings_beat, fda_approval, analyst_upgrade, … |
| D5 | Proposal quality taxonomy | `proposal_catalyst_quality.py` | STRONG_COMPANY_SPECIFIC … STALE_CATALYST |
| D6 | Social-route "verified" | `social_route_policy.py` | looser: any medium/high-impact news ⇒ verified |
| D7 | Hermes researcher types | `hermes_momentum_catalyst_researcher.py` | earnings/analyst/regulatory/manda/offering/… |
| D8 | Ollama catalyst types | `catalyst_intelligence.py` | fda/earnings/ma/dilution/upgrade/partnership/other |
| D9 | Warrior exception (catalyst optional) | `lib/catalyst_exception.py` | high RVOL/gap runners can skip catalyst |
| D10 | Strategy config gate | `config/strategies/momentum_scalp.yaml` | requires `catalyst_verified` for live/A+ |

**Storage** spans `trade_ai_scans`, `paper_trade_proposals`, `catalyst_events` (+ 4 satellite tables),
`hermes_research_intelligence`, `intelligence_entities`, `incubator_universe`.

**Concrete product bugs found:**
- Watchlist UI shows `catalyst_events` headlines with **no verified/confidence model**; Broker cards require
  `verified` + confidence ≥30 for the same symbol — can disagree.
- `continuous_runner.py` broadcasts `catalyst_verified: True` on the live WS feed **regardless of the scored
  value** (the DB write uses the real scored value; only the WS broadcast is hardcoded).
- Premarket social alerts persist headline text into `trade_ai_scans.catalyst` and fire a
  "PRE-MARKET CATALYST" Telegram message that the router then **suppresses as P2** — so the catalyst that
  triggered the UI display is invisible in the channel that supposedly announces it.
- `research_scheduler.catalyst_signals` (D1, price-action only) is consumed by things that expect a news
  catalyst — it is not one.

---

## 5. Server aggregation & caching

- `api_v2.py` (~47k lines) exposes **~495 GET routes** via a static `ROUTES` dict plus ~400+ dynamic
  branches inside `handle()` for POSTs.
- **No shared in-request portfolio broker** — `/overview`, `/portfolio/holdings`, `/risk`,
  `/portfolio/book-map` each independently load `holdings.json` and re-query overlapping tables.
- **Hot endpoints have no server-side TTL** — `/overview` and `/portfolio/holdings` recompute on every call;
  the "~60s cache" referenced in ops notes is actually the **frontend poll interval**, not a backend cache.
- ~20 other endpoints DO have in-process TTL caches (15s–6h), inconsistently applied per-handler rather than
  per-data-type.
- HomeHub alone fires overview + risk + performance + defense/posture + trade-ai/summary roughly every
  minute — three independent holdings/risk aggregation passes per minute from one page.
- Dual enrichment-cache paths exist for the same logical cache
  (`data/state/ticker_enrichment_cache.json` vs `data/portfolios/state/ticker_enrichment_cache.json`).

---

## 6. Frontend usage matrix (every page)

All 22 primary hubs + 11 redirect routes + the shell (MetricStrip, DetailDrawer) were traversed. Full
route→endpoint→data-type table lives in `config/data_registry.yaml` under `consumers.pages`. Headlines:

- **Support/resistance is two products**: closed-session levels via
  `GET /api/v2/ui/prefs/get?key=portfolio.reentry.resistance.v1` (Portfolio/Watch/Re-Entry cards) vs
  trade-plan `support_1`/`resistance_1` embedded on `GET /api/v2/broker-proposals`. Re-Entry additionally has
  a text-parse fallback from `watchlist/items`/`symbol-cards` — a broker-migration target.
- **Analyst data is four products**: `GET /api/v2/pro-analyst/pills` (Street/Hermes rollup),
  `GET /api/v2/analyst-detail` (Yahoo targets + rating distribution), `GET /api/v2/reports/analyst/*`
  (generated documents), and `symbol-cards.analyst` (cached snapshot) — with no shared authority ranking.
- 10 same-concept/different-endpoint risks recorded (analyst, S/R, regime/VIX, holdings universe, proposals,
  sector performance, rotation, watch decisions, stops, Hermes health).

---

## 7. Alert/notification usage matrix (every outbound alert)

~90+ alert senders across 8 families (position/stop, proposal/ATM, watch/re-entry, screener/scalp/social,
Hermes/research, portfolio/report, ops/health, infra/manual) plus non-Telegram surfaces (global alerts
banner, SIEM feed, `/api/v2/alerts`, `/api/v3/alerts/active`, email, WhatsApp/Slack). Full table in the
registry under `consumers.alerts`. Headlines:

- **17 alerts fetch or compute data ad hoc** instead of reading a shared store — priority migration list:
  `holdings_gain_guardian.py` (own Schwab/yfinance bars + local RSI/ATR/RVOL), `portfolio_live_monitor.py` /
  `portfolio_technical.py` (own Finviz scrape, not `market_quotes`), `watchlist_entry_planner.py` +
  `pullback_macd_screener.py` (own yfinance bars + local indicators), `ask_alerts.py` / `ipo_lockup_alert.py`
  (raw `yfinance` last price), `open_trade_monitor.py` (Alpaca fallback divergent from `market_quotes`).
- **10 UI-vs-alert source mismatches**: e.g. watch alerts fire on `market_quotes` while cards show Finviz
  strip prices; the global banner reads only `risk_management.json` while Telegram stop-health scans actual
  broker working orders; premarket/social "catalyst" alerts ignore `catalyst_verified` entirely; two
  different analyst-divergence alerts (`hermes_score_alerts.py`, `pro_analyst_monitor.py`) use different
  builders.
- **Aligned example to generalize**: `send_telegram_proposal_alert.py` already uses `get_best_quote` — same
  provider the proposal UI uses. This is the target pattern for every other alert.

---

## 8. Remediation — see the registry, not this document

This document is a point-in-time record. The live, maintained plan is:

- **[`config/data_registry.yaml`](../config/data_registry.yaml)** — every data type: authoritative producer,
  canonical store, TTL, authority rank, consumers (pages + alerts), and `deprecated_producers` (the
  ad-hoc paths above, tracked for migration).
- **`scripts/lib/data_broker/registry.py`** `check_coverage()` — flags when a deprecated producer is still
  referenced, or a new endpoint/page reads a registered data type without appearing in the matrix.
- **Data Management page** (`/v3/data`) — live registry browser, source health, and duplication report.
- **[`AGENTS.md`](../AGENTS.md)** — the standing rule for developers/agents: new data sources and data types
  register in `data_registry.yaml` and are served through the broker; no new ad-hoc scrape/yfinance paths.
