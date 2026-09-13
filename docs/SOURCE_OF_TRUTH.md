# Source of Truth — one declaration per domain

**Rendered from `config/data_source_authority.json` by `scripts/render_source_of_truth.py`. Do not edit by hand.**
Registry as of 2026-09-13 · authority READ_ONLY_ADVISORY · 17 domains · 22 providers.

One source of truth per domain. For five months Performance (10 Years) was stored as a 1-5 analyst rating because two files mapped Finviz columns by position and nothing declared which store was the analyst source. For eighteen days the site served one copy of the state tree while the producers wrote another, because nothing declared where each store is served from. This file is that declaration. The data broker reads it; scripts/check_data_source_authority.py enforces it; docs/SOURCE_OF_TRUTH.md is rendered from it.

## Rules

1. Every domain has exactly one writer. Anything else that writes the store is a defect.
2. Every domain is read through its broker projection. A hub handler that reads the store directly is a defect (the direct-read baseline can only shrink).
3. Every value carries as_of and age. A value older than stale_after_hours renders with its age, never as current.
4. A backup answers the SAME question from a different provider. Cross-domain substitution is not a backup.
5. A retired provider has zero call sites outside scripts/lib/retired_providers.py and the secret-hygiene scanners.
6. A provider that stops reporting decays to unknown in data_source_health; healthy means succeeded within its window.
7. Adding a source: add it here first (domain, store, writer, projection, backup, retired) and to AGENTS.md section 7B in the same PR. The gate fails on an undeclared provider host or SDK import.

## Where every served store lives

Root: `/home/johnclaw/trade-ai-releases/persistent-state/data`. Directories that must resolve here from **both** the release and the dev tree:
- `data/audit`
- `data/cio`
- `data/health`
- `data/paper_trading`
- `data/portfolios/state`
- `data/runtime`
- `data/state`

Both the release (CURRENT) and the dev tree the 344 cron producers run from must resolve each of these to this root. check_served_copy_split.py alerts when they do not.

## Domains of record

| Domain | Class | Store of record | Single writer | Cadence | Stale after | Read path | Primary | Backup (same question) | Retired | No coverage |
|---|---|---|---|---|---|---|---|---|---|---|
| **quote_price** | ingested | `market_quotes` | **none — dead feed** | */15 09:30-16:00 Mon-Fri | 0.25h | `market_quote` | alpaca | yfinance, schwab_stream | polygon, finnhub, fmp | `last_price_with_age_and_source` |
| **symbol_identity** | ingested | `symbol_profiles` | **none — dead feed** | 06:35 daily | 168h | `symbol_profile` | yfinance | finviz | fmp | `say_so` |
| **analyst_opinion** | ingested | `yahoo_analyst_targets_history` | `scripts/pro_analyst_fetch.py` | daily | 168h | `analyst_detail` | yahoo | yfinance_on_demand | fmp, finnhub | `say_so` |
| **catalyst_news** | ingested | `news_articles` | **none — dead feed** | 00:30 · 12:30 | 12h | `catalyst_record` | finviz | yahoo, brave, searxng | finnhub, newsapi, polygon, fmp | `say_so` |
| **technicals** | derived | `ticker_prices` · `portfolios/state/technical_snapshot.json` | **none — dead feed** | hourly | 26h | `indicator_snapshot` | alpaca | yfinance | — | `say_so` |
| **sector_momentum** | derived | `sector_rs_daily` · `runtime/sector_momentum_latest.json` | `scripts/sector_rs_daily.py` | 17:20 Mon-Fri | 26h | `sector_momentum` | internal:market_quotes | finviz_sector_view | — | `say_so` |
| **industry_momentum** | ingested | `runtime/industry_momentum_latest.json` | `scripts/finviz_industry_groups.py` | 12:30 · 16:18 | 26h | `sector_momentum` | finviz | — | — | `show_sector_with_industry_unavailable` |
| **market_regime** | derived | `market_regime_snapshots` | `scripts/market_regime_classifier.py` | 06:35 · 16:05 Mon-Fri (collector 06:30 feeds it) | 26h | `risk_snapshot` | yahoo | internal:trade_ai_scans | — | `carry_last_regime_with_date_never_neutral` |
| **earnings_date** | ingested | `symbol_profiles` | `scripts/earnings_enrich.py` | 06:35 daily | 168h | `symbol_profile` | yfinance | — | fmp | `UNKNOWN_blocks_options_gate` |
| **holdings_accounts** | ingested | `portfolios/state/holdings.json` | `scripts/portfolio_loader.py` | broker sync + */15 repricer | 24h | `portfolio_snapshot` | schwab | alpaca | — | `per_account_state_never_zero` |
| **options_iv** | live_external | `options_iv_history` | `scripts/lib/strategy_research/iv_history.py` | unscheduled | 4h | — | schwab | — | — | `call_out_at_read_time` |
| **research_thesis** | native | `hermes_research_intelligence` | **none — dead feed** | 8 scheduled lanes | 168h | `research_card` | internal | research_insights, governed_pull:brave>searxng | — | `say_so_queue_only_if_producer_exists` |
| **watch_directives** | native | `watch_directives` | **none — dead feed** | 3 scheduled | 48h | `watch_intelligence` | internal | — | — | `say_so` |
| **watch_discovery** | dead_feed | `watch_candidate_events` | **none — dead feed** | — | 48h | `watch_intelligence` | internal | — | — | `declared_gap_no_producer` |
| **web_search** | live_external | `runtime/search_budget.json` | `scripts/lib/brave_router.py` | on demand | — | — | brave | searxng, tavily | — | `declared_gap` |
| **private_company** | manual | `private_company_proxies` | operator | — | — | — | none | — | — | `refuse_up_front` |
| **dividends** | ingested | `ticker_dividend_data` | `scripts/sync_dividend_data.py` | 07:05 Mon-Fri | 168h | — | yfinance | — | fmp | `say_so` |

