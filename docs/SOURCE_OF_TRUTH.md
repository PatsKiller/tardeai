# Source of Truth — one declaration per domain

**Rendered from `config/data_source_authority.json` by `scripts/render_source_of_truth.py`. Do not edit by hand.**
Registry as of 2026-10-06T11:00:00-04:00 · schema `DataSourceAuthority@v2` · authority READ_ONLY_ADVISORY · 56 domains · 22 providers.

One source of truth per domain. For five months Performance (10 Years) was stored as a 1-5 analyst rating because two files mapped Finviz columns by position and nothing declared which store was the analyst source. For eighteen days the site served one copy of the state tree while the producers wrote another, because nothing declared where each store is served from. This file is that declaration. The data broker reads it; scripts/check_data_source_authority.py enforces it; docs/SOURCE_OF_TRUTH.md is rendered from it.

## Rules

1. Every domain has exactly one writer. Anything else that writes the store is a defect.
2. Every domain is read through its broker projection. A hub handler that reads the store directly is a defect (the direct-read baseline can only shrink).
3. Every value carries as_of and age. A value older than stale_after_hours renders with its age, never as current.
4. A backup answers the SAME question from a different provider. Cross-domain substitution is not a backup.
5. A retired provider has zero call sites outside scripts/lib/retired_providers.py and the secret-hygiene scanners.
6. A provider that stops reporting decays to unknown in data_source_health; healthy means succeeded within its window.
7. Adding a source: add it here first (domain, store, writer, projection, backup, retired, approval) and re-render AGENTS.md §7A and docs/SOURCE_OF_TRUTH.md with scripts/render_source_of_truth.py in the same PR. The gate fails on an undeclared provider host or SDK import.
8. Every domain declares on_gap: the ordered, budgeted vectors the gap resolver may run when the store is stale or empty. Free before metered before paid; operator_ask last; retired providers never.
9. Adding, replacing or retiring a data source — or a writer of an authoritative store — is an operator-only decision (AGENTS.md §17). An agent proposes the registry row in a PR; the operator grants it; the grant is recorded in that row's `approval` {approved_by, approved_on, reference, scope} (retired rows: retired_by, retired_on, reference). Only then may a call site exist. A provider or domain without a complete approval fails check_data_source_authority.py with UNAPPROVED_SOURCE.

## Ownership and the grant

The registry names, for every authoritative store, **who owns it** (the single writer module, or the
operator for a manual store), **how it is written** (cadence, writer, projection it is read through)
and **what stands in for it** (the `backup` chain — same question, different provider — and the
declared `no_coverage` behaviour when the chain is exhausted). Each row also carries the
**operator's grant** in `approval`: who approved it, when, where that approval is recorded, and the
one-line scope of what the source may supply. A retired row records who retired it and when.

**Adding, replacing or retiring a data source — or a writer of an authoritative store — is an
operator-only decision** (`AGENTS.md` §17). An agent proposes the registry row in a PR; the operator
grants it; the grant is written into `approval`; only then may a call site exist. A row without a
complete approval fails `check_data_source_authority.py` with `UNAPPROVED_SOURCE`, and a host the
registry does not know fails with `UNDECLARED_PROVIDER` whose message says what to do: propose a
registry row with an approval record, do not add the host.

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

