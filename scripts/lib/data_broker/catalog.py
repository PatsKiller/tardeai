"""Data Broker catalog — advertise every read projection (including Watch Intelligence).

GET /api/v3/data-broker
GET /api/v3/data-broker/catalog

This is the index for operators and other apps. Watch Intelligence is one projection
in the same package as market_quote, symbol_profile, reentry_decision_desk, etc.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Existing + new projections. Keep paths stable; UI and other apps discover from here.
PROJECTIONS: list[dict[str, Any]] = [
    {
        "id": "active_trader_microstructure",
        "module": "lib.data_broker.microstructure",
        "entrypoints": ["latest", "book", "tape", "quote", "bars", "live_symbols"],
        "http": [],
        "domain": "active_trader_microstructure",
        "description": "Live book / prints / last / 1-min bars for the scalp names, as published by the "
                       "microstructure recorder (single writer); 15 s freshness contract, fails closed",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "market_quote",
        "module": "lib.data_broker.market_quote",
        "entrypoints": ["get_price_batch"],
        "http": [],
        "domain": "quotes",
        "description": "Batch live prices: newest market_quotes row per symbol (latest_quote projection) within "
                       "max_age_hours; for misses, quote-only get_best_quote (stored first, first fresh provider, "
                       "<=10 symbols per batch, 5 s each; QUOTE_ONLY_MODE=0 turns the fallback off)",
        "read_only": True,
        "provider_calls": "none_on_cache_hit",
    },
    {
        "id": "latest_quote",
        "module": "lib.data_broker.latest_quote",
        "entrypoints": ["get_latest_quotes", "get_latest_quote"],
        "http": [],
        "domain": "quotes",
        "authority_domain": "quote_price",
        "description": "Newest stored quote per symbol from market_quotes (one index probe per symbol, not a "
                       "DISTINCT ON scan) with as_of/age_seconds/stale; stale rows returned labelled "
                       "(no_coverage last_price_with_age_and_source); never fetches",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["market_quote.get_price_batch", "market_quote_provider.get_best_quote (quote-only mode)"],
    },
    {
        "id": "social_feed",
        "module": "lib.data_broker.social_feed",
        "entrypoints": ["get_social_posts"],
        "http": [],
        "domain": "social_posts",
        "authority_domain": "social_posts",
        "description": "Recent StockTwits posts per symbol from social_posts (sentiment label/score, bounded per "
                       "symbol) with as_of = newest ingested_at; never fetches",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
    },
    {
        "id": "yfinance_info",
        "module": "lib.data_broker.yfinance_info",
        "entrypoints": ["get_info_batch"],
        "http": [],
        "domain": "yfinance_info_snapshot",
        "authority_domain": "yfinance_info_snapshot",
        "description": "Raw yfinance .info per symbol from yfinance_info_snapshot (status ok/no_profile/error is "
                       "the negative cache) with as_of/age/stale; never fetches",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
    },
    {
        "id": "finviz_enrichment_snapshot",
        "module": "lib.data_broker.finviz_enrichment_snapshot",
        "entrypoints": ["get_enrichment_batch", "get_enrichment"],
        "http": [],
        "domain": "finviz_enrichment",
        "authority_domain": "finviz_enrichment",  # registered 2026-10-10 (operator, CONSOLIDATION_PLAN §D.2)
        "description": "Finviz six-view enrichment per symbol (rsi/float/rvol/atr/valuation/performance) "
                       "from data/state/ticker_enrichment_cache.json, single writer scripts/finviz_enrichment.py; "
                       "per-symbol as_of/age/stale, never fetches",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["directive_promotion (watch directives servicer, cron L442)"],
    },
    {
        "id": "scalp_list",
        "module": "lib.data_broker.scalp_list",
        "entrypoints": ["get_scalp_list", "get_scalp_enrichment", "freshness_report"],
        "http": [],
        "domain": "scalp_list",
        "authority_domain": "scalp_list",  # registered 2026-10-10 (operator, CONSOLIDATION_PLAN §D.5)
        "description": "Momentum-scalp list: the fresher of L1050's scalp_universe_latest.json (09:30-16:00) and the "
                       "hot-tier premarket screener membership (06:00-09:30, 2-min refresh receipt); hot enrichment "
                       "stamps for the list's names; the four hot-tier freshness SLOs. Never fetches, never writes",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["social_scalp_scanner (L246 --on-list-advance)",
                      "hermes_momentum_catalyst_researcher (L708 --on-list-advance)",
                      "run_finviz_momentum_scalp_scan (L636 proposal-stage trigger)",
                      "finviz_enrichment --scalp-hot", "social_ingest --scalp-list", "scalp_hot_tier_report"],
    },
    {
        "id": "quote_batch",
        "module": "lib.data_broker.quote_batch",
        "entrypoints": ["quote_row_from_broker"],
        "http": [],
        "domain": "quotes",
        "description": "Canonical single-symbol quote via quote-only get_best_quote (stored quote first, a "
                       "provider only when stale, stopping at the first fresh answer)",
        "read_only": True,
    },
    {
        "id": "symbol_profile",
        "module": "lib.data_broker.symbol_profile",
        "entrypoints": ["get_symbol_profiles"],
        "http": [],
        "domain": "identity",
        "description": "Sector, industry, instrument_type, earnings from symbol_profiles",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "analyst_rollup",
        "module": "lib.data_broker.analyst_rollup",
        "entrypoints": ["get_analyst_rollup"],
        "http": [],
        "domain": "street",
        "description": "Street consensus pills (pro_analyst_pills_latest.json)",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "analyst_detail",
        "module": "lib.data_broker.analyst_detail",
        "entrypoints": ["get_analyst_targets"],
        "http": [],
        "domain": "street",
        "description": "Yahoo target history rollup",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "catalyst_record",
        "module": "lib.data_broker.catalyst_record",
        "entrypoints": ["normalize_catalyst_row", "get_catalyst_record"],
        "http": [],
        "domain": "catalysts",
        "description": "Verified catalyst_events rows",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "indicator_snapshot",
        "module": "lib.data_broker.indicator_snapshot",
        "entrypoints": ["get_indicator_snapshot"],
        "http": [],
        "domain": "technicals",
        "description": "RSI/MACD/ATR/OBV snapshot store",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "portfolio_snapshot",
        "module": "lib.data_broker.portfolio_snapshot",
        "entrypoints": ["get_portfolio_snapshot"],
        "http": [],
        "domain": "portfolio",
        "description": "Book totals and holdings snapshot",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "entry_plan",
        "module": "lib.data_broker.entry_plan",
        "entrypoints": ["get_entry_plans"],
        "http": [],
        "domain": "mechanics",
        "description": "Deterministic entry plan rows",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "reentry_decision_desk",
        "module": "lib.data_broker.reentry_decision_desk",
        "entrypoints": ["build_decision_desk"],
        "http": ["GET /api/v2/reentry/decision-desk"],
        "domain": "reentry",
        "description": "Re-Entry READY/NEAR/BLOCK desk (broker-backed, no LLM)",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Re-Entry", "Watch"],
    },
    {
        "id": "watch_prospects",
        "module": "lib.data_broker.watch_prospects",
        "entrypoints": ["list_watch_prospects", "build_watch_prospects", "from_cio_prospect"],
        "http": ["GET /api/v3/data-broker/watch-prospects"],
        "domain": "watch",
        "description": (
            "Watch prospect lanes (Actionable now / Setup forming / Re-entry near / Manage / Expired): one row per "
            "security with conviction + components, stance, conflicts shown never resolved, next trigger (reference "
            "level) and one next step. Reads the cio_prospect projection when it is live; until then an interim "
            "adapter over cio_opportunity_projection, watch_decision.v1, the Trade AI decision projection, the "
            "Watch held reader and the re-entry desk, labelled interim."
        ),
        "contract_version": "WatchProspects@v1",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Watch (/v3/watch)"],
    },
    {
        "id": "watch_curation",
        "module": "lib.data_broker.watch_curation",
        "entrypoints": ["list_watch_curation", "build_curation", "suggest", "rotate", "ownership_conflicts"],
        "http": ["GET /api/v3/data-broker/watch-curation"],
        "domain": "watch",
        "description": (
            "My Watchlist (every operator name — stars, personal watchlist, operator directives, operator adds — "
            "starred first, never capped, expiry only suggests) and System Suggests (top N, default 20, max 30, of "
            "the curator's Full universe ranking minus held / yours / dismissed, rotating with hysteresis and a "
            "reason for every entry and exit). Rows come from the same watch_prospects.gather() composition as the "
            "Prospects lanes. Ownership conflicts between the curator and the Watch held reader are listed, never "
            "resolved."
        ),
        "contract_version": "WatchCuration@v1",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Watch (/v3/watch?tab=my-watchlist, ?tab=suggests, ?tab=opportunities)"],
    },
    {
        "id": "watch_universe",
        "module": "lib.data_broker.watch_universe",
        "entrypoints": ["list_watch_universe", "build_universe", "overlay"],
        "http": ["GET /api/v3/data-broker/watch-universe"],
        "domain": "watch",
        "description": (
            "Watch › Full universe: the CIO curator's ranked list (cio_opportunity_projection.json) with position "
            "facts per row — held / formerly held / never held from the Watch held reader, the last round trip "
            "(entry, exit, P/L, R, exit cause) and the re-entry advice from the CIO prospect lifecycle "
            "(watch_position_facts). A sold name the curator still treats as owned shows Type Re-entry / formerly "
            "held with the curator's own values kept beside it. Curator filters plus position filters and sorts, "
            "all URL parameters; count chips per option."
        ),
        "contract_version": "WatchUniverse@v1",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Watch (/v3/watch?tab=opportunities)"],
    },
    {
        "id": "watch_intelligence",
        "module": "lib.data_broker.watch_intelligence",
        "entrypoints": [
            "list_watch_intelligence",
            "detail_watch_intelligence",
            "watch_filters",
            "watch_lists",
            "watch_reviews",
        ],
        "http": [
            "GET /api/v3/data-broker/watch-intelligence",
            "GET /api/v3/data-broker/watch-intelligence/{symbol}",
            "GET /api/v3/data-broker/watch-filters",
            "GET /api/v3/data-broker/watch-lists",
            "GET /api/v3/data-broker/watch-reviews/{symbol}",
        ],
        "domain": "watch",
        "description": (
            "Primary Watch Intelligence projection: identity, canonical quote, Street, "
            "Trade AI decision, CIO/Maria review artifacts, catalyst, relative performance, "
            "membership (starred/held/screener). Composes existing broker domains; zero "
            "provider calls on page load."
        ),
        "contract_version": "watch_intelligence.broker.v1",
        "read_only": True,
        "provider_calls": 0,
        "primary_ui": "/v3/watch",
        "composes": [
            "market_quote / watch_canonical_quote",
            "symbol_profile",
            "analyst_rollup / yahoo targets",
            "catalyst_record",
            "decision_packets (Trade AI)",
            "review artifacts (COMPLETE only with full provenance)",
            "operator_starred_symbols",
            "holdings.json",
            "screener_find_pins",
        ],
        "consumers": [
            "Watch Intelligence (primary /v3/watch)",
            "Portfolio",
            "Re-Entry",
            "Risk",
            "Active Trader",
            "Research Intelligence",
            "Agents",
            "Reports",
        ],
        "commands_not_broker": [
            "POST /api/v3/watch/commands/star",
            "POST /api/v3/watch/commands/list-membership",
            "POST /api/v3/watch/commands/alert",
            "POST /api/v3/watch/commands/refresh-data",
        ],
        "status": "active",
        "advertised": True,
    },
    {
        "id": "watch_decision_desk",
        "module": "lib.data_broker.watch_decision_desk",
        "entrypoints": [],
        "http": [],
        "domain": "watch",
        "description": "Legacy watch decision desk helper (prefer watch_intelligence for UI)",
        "read_only": True,
        "status": "legacy",
    },
    # 2026-09-13 One Source of Truth: three modules that existed in this package but
    # were never catalogued, so config/data_source_authority.json could not name them
    # as a domain's read path. Declared here, unchanged in behaviour.
    {
        "id": "sector_momentum",
        "module": "lib.data_broker.sector_momentum",
        "entrypoints": ["get_sector_momentum"],
        "http": [],
        "domain": "sectors",
        "description": "Sector relative-strength momentum from sector_rs_daily / sector_momentum_latest",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "risk_snapshot",
        "module": "lib.data_broker.risk_snapshot",
        "entrypoints": ["get_risk_snapshot"],
        "http": [],
        "domain": "risk",
        "description": "Regime, VIX and book-risk snapshot (market_regime_snapshots + risk state)",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "research_card",
        "module": "lib.data_broker.research_card",
        "entrypoints": ["get_research_cards"],
        "http": [],
        "domain": "research",
        "description": "Per-symbol research cards from watchlist_research_cards",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "desk_feeds",
        "module": "lib.data_broker.desk_feeds",
        "entrypoints": ["get_report_feed", "get_redeploy_cache_feed"],
        "http": [],
        "domain": "reports",
        "description": "Envelope readers for the Reports (ai_reports) and Redeploy (redeploy_analytics_cache) dead stores — gap.kind=no_producer with the real last as_of",
        "read_only": True,
        "provider_calls": 0,
        "status": "active",
    },
    {
        "id": "cio_portfolio",
        "module": "lib.data_broker.cio_portfolio",
        "entrypoints": [
            "get_cio_snapshot",
            "get_cio_domain",
            "get_cio_material_changes",
        ],
        "http": [
            "GET /api/v3/data-broker/cio/snapshot",
            "GET /api/v3/data-broker/cio/domain/{domain}",
            "GET /api/v3/data-broker/cio/changes",
        ],
        "domain": "cio",
        "description": (
            "Unified CIO snapshot: portfolio, risk, watch, rotation, income, "
            "reconciliation — aggregated into one read. Composes existing broker "
            "domains; zero provider calls."
        ),
        "contract_version": "cio-snapshot-v1",
        "read_only": True,
        "provider_calls": 0,
        "composes": [
            "portfolio_snapshot",
            "risk_snapshot",
            "watch_intelligence",
            "rotation_ladders",
            "strategy_desk",
        ],
        "consumers": [
            "CIO Heartbeat",
            "Alex / CIO synthesis",
            "Command Center /v3/cio",
        ],
    },
    # 2026-09-13 One Source of Truth, Phase 4 — "the broker is the only read path".
    # Every projection below returns the shared read envelope from
    # lib.data_broker.envelope (as_of, age_hours, source, stale, gap) with the stale
    # window read from config/data_source_authority.json. Hub handlers in
    # scripts/api_v2.py that used to `FROM <table>` these stores now call here.
    {
        "id": "market_regime",
        "module": "lib.data_broker.market_regime",
        "entrypoints": ["get_market_regime", "regime_line"],
        "http": [],
        "domain": "risk",
        "authority_domain": "market_regime",
        "description": "Latest + history from market_regime_snapshots (writer market_regime_classifier.py); envelope-wrapped",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["Defense", "Sectors", "Reports", "risk_snapshot (may compose)"],
    },
    {
        "id": "daily_bars",
        "module": "lib.data_broker.daily_bars",
        "entrypoints": ["get_last_close", "get_daily_bars"],
        "http": [],
        "domain": "technicals",
        "authority_domain": "technicals",
        "description": "Daily closes from ticker_prices (last close / close series); envelope-wrapped",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["Defense hedge_state"],
    },
    {
        "id": "subject_research",
        "module": "lib.data_broker.subject_research",
        "entrypoints": ["get_subject_research"],
        "http": [],
        "domain": "research",
        "authority_domain": "research_thesis",
        "description": "hermes_research_intelligence rows keyed by symbol / subject_guid / sector; READ ONLY, never queues",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["Sectors subject-intel", "Intelligence"],
    },
    {
        "id": "agent_opinion",
        "module": "lib.data_broker.agent_opinion",
        "entrypoints": ["get_agent_opinion", "get_agent_roster", "get_debate_summary"],
        "http": [],
        "domain": "agents",
        "authority_domain": "agent_opinion",
        "description": (
            "Per-agent roster from watchlist_agent_results (alive) + debate summary from "
            "agent_debate_log (dead since 2026-05-05 — declared as gap.no_producer); composes agent_results"
        ),
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "composes": ["agent_results"],
        "consumers": ["Agents"],
    },
    {
        "id": "option_chain",
        "module": "lib.data_broker.option_chain",
        "entrypoints": ["get_option_chain"],
        "http": [],
        "domain": "options",
        "authority_domain": "options_iv",
        "description": (
            "options_iv_history store read (IV, ATM strike, underlying) with age. "
            "live_external at Schwab: NO provider call from the projection — states the age instead"
        ),
        "read_only": True,
        "provider_calls": 0,
        "live_external": "schwab (declared, never called here)",
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["Options", "Defense hedging radar"],
    },
    {
        "id": "watch_discovery",
        "module": "lib.data_broker.watch_discovery",
        "entrypoints": [
            "feed_envelope",
            "quality_gate_rows",
            "wide_finds_rows",
            "track_record_row",
            "directive_alpha_events",
            "directive_score_meta",
        ],
        "http": [],
        "domain": "watch",
        "authority_domain": "watch_discovery",
        "description": (
            "watch_candidate_events (DEAD feed: 13,093 rows, last 2026-07-16, no INSERT in repo). "
            "Every read carries gap.kind=no_producer with the last as_of"
        ),
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "status": "dead_feed",
        "consumers": ["Watch Discovery / Screener Finds", "Watch directives"],
    },
    # Investment Command Center (operator 2026-10-08)
    {
        "id": "price_stats",
        "module": "lib.data_broker.price_stats",
        "entrypoints": ["get_price_stats"],
        "http": [],
        "domain": "technicals",
        "description": "52-week range, 1W/1M change, SMA 20/50/200, 30-session avg volume, relative volume — derived from ticker_prices + market_ohlcv_bars",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["Investment Command Center"],
    },
    {
        "id": "ohlc_bars",
        "module": "lib.data_broker.ohlc_bars",
        "entrypoints": ["get_daily_ohlc"],
        "http": ["/api/v3/opportunities/{symbol}"],
        "domain": "technicals",
        "description": "Daily candles from market_ohlcv_bars (falls back to ticker_prices closes)",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        # watchlist_entry_planner: yfinance-fallback bars (L473/L474), operator ruling 2026-10-10 — no broker keys.
        "consumers": ["Opportunity modal chart", "watchlist_entry_planner (bars fallback)"],
    },
    {
        "id": "positions_context",
        "module": "lib.data_broker.positions_context",
        "entrypoints": ["get_positions_context"],
        "http": [],
        "domain": "holdings",
        "authority_domain": "holdings_accounts",
        "description": "Per-symbol shares, value, avg cost, unrealized, weight (holdings.json) + last sell date; realized/days held pending the positions_store reader",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Opportunity modal portfolio context"],
    },
    {
        "id": "trade_journey",
        "module": "lib.data_broker.trade_journey",
        "entrypoints": ["list_trade_journeys", "detail_trade_journey", "build_trade_journeys", "from_cio_prospect"],
        "http": ["GET /api/v3/data-broker/trade-journeys", "GET /api/v3/data-broker/trade-journeys/{trade_id}"],
        "domain": "trade_journal",
        "description": (
            "TradeInView per-trade journey (operator 2026-10-22): open + recently closed trades with origin (internal "
            "surface, rank and conviction at entry, CIO entry call — or the operator's own pick), stop path, conviction/"
            "stance changes, exit cause, post-exit review (facts first, model prose labelled advisory) and re-entry "
            "conditions from the re-entry desk record Watch reads. Reads the cio_prospect projection when its store is "
            "live; until then an interim adapter over schwab_round_trips, holdings_accounts, trade_transactions, "
            "recommendation links, cio_entry_states, stop_last_known, the CIO opportunity history and ohlc_bars, "
            "labelled interim."
        ),
        "contract_version": "TradeJourneys@v1",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["TradeInView (/v3/journal)"],
    },
    {
        "id": "opportunity",
        "module": "lib.data_broker.opportunity",
        "entrypoints": ["universe", "gather", "assess", "rank"],
        "http": ["/api/v3/opportunities", "/api/v3/opportunities/{symbol}"],
        "domain": "opportunity",
        "authority_domain": "opportunity_assessment",
        "description": "Risk/reward ladder, six factor scores, conviction, rank, type, condition, stance (config/opportunity_conviction.yaml); curated into CIO memory by cio_opportunity_curator",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Investment Command Center", "Telegram opportunity line"],
    },
    {
        "id": "earnings_calendar",
        "module": "lib.data_broker.earnings_calendar",
        "entrypoints": ["get_earnings", "upcoming"],
        "http": [],
        "domain": "earnings_calendar",
        "authority_domain": "earnings_calendar (PROPOSED 2026-10-10; operator grant pending)",
        "description": "Whole-market earnings calendar (report date, pre/post-market timing, estimate) published by "
                       "the Alpha Vantage owner (one EARNINGS_CALENDAR call/day); file read only, envelope, say_so on gap",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": [],
    },
    {
        "id": "news_sentiment",
        "module": "lib.data_broker.news_sentiment",
        "entrypoints": ["get_sentiment", "get_articles"],
        "http": [],
        "domain": "news_sentiment",
        "authority_domain": "news_sentiment (PROPOSED 2026-10-10; operator grant pending)",
        "description": "Per-ticker relevance-weighted news sentiment over 72 h from the Alpha Vantage owner's "
                       "windowed NEWS_SENTIMENT pulls; file read only, envelope, say_so on gap",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": ["scripts/catalyst_enrichment.py (alpha_vantage slot)",
                      "scripts/external_market_data_ingest.py --news-sentiment"],
    },    {
        "id": "home_do_now",
        "module": "lib.data_broker.home_do_now",
        "entrypoints": ["build", "probe_pending_proposals"],
        "http": ["/api/v2/home/do-now"],
        "domain": "home_do_now",
        "authority_domain": None,
        "contract_version": "HomeDoNow@v1",
        "description": "Home 'Do now' queue (operator-approved Home redesign 2026-10-22): one deduplicated, "
                       "money-at-risk-first queue (protect / decide / fix) composed from needs-action, the operator "
                       "inbox, the risk snapshot, the held-exit-coverage receipt, pending paper proposals and open "
                       "redeploys; per-source as_of / age / stale; an unreadable source is an item. Owns no store; "
                       "positions via risk_snapshot (holdings.json) until a positions_current reader batch covers Home",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Command Center v3 Home (Do now queue, three numbers)"],
    },
    {
        "id": "cio_prospect",
        "module": "lib.data_broker.cio_prospect",
        "entrypoints": ["get_prospects", "get_prospect", "get_position_view"],
        "http": [],
        "domain": "cio_prospect",
        "authority_domain": "cio_prospect (PROPOSED 2026-10-22, AGENTS.md §26; operator grant pending)",
        "description": "The CIO prospect — one record per security_guid (stage, conviction + components, stance, "
                       "next trigger, what's missing, next action, conflicts, evidence_at/expires_at). Reads the "
                       "cio_prospect store only when it is live (row granted + flag + table); otherwise the shadow "
                       "build, labelled SHADOW; say_so on gap; per-row stale after expires_at. get_position_view: "
                       "origin, lifecycle, post-exit review and re-entry advice for TradeInView / Open Trades / Watch",
        "read_only": True,
        "provider_calls": 0,
        "envelope": "BrokerReadEnvelope@v1",
        "consumers": [],
    },
]


def broker_catalog() -> dict[str, Any]:
    """Full Data Broker advertisement payload."""
    watch = next((p for p in PROJECTIONS if p["id"] == "watch_intelligence"), {})
    return {
        "ok": True,
        "service": "data_broker",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package": "scripts/lib/data_broker",
        "description": (
            "Trade AI Data Broker — canonical read models. Applications must not "
            "re-select quotes, invent Street ratings, or fabricate LLM provenance."
        ),
        "index": "GET /api/v3/data-broker",
        "projection_count": len(PROJECTIONS),
        "projections": PROJECTIONS,
        "watch_intelligence": {
            "primary": True,
            "contract_version": watch.get("contract_version"),
            "http": watch.get("http"),
            "ui": watch.get("primary_ui"),
            "composes": watch.get("composes"),
            "consumers": watch.get("consumers"),
            "provider_calls_on_page_load": 0,
        },
        "rules": [
            "Broker projections are read-only",
            "Mutations use governed command endpoints, not projection POSTs",
            "Page load must not call LLM providers",
            "COMPLETE reviews require full immutable provenance",
            "Missing review → Provider NONE / Model NONE / Policy NO_CALL / Cost $0",
        ],
        "provider_calls": 0,
    }