## Providers

| Provider | Class | Status | Supplies | Markers the gate recognises |
|---|---|---|---|---|
| **alpaca** | live_external | active | quotes, bars, paper_execution | `alpaca`, `data.alpaca.markets` |
| **schwab** | live_external | active | positions, option_chain, stream_quotes, instruments | `schwab_transport`, `schwab_api`, `api.schwabapi.com` |
| **yfinance** | live_external | active | profiles, quote_backup, prices, technicals, earnings, analyst_on_demand | `import yfinance`, `yfinance as yf` |
| **yahoo** | live_external | active | analyst_targets, vix, news_feed | `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `finance.yahoo.com` |
| **finviz** | live_external | active | screeners, enrichment, industry_groups, sector_perf, news | `finviz.com`, `elite.finviz.com` |
| **sec_edgar** | live_external | active | form4, filings | `sec.gov`, `efts.sec.gov` |
| **fred** | live_external | active_unwired_health | macro | `api.stlouisfed.org`, `FRED_API` |
| **alpha_vantage** | live_external | active_unwired_health | fundamentals | `alphavantage.co`, `ALPHA_VANTAGE` |
| **brave** | live_external | active_paid | web_search | `api.search.brave.com`, `brave_router`, `BRAVE_API` |
| **searxng** | self_hosted | active | web_search | `searxng`, `SEARXNG_URL` |
| **tavily** | live_external | configured_unused | web_search | `api.tavily.com`, `TAVILY_API` |
| **finnhub** | live_external | retired (2026-09-13) |  | `finnhub.io`, `FINNHUB_API` |
| **polygon** | live_external | retired (2026-09-13) |  | `api.polygon.io`, `polygon_api`, `POLYGON_API` |
| **fmp** | live_external | retired (2026-09-13) |  | `financialmodelingprep.com`, `FMP_API` |
| **newsapi** | live_external | retired (2026-09-13) |  | `newsapi.org`, `NEWSAPI_KEY`, `NEWSAPI_API` |
| **ollama** | local_model | active | inference | `11434`, `ollama` |
| **deepseek** | external_model | active_metered | inference | `api.deepseek.com`, `DEEPSEEK_API` |
| **stocktwits** | live_external | active | sentiment | `stocktwits.com` |
| **reddit** | live_external | active | sentiment | `reddit.com`, `oauth.reddit.com` |
| **google_news** | live_external | active | news_feed | `news.google.com` |
| **moomoo** | live_external | service_down | positions | `moomoo`, `futu`, `OpenD` |
| **fidelity** | manual | no_api_manual | positions | `fidelity`, `snaptrade` |

## How to add or retire a source

See `AGENTS.md` §7B. Short form: registry first, projection second, markers third, table row in the
same PR. `scripts/check_data_source_authority.py` fails on an undeclared host, a retired call site,
a writer count that rose, or a hub direct read that rose.

## Enforcement

| Gate | Fails when | Where |
|---|---|---|
| `check_data_source_authority.py` | retired call site · undeclared provider · writer count rose · direct read rose · writer/projection missing | `ai_local_acceptance`, PR workflow |
| `check_served_copy_split.py` | any linked dir resolves to two directories from dev vs served · anything references the reconcile archive | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
| `data_plausibility_monitor.py` | a declared column leaves its declared scale | 06:20 timer, `[DATA_INTEGRITY]` interrupt |
| `check_expected_services.py` | a declared unit or flag is off | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