| Domain | Class | Store of record | Single writer (how it is written) | Cadence | Stale after | Read path | Primary | Backup (same question) | Retired | No coverage | Approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **quote_price** | ingested | `market_quotes` | `scripts/lib/writers/market_quotes_writer.py` | */15 09:30-16:00 Mon-Fri | 0.25h | `market_quote` | alpaca | yfinance, schwab_stream | polygon, finnhub, fmp | `last_price_with_age_and_source` | operator 2026-09-13 |
| **symbol_identity** | ingested | `symbol_profiles` | `scripts/lib/writers/symbol_profiles_writer.py` | 06:35 daily | 168h | `symbol_profile` | yfinance | finviz | fmp | `say_so` | operator 2026-09-13 |
| **analyst_opinion** | ingested | `yahoo_analyst_targets_history` | `scripts/pro_analyst_fetch.py` | daily | 168h | `analyst_detail` | yahoo | yfinance_on_demand | fmp, finnhub | `say_so` | operator 2026-09-13 |
| **catalyst_news** | ingested | `news_articles` | `scripts/lib/writers/news_articles_writer.py` | 00:30 · 12:30 | 18h | `catalyst_record` | finviz | yahoo, brave, searxng | finnhub, newsapi, polygon, fmp | `say_so` | operator 2026-09-13 |
| **technicals** | derived | `ticker_prices` · `portfolios/state/technical_snapshot.json` | `scripts/lib/writers/ticker_prices_writer.py` | hourly | 26h | `indicator_snapshot` | alpaca | yfinance | — | `say_so` | operator 2026-09-13 |
| **sector_momentum** | derived | `sector_rs_daily` · `runtime/sector_momentum_latest.json` | `scripts/sector_rs_daily.py` | 17:20 Mon-Fri | 26h | `sector_momentum` | internal:market_quotes | finviz_sector_view | — | `say_so` | operator 2026-09-13 |
| **industry_momentum** | ingested | `runtime/industry_momentum_latest.json` | `scripts/finviz_industry_groups.py` | 12:30 · 16:18 | 26h | `sector_momentum` | finviz | — | — | `show_sector_with_industry_unavailable` | operator 2026-09-13 |
| **market_regime** | derived | `market_regime_snapshots` | `scripts/market_regime_classifier.py` | 06:35 · 16:05 Mon-Fri (collector 06:30 feeds it) | 26h | `market_regime` | yahoo | internal:trade_ai_scans | — | `carry_last_regime_with_date_never_neutral` | operator 2026-09-13 |
| **earnings_date** | ingested | `symbol_profiles` | `scripts/earnings_enrich.py` | 06:35 daily | 168h | `symbol_profile` | yfinance | — | fmp | `UNKNOWN_blocks_options_gate` | operator 2026-09-13 |
| **holdings_accounts** | ingested | `portfolios/state/holdings.json` | `scripts/portfolio_loader.py` | broker sync + */15 repricer | 24h | `portfolio_snapshot` | schwab | alpaca | — | `per_account_state_never_zero` | operator 2026-09-13 |
| **positions_store** | ingested | `positions_current` | `scripts/positions_sync.py` | */15 09:30-16:00 Mon-Fri once installed (cron after the deploy grant); heartbeat = positions_sync_runs | 0.5h | — | schwab | — | — | `per_account_state_never_zero` | operator 2026-10-06 |
| **options_iv** | live_external | `options_iv_history` | `scripts/lib/strategy_research/iv_history.py` | unscheduled | 4h | `option_chain` | schwab | — | — | `call_out_at_read_time` | operator 2026-09-13 |
| **research_thesis** | native | `hermes_research_intelligence` | `scripts/lib/writers/hermes_research_writer.py` | 8 scheduled lanes | 168h | `research_card` | internal | research_insights, governed_pull:brave>searxng | — | `say_so_queue_only_if_producer_exists` | operator 2026-09-13 |
| **watch_directives** | native | `watch_directives` | `scripts/lib/writers/watch_directives_writer.py` | 3 scheduled | 48h | `watch_intelligence` | internal | — | — | `say_so` | operator 2026-09-13 |
| **watch_discovery** | dead_feed | `watch_candidate_events` | **none — dead feed** | — | 48h | `watch_discovery` | internal | — | — | `declared_gap_no_producer` | operator 2026-09-13 |
| **web_search** | live_external | `runtime/search_budget.json` | `scripts/lib/brave_router.py` | on demand | 72h | — | brave | searxng, tavily | — | `declared_gap` | operator 2026-09-13 |
| **private_company** | manual | `private_company_proxies` | operator (manual entry) | — | — | — | none | — | — | `refuse_up_front` | operator 2026-09-13 |
| **dividends** | ingested | `ticker_dividend_data` | `scripts/sync_dividend_data.py` | 07:05 Mon-Fri | 168h | — | yfinance | — | fmp | `say_so` | operator 2026-09-13 |
| **macro** | ingested | `fred_economic_series` | UNCONSOLIDATED → `scripts/external_market_data_ingest.py` (2 writers today; ceiling may only fall) | 06:15 daily (fred_data_ingest.py --ingest) | 48h | — | fred | — | — | `say_so` | operator 2026-09-13 |
| **fundamentals** | ingested | `fundamental_data` | `scripts/external_market_data_ingest.py` | 08:00 Mon (--fundamentals) | 192h | — | alpha_vantage | yfinance | fmp | `say_so` | operator 2026-09-13 |
| **agent_opinion** | native | `watchlist_agent_results` | `scripts/process_watchlist_agent_jobs.py` | on watch events | 48h | `agent_opinion` | internal | — | — | `say_so` | operator 2026-09-13 |
| **agent_debate** | dead_feed | `agent_debate_log` | **none — dead feed** | — | 168h | `agent_opinion` | internal | — | — | `declared_gap_no_producer` | operator 2026-09-13 |
| **ai_reports** | dead_feed | `ai_reports` | **none — dead feed** | — | 168h | `desk_feeds` | internal | — | — | `declared_gap_no_producer` | operator 2026-09-13 |
| **redeploy_analytics** | dead_feed | `portfolios/state/redeploy_analytics_cache.json` | `scripts/api_v2.py` | on demand (30-min TTL cache) | 24h | `desk_feeds` | internal | — | — | `declared_gap_no_producer` | operator 2026-09-13 |
| **inverse_stoplights** | derived | `runtime/inverse_stoplights_latest.json` | `scripts/defense_inverse_stoplights.py` | 10:15 · 17:55 Mon-Fri | 26h | — | internal | — | — | `say_so` | operator 2026-09-13 |
| **data_gaps** | native | `data_gap_registry` | `scripts/lib/writers/data_gap_registry_writer.py` | crontab: data_gap_resolver.py hourly 10:00-16:00 and --pre-overnight 18:00 on weekdays, --weekly-audit Sunday 08:00 (the desk reads these times from the crontab itself) | 168h | — | internal | — | — | `say_so` | operator 2026-09-13 |
| **operator_conversation** | native | `operator_conversation_turns` | `scripts/lib/inbound_identity_tagger.py` | event-driven: every operator message and every agent reply on Telegram | 720h | — | internal | — | — | `say_so` | operator 2026-09-13 |
| **intelligence_memory_contexts** | derived | `cio/memory_contexts.jsonl` | `scripts/lib/intelligence_client.py` | per context open/commit | 24h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **intelligence_retrieval_receipts** | derived | `cio/retrieval_receipts.jsonl` | `scripts/lib/intelligence_client.py` | per generation | 24h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **supervisor_heartbeats** | derived | `intelligence.heartbeat` · `runtime/heartbeats/<lane_id>.json` | `scripts/lib/supervisor_heartbeat.py` | per lane run | 48h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **approval_packages** | derived | `intelligence.approval_package` · `governance/approval_packages.jsonl` | `scripts/lib/approval_package.py` | per package event | 720h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **platform_conformance** | derived | `governance/platform_conformance_latest.json` | `scripts/report_platform_conformance.py` | daily | 36h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **intelligence_gir_projection** | derived | `intelligence.gir_entity` · `runtime/gir_projection_dryrun.json` | `scripts/gir_projector.py` | batch (nightly) then incremental | 36h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **supervisor_breaches** | derived | `intelligence.breach` · `runtime/supervisor_breaches.jsonl` | `scripts/supervisor_breach_detector.py` | every 2 min once installed | 1h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **research_write_path_receipts** | derived | `cio/research_write_path_receipts.jsonl` | `scripts/lib/research_write_path.py` | per producer result | 24h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **edge_fanout_work_items** | derived | `cio/edge_fanout_work_items.jsonl` | `scripts/edge_fanout_consumer.py` | every 5 min (systemd timer, after the service grant) | 1h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **intelligence_research_index** | derived | `intelligence.research_index` | `scripts/lib/research_index_writer.py` | per accepted research delta | 168h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **sec_filing_events** | ingested | `cio/sec_filing_events.jsonl` | `scripts/sec_filings_feed.py` | 4× on market days (cron, after the cron grant) | 30h | — | sec_edgar | — | — | `say_so` | operator 2026-09-27 |
| **agent_checkpoints** | derived | `cio/agent_checkpoints/<agent_id>.jsonl` | `scripts/lib/cognitive_checkpoint.py` | per non-monitor commit | 48h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **lesson_promotions** | derived | `cio/lesson_promotions.jsonl` | `scripts/lib/lesson_promotion.py` | weekly batch (operator CLI) | 336h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **contradiction_verdicts** | derived | `cio/contradiction_verdicts.jsonl` | `scripts/contradiction_adjudicator.py` | daily (systemd timer, after the service grant) | 48h | — | deepseek | — | — | `say_so` | operator 2026-09-27 |
| **agent_registry** | manual | `config/agent_registry.json` | `scripts/lib/agent_registry.py` | per PR | 8760h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **model_chooser_receipts** | derived | `runtime/model_chooser_receipts.jsonl` | `scripts/lib/model_chooser.py` | per disagreeing LLM call | 48h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **supervisor_ladder_receipts** | derived | `runtime/supervisor_ladder_receipts.jsonl` | `scripts/supervisor_breach_detector.py` | per detector run (3 min) | 1h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **maturity_scores** | derived | `governance/maturity_scores.jsonl` | `scripts/maturity_remeasure.py` | weekly (cron, after the cron grant) | 336h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **conformance_gate_receipts** | derived | `governance/conformance_gate_receipts.jsonl` | `scripts/conformance_gate.py` | per promote | 720h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **supervisor_recoveries** | derived | `runtime/supervisor_recoveries.jsonl` | `scripts/supervisor_breach_detector.py` | per detector run | 1h | — | native | — | — | `say_so` | operator 2026-09-27 |
| **capital_plan_decisions** | derived | `cio/cio_capital_plan_decisions.jsonl` | `scripts/lib/cio_capital_plan_decision_store.py` | on capital-plan build (GET /api/v2/cio/capital-plan) | 168h | — | native | — | — | `say_so` | operator 2026-10-03 |
| **cio_operator_artifacts** | derived | `cio/cio_operator_artifacts.jsonl` | `scripts/lib/cio_operator_artifacts.py` | event-driven (written when a hooked producer composes or sends an output) | 168h | — | native | — | — | `say_so` | operator 2026-10-03 |
| **counterfactual_ledger** | derived | `cio/counterfactual_ledger.jsonl` | `scripts/lib/counterfactual_ledger.py` | daily (scripts/build_counterfactual_ledger.py --apply) | 48h | — | native | — | — | `say_so` | operator 2026-10-03 |
| **active_trader_microstructure** | ingested | `data/active_trader/micro/<day>/<SYMBOL>.jsonl + <SYMBOL>.bars.json + micro/live_symbols.json` | `scripts/active_trader/microstructure_recorder.py` | every 5 s 06:00-12:00 ET Mon-Fri (recorder windows) | 0.00417h | `active_trader_microstructure` | moomoo | — | — | `say_so` | operator 2026-10-05 |
| **opportunity_assessment** | derived | `data/cio/cio_opportunity_projection.json` | `scripts/cio_opportunity_curator.py` | */30 09:00-16:00 Mon-Fri + 17:50 once the cron is granted | 26h | `opportunity` | derived | — | — | `say_so` | operator 2026-10-08 |
| **finviz_enrichment** | ingested | `state/ticker_enrichment_cache.json` | `scripts/finviz_enrichment.py` | 0 13 * * 1-5 (cron L142) + on-demand owner batches (watch-directive servicer prefetch, L442) | 6h | `finviz_enrichment_snapshot` | finviz | — | — | `say_so` | operator 2026-10-10 |
| **scalp_list** | ingested | `trade_ai/scalp_universe_latest.json` | `scripts/run_trade_ai_scalp_live.py` | */5 09:30-16:00 Mon-Fri (cron L1050, §23.3 lane; unchanged). Premarket 06:00-09:30 hot tier (operator decision §D.4, PR #1671) is code-complete with its knob OFF by default. | 0.25h | `scalp_list` | finviz | — | — | `say_so` | operator 2026-10-10 |
| **social_posts** | ingested | `social_posts` | UNCONSOLIDATED → `scripts/social_ingest.py` (3 writers today; ceiling may only fall) | 06:00 Mon-Fri --source all (cron L243) + 08:30/10:30/13:30 --source stocktwits --discover (L244) | 26h | `social_feed` | stocktwits | — | — | `say_so` | operator 2026-10-10 |
| **yfinance_info_snapshot** | ingested | `yfinance_info_snapshot` | `scripts/lib/writers/yfinance_info_snapshot_writer.py` | unscheduled — no producer until the yfinance-reference-ingest owner lane is decided (§D.12); migration migrations/2026_10_10_yfinance_info_snapshot.sql not yet applied | 48h | `yfinance_info` | yfinance | — | fmp | `say_so` | operator 2026-10-10 |

## Writer ceilings — stores not yet consolidated to one writer

`config/data_source_authority_baseline.json` records how many files write each store today. The
number is a **ceiling, not a target**: `WRITER_COUNT_ROSE` fails the build when it rises, and it is
regenerated only after a deliberate reduction (`--write-baseline`). The consolidation target is the
module every other writer must call.

| Domain | Store | Writers today (ceiling) | Consolidation target | Hub direct reads (ceiling) |
|---|---|---|---|---|
| **macro** | `fred_economic_series` | 2 | `scripts/external_market_data_ingest.py` | — |
| **social_posts** | `social_posts` | 3 | `scripts/social_ingest.py` | 7 |

## Providers

| Provider | Class | Status | Supplies | Markers the gate recognises | Approval |
|---|---|---|---|---|---|
| **alpaca** | live_external | active | quotes, bars, paper_execution | `alpaca`, `data.alpaca.markets` | operator 2026-09-13 |
| **schwab** | live_external | active | positions, option_chain, stream_quotes, instruments | `schwab_transport`, `schwab_api`, `api.schwabapi.com` | operator 2026-09-13 |
| **yfinance** | live_external | active | profiles, quote_backup, prices, technicals, earnings, analyst_on_demand | `import yfinance`, `yfinance as yf` | operator 2026-09-13 |
| **yahoo** | live_external | active | analyst_targets, vix, news_feed | `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `finance.yahoo.com` | operator 2026-09-13 |
| **finviz** | live_external | active | screeners, enrichment, industry_groups, sector_perf, news | `finviz.com`, `elite.finviz.com` | operator 2026-09-13 |
| **sec_edgar** | live_external | active | form4, filings | `sec.gov`, `efts.sec.gov` | operator 2026-09-13 |
| **fred** | live_external | active | macro | `api.stlouisfed.org`, `FRED_API` | operator 2026-09-13 |
| **alpha_vantage** | live_external | active | fundamentals | `alphavantage.co`, `ALPHA_VANTAGE` | operator 2026-09-13 |
| **brave** | live_external | active_paid | web_search | `api.search.brave.com`, `brave_router`, `BRAVE_API` | operator 2026-09-13 |
| **searxng** | self_hosted | active | web_search | `searxng`, `SEARXNG_URL` | operator 2026-09-13 |
| **tavily** | live_external | configured_unused | web_search | `api.tavily.com`, `TAVILY_API` | operator 2026-09-13 |
| **finnhub** | live_external | retired (2026-09-13) |  | `finnhub.io`, `FINNHUB_API` | retired by operator 2026-09-13 |
| **polygon** | live_external | retired (2026-09-13) |  | `api.polygon.io`, `polygon_api`, `POLYGON_API` | retired by operator 2026-09-13 |
| **fmp** | live_external | retired (2026-09-13) |  | `financialmodelingprep.com`, `FMP_API` | retired by operator 2026-09-13 |
| **newsapi** | live_external | retired (2026-09-13) |  | `newsapi.org`, `NEWSAPI_KEY`, `NEWSAPI_API` | retired by operator 2026-09-13 |
| **ollama** | local_model | active | inference | `11434`, `ollama` | operator 2026-09-13 |
| **deepseek** | external_model | active_metered | inference | `api.deepseek.com`, `DEEPSEEK_API` | operator 2026-09-13 |
| **stocktwits** | live_external | active | sentiment | `stocktwits.com` | operator 2026-09-13 |
| **reddit** | live_external | active | sentiment | `reddit.com`, `oauth.reddit.com` | operator 2026-09-13 |
| **google_news** | live_external | active | news_feed | `news.google.com` | operator 2026-09-13 |
| **moomoo** | live_external | service_down | positions, order_book, tape, intraday_bars | `moomoo`, `futu`, `OpenD` | operator 2026-09-13 |
| **fidelity** | manual | no_api_manual | positions | `fidelity`, `snaptrade` | operator 2026-09-13 |

## Approval records

Every provider and domain row carries `approval`. The distinct references, and the rows they cover:

- **One Source of Truth campaign — operator approved Phases 1-7 on 2026-09-13 (PRs #992 #993 #994); registry seeded from the measured sweep** — 42 rows: provider `alpaca`, provider `schwab`, provider `yfinance`, provider `yahoo`, provider `finviz`, provider `sec_edgar`, provider `fred`, provider `alpha_vantage`, provider `brave`, provider `searxng`, provider `tavily`, provider `ollama`, provider `deepseek`, provider `stocktwits`, provider `reddit`, provider `google_news`, provider `moomoo`, provider `fidelity`, domain `quote_price`, domain `symbol_identity`, domain `analyst_opinion`, domain `catalyst_news`, domain `technicals`, domain `sector_momentum`, domain `industry_momentum`, domain `market_regime`, domain `earnings_date`, domain `holdings_accounts`, domain `options_iv`, domain `research_thesis`, domain `watch_directives`, domain `watch_discovery`, domain `web_search`, domain `private_company`, domain `dividends`, domain `macro`, domain `fundamentals`, domain `agent_opinion`, domain `agent_debate`, domain `ai_reports`, domain `redeploy_analytics`, domain `inverse_stoplights`
- **One Source of Truth campaign — operator approved Phases 1-7 on 2026-09-13 (PRs #992 #993 #994); registry seeded from the measured sweep; retirement = Phase 2, archive/ARCHIVE_MANIFEST.json (polygon_source.py row) and zero call sites proven by RETIRED_CALL_SITE** — 4 rows: provider `finnhub`, provider `polygon`, provider `fmp`, provider `newsapi`
- **Positions Source of Truth plan phase 1 — operator 2026-10-06 'yes start phase 1 and fix all of it' (session https://claude.ai/code/session_018utgrKN5h7J95riLqPm5te); plan PR #1449, docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md** — 1 rows: domain `positions_store`
- **Operator approved reconnecting the operator desk to the data gap queue in session on 2026-09-13 ("yess reconect approved"); shipped in PR #998; the desk becomes a caller of the store's one write module** — 1 rows: domain `data_gaps`
- **Operator asked in session on 2026-09-13 to connect chat memory recall per subject GUID ("yes connect chat memory recall per guid"); shipped in PR #1001 (branch feat/chat-memory-recall)** — 1 rows: domain `operator_conversation`
- **ApprovalPackage pkg-20260927-cogx-w1-d9e1 (typed reply 'APPROVE … all', Claude Code 2026-09-27 ~18:50 ET); package docs/architecture/cognitive_transformation_20260927/ on PR #1304** — 7 rows: domain `intelligence_memory_contexts`, domain `intelligence_retrieval_receipts`, domain `supervisor_heartbeats`, domain `approval_packages`, domain `platform_conformance`, domain `intelligence_gir_projection`, domain `supervisor_breaches`
- **ApprovalPackage pkg-20260928-wave-2-enforcement-35c4 (typed reply 'APPROVE … all', Claude Code 2026-09-27 ~21:00 ET); PR #1319; decision record docs/ops/COGX_WAVE2_APPROVAL_PACKAGE_2026-09-28.md item 2** — 1 rows: domain `research_write_path_receipts`
- **ApprovalPackage pkg-20260928-wave-2-enforcement-35c4 (typed reply 'APPROVE … all', Claude Code 2026-09-27 ~21:00 ET); PR #1319; decision record docs/ops/COGX_WAVE2_APPROVAL_PACKAGE_2026-09-28.md items 3-4** — 1 rows: domain `edge_fanout_work_items`
- **ApprovalPackage pkg-20260928-wave-2-enforcement-35c4 (typed reply 'APPROVE … all', Claude Code 2026-09-27 ~21:00 ET); PR #1319; decision record docs/ops/COGX_WAVE2_APPROVAL_PACKAGE_2026-09-28.md item 8** — 1 rows: domain `intelligence_research_index`
- **ApprovalPackage pkg-20260928-wave-2-enforcement-35c4 (typed reply 'APPROVE … all', Claude Code 2026-09-27 ~21:00 ET); PR #1321; decision record docs/ops/COGX_WAVE2_APPROVAL_PACKAGE_2026-09-28.md item 5** — 1 rows: domain `sec_filing_events`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326; decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 3 item O-W3-1** — 1 rows: domain `agent_checkpoints`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326; decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 3 item O-W3-2** — 1 rows: domain `lesson_promotions`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326; decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 3 item O-W3-3** — 1 rows: domain `contradiction_verdicts`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326 (Wave 3 base; this row lands with the stacked Wave 4 PR); decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 4 item O-W4-2** — 1 rows: domain `agent_registry`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326 (Wave 3 base; this row lands with the stacked Wave 4 PR); decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 4 item O-W4-3** — 1 rows: domain `model_chooser_receipts`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326 (Wave 3 base; this row lands with the stacked Wave 4 PR); decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 4 item O-W4-5** — 1 rows: domain `supervisor_ladder_receipts`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326 (Wave 3 base; this row lands with the stacked Wave 5 PR); decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 5 item O-W5-4** — 1 rows: domain `maturity_scores`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326 (Wave 3 base; this row lands with the stacked Wave 5 PR); decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 5 item O-W5-2** — 1 rows: domain `conformance_gate_receipts`
- **ApprovalPackage pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 (SUBMITTED 2026-09-27 22:53 ET, Telegram 54509/54511; operator 'do rest of waves now'); PR #1326 (Wave 3 base; this row lands with the stacked Wave 5 PR); decision record docs/ops/COGX_WAVE1_STATUS_2026-09-27.md § Wave 5 item O-W5-3** — 1 rows: domain `supervisor_recoveries`
- **Decision Lineage Join Plan Phase 3 — operator approved all phases 2026-10-03 (artifact https://claude.ai/artifact/C89ctZQYdYWg8onPMiCjyD, session https://claude.ai/code/session_016HFMrnsdyVGo4QnLAijLVC); PR #1402** — 1 rows: domain `capital_plan_decisions`
- **CIO completeness gap closure - operator approved ONE append-only store for operator-relevant CIO outputs 2026-10-03 (session https://claude.ai/code/session_016HFMrnsdyVGo4QnLAijLVC); PR #1419** — 1 rows: domain `cio_operator_artifacts`
- **Policy Review P3 counterfactual ledger for blocked ideas — operator approved 2026-10-03 (artifact https://claude.ai/artifact/A9hC1prwHkkt3WbvTDBxiv, session https://claude.ai/code/session_016HFMrnsdyVGo4QnLAijLVC); PR #1425** — 1 rows: domain `counterfactual_ledger`
- **Operator HARD RULE 2026-10-05 (Command Center is the source of truth; refreshed by the data broker and spawned out) + Active Trader microstructure recorder approved 2026-10-05 ('yes do 1-4', PR #1444); alert sync PR wt/at-alert-sync-20261005** — 1 rows: domain `active_trader_microstructure`
- **Investment Command Center plan approved 2026-10-08 (/plan; session https://claude.ai/code/session_018utgrKN5h7J95riLqPm5te); PR #1516, docs/ops/INVESTMENT_COMMAND_CENTER_2026-10-08.md** — 1 rows: domain `opportunity_assessment`
- **CONSOLIDATION_PLAN.md §D decisions (2),(3),(5),(6),(7),(13),(14) — operator approval 2026-10-10 ~17:45 ET (session https://claude.ai/code/session_018QBWwttnCspwJYNhNdqd14; evidence API_OVERLAP_CONSOLIDATION.md); PR #1678 (branch n8nmat/broker-domains-q1) — decision (2) register finviz_enrichment; (3) store of record = data/state copy** — 1 rows: domain `finviz_enrichment`
- **CONSOLIDATION_PLAN.md §D decisions (2),(3),(5),(6),(7),(13),(14) — operator approval 2026-10-10 ~17:45 ET (session https://claude.ai/code/session_018QBWwttnCspwJYNhNdqd14; evidence API_OVERLAP_CONSOLIDATION.md); PR #1678 (branch n8nmat/broker-domains-q1) — decision (5) register scalp_list** — 1 rows: domain `scalp_list`
- **CONSOLIDATION_PLAN.md §D decisions (2),(3),(5),(6),(7),(13),(14) — operator approval 2026-10-10 ~17:45 ET (session https://claude.ai/code/session_018QBWwttnCspwJYNhNdqd14; evidence API_OVERLAP_CONSOLIDATION.md); PR #1678 (branch n8nmat/broker-domains-q1) — decision (5) register social_posts** — 1 rows: domain `social_posts`
- **CONSOLIDATION_PLAN.md §D decisions (2),(3),(5),(6),(7),(13),(14) — operator approval 2026-10-10 ~17:45 ET (session https://claude.ai/code/session_018QBWwttnCspwJYNhNdqd14; evidence API_OVERLAP_CONSOLIDATION.md); PR #1678 (branch n8nmat/broker-domains-q1) — decision (13) create store yfinance_info_snapshot** — 1 rows: domain `yfinance_info_snapshot`

## Monitors

The campaign's monitors are declared three times so that a monitor that is OFF is itself a finding:
as a systemd unit in `config/systemd/user/`, as a lane in `config/lane_registry.json` with a receipt
`output_signal`, and as a required unit in `config/expected_services.json`. Installing a timer is
operator-only (`AGENTS.md` §9.3, §17); this table asserts the declarations, not the host state.

| Monitor lane | Timer unit | Schedule | Receipt (written every run) | Declared in expected_services | Installed? |
|---|---|---|---|---|---|
| `served-copy-split-audit` | `tradeai-served-copy-split.timer` | `*-*-* *:42:00` | `data/runtime/served_copy_split_last_run.json` | yes | measured by `check_expected_services.py` on the host — not asserted here |
| `expected-services-audit` | `tradeai-expected-services.timer` | `*-*-* *:12:00` | `data/runtime/expected_services_last_run.json` | yes | measured by `check_expected_services.py` on the host — not asserted here |
| `data-plausibility-audit` | `tradeai-data-plausibility.timer` | `*-*-* 06:20:00` | `data/runtime/data_plausibility_last_run.json` | yes | measured by `check_expected_services.py` on the host — not asserted here |
| `data-source-health-audit` | `tradeai-data-source-health.timer` | `*-*-* *:27:00` | `data/runtime/data_source_health_last_run.json` | yes | measured by `check_expected_services.py` on the host — not asserted here |
| `gap-resolution-audit` | `tradeai-gap-resolution.timer` | `*-*-* *:07,37:00` | `data/runtime/gap_resolution_last_run.json` | yes | measured by `check_expected_services.py` on the host — not asserted here |

## How to add or retire a source

See `AGENTS.md` §7A. Short form: **operator grant first** (recorded in the row's `approval`), registry
row second, projection third, markers fourth, then re-render this document and the §7A table with
`scripts/render_source_of_truth.py` in the same PR. `scripts/check_data_source_authority.py` fails on
an ungranted row, an undeclared host, a retired call site, a writer count that rose, or a hub direct
read that rose.

## Enforcement

| Gate | Fails when | Where |
|---|---|---|
| `check_data_source_authority.py` | ungranted provider/domain (`UNAPPROVED_SOURCE`) · retired call site · undeclared provider · writer count rose · direct read rose · writer/projection missing | `ai_local_acceptance`, PR workflow |
| `render_source_of_truth.py --check` | this document or the `AGENTS.md` §7A table differs from the registry | `ai_local_acceptance`, PR workflow |
| `check_served_copy_split.py` | any linked dir resolves to two directories from dev vs served · anything references the reconcile archive | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
| `check_data_source_health.py` | a source with a scheduled caller is not *effectively* healthy (decayed to unknown, or error) | hourly timer, `[PLATFORM_AVAILABILITY]` on change |
| `check_gap_resolution.py` | a gap open >2h with no attempt · a vector failing ≥3× today · a retired provider ran (`RETIRED_RAN`, must be 0) | 30-min timer, `[DATA_INTEGRITY]` interrupt |
| `data_plausibility_monitor.py` | a declared column leaves its declared scale | 06:20 timer, `[DATA_INTEGRITY]` interrupt |
| `check_expected_services.py` | a declared unit or flag is off | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
