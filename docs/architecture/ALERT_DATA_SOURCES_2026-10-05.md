# Alert data sources — inventory 2026-10-05

Operator rule (2026-10-05): *"All of the alerts — the source of truth should be the Command Center for all data. If data needs to be refreshed, it's refreshed with the data broker in the Command Center and then spawned out. Each individual process should not be going out looking for its own data sources."*

Method: static scan (`scripts/lib/alert_source_scan.py`) of every file under `scripts/` that sends an operator alert (`send_telegram`, `deliver_notice`, `telegram_send`, `send_operator_alert`, `deliver_text`, `tg_send`, `_send_telegram`). Each file is classified by the data access in its own source, plus provider calls one local import down. Pattern matching finds code paths; it does not prove the path runs. The broker's own adapters (`scripts/lib/data_broker/`, `scripts/lib/writers/`) are the refresh path and are excluded.

## Summary

- Alert-producing files: **169**
- cc_store: 79
- provider (one import down): 35
- provider (direct): 19
- none: 18
- cc_api: 10
- not a data read: 6
- broker: 2

Classes: **provider** = calls a market-data provider itself (Yahoo/yfinance, Finviz, Alpaca, Schwab client, Alpha Vantage, moomoo, or the `get_best_quote` waterfall outside the broker). **broker** = reads through `lib.data_broker` / `lib.alert_quotes`. **cc_api** = reads the Command Center HTTP API. **cc_store** = reads Command Center stores (SQL / state files) directly, with no provider call; these follow the rule on sources but skip the broker's freshness envelope. **none** = sends text computed upstream.

## Fixed in this PR

| Producer | Before | After |
|---|---|---|
| `notify_material_change.py` (material-change page + daily digest) | price/age from `watchlist_items` enrichment (NVDA 26 h old at 16:15 while the broker had 16:00) | `lib.alert_quotes.broker_quotes` → data broker `market_quote` projection, refreshed through the broker waterfall when older than the registry contract (15 min open / 72 h closed) |
| `cio_entry_state_runner.py` (CIO ENTRY ALERT) | price from `watchlist_items`; options chain from `schwab_transport` directly (via `lib/buy_ready_options_alternatives.py`) | broker quotes; chain from the CC route `/api/v2/schwab/option-chain`; plan sanity: plan age, single-price zone that tracks the quote, stop > 25 % below entry, ≥ 15 % day move without a re-plan |
| `lib/telegram_rich.py` entry card | BUY READY rendered green when unreviewed | green only with a CIO review id |

## Producers calling a provider directly (19) — ratchet allowlist

`tests/test_alert_single_source_20261005.py` fails if a new producer joins this list, and fails if one leaves it without being removed (the list only shrinks).

| Producer | Providers | Also one import down |
|---|---|---|
| `scripts/active_trader/momentum_alerts.py` | moomoo | — |
| `scripts/finviz_ingestion.py` | finviz | — |
| `scripts/health_agent.py` | yahoo | alphavantage, finnhub, finviz, moomoo, polygon, schwab, waterfall |
| `scripts/incubator_proposal_promoter.py` | waterfall | alpaca, finviz, schwab, yahoo |
| `scripts/open_trade_monitor.py` | alpaca | — |
| `scripts/phase3_lookthrough_fetcher.py` | yahoo | — |
| `scripts/portfolio_alerts.py` | yahoo | moomoo |
| `scripts/portfolio_orchestrator.py` | yahoo | finviz, moomoo |
| `scripts/portfolio_technical.py` | finviz | — |
| `scripts/portfolio_weekly_report.py` | finviz | yahoo |
| `scripts/previously_traded_watchlist.py` | yahoo | — |
| `scripts/process_watchlist_agent_jobs.py` | yahoo | alpaca, alphavantage, finviz |
| `scripts/pullback_macd_screener.py` | yahoo | — |
| `scripts/run_proactive_quote_refresh.py` | waterfall | alpaca, finviz, schwab, yahoo |
| `scripts/scalp_critic_agent.py` | yahoo | — |
| `scripts/social_scalp_scanner.py` | finviz | yahoo |
| `scripts/technicals_gap_backfill.py` | yahoo | — |
| `scripts/trade_ai_orchestrator.py` | yahoo | alpaca, alphavantage, finviz, schwab, waterfall |
| `scripts/watchlist_entry_planner.py` | alpaca, yahoo | — |

## Producers reaching a provider one import down (35)

| Producer | Providers (via a local import) |
|---|---|
| `scripts/aegis_overnight.py` | finviz, yahoo |
| `scripts/agent_event_router.py` | yahoo |
| `scripts/agent_watchlist_engine.py` | alpaca, alphavantage, yahoo |
| `scripts/alpaca_live_read_sync.py` | finviz, moomoo |
| `scripts/atm_auto_approver.py` | waterfall |
| `scripts/audit_position_basis.py` | schwab |
| `scripts/auto_research.py` | finviz, moomoo, schwab, waterfall, yahoo |
| `scripts/check_data_source_health.py` | yahoo |
| `scripts/check_gap_resolution.py` | yahoo |
| `scripts/check_operator_answer_quality.py` | yahoo |
| `scripts/continuous_runner.py` | alphavantage, finviz, yahoo |
| `scripts/defense_execution.py` | schwab |
| `scripts/incubator_llm_screener.py` | finviz |
| `scripts/lib/gain_guardian_publish.py` | yahoo |
| `scripts/lib/options_pipeline/paper_position_alerts.py` | schwab |
| `scripts/options_lifecycle_alerts.py` | schwab |
| `scripts/overnight_batch.py` | alpaca, alphavantage, yahoo |
| `scripts/paper_trade_monitor.py` | waterfall |
| `scripts/pipeline_freshness_slo.py` | schwab |
| `scripts/portfolio_live_monitor.py` | finviz, moomoo |
| `scripts/portfolio_monthly_report.py` | yahoo |
| `scripts/proposal_paper_submitter.py` | alpaca, yahoo |
| `scripts/remediate_weekly_report_action.py` | finviz |
| `scripts/rerun_cio_dual_consensus.py` | yahoo |
| `scripts/rotation_autopilot.py` | waterfall |
| `scripts/run_alex_daily.py` | yahoo |
| `scripts/run_telegram_callback_poller.py` | waterfall |
| `scripts/schwab_position_sync.py` | schwab |
| `scripts/schwab_token_manager.py` | schwab |
| `scripts/send_telegram_proposal_alert.py` | alpaca, finviz, schwab, waterfall, yahoo |
| `scripts/supervisor_breach_detector.py` | yahoo |
| `scripts/system_rollup_snapshot.py` | finviz, moomoo, schwab, waterfall, yahoo |
| `scripts/telegram_command_handler.py` | alpaca, alphavantage, finviz, waterfall, yahoo |
| `scripts/telegram_smart_alerts.py` | yahoo |
| `scripts/trade_ai_news_monitor.py` | yahoo |

## Matched a provider pattern but not an alert data read

| File | Why |
|---|---|
| `scripts/api_v2.py` | the Command Center API server itself (hosts the broker endpoints) |
| `scripts/credential_monitor.py` | credential health probe — tests provider reachability by design |
| `scripts/finviz_health_check.py` | Finviz health probe — tests provider reachability by design |
| `scripts/moomoo/opend_health.py` | OpenD health probe — tests gateway reachability by design |
| `scripts/run_cio_hardening_ci.py` | CI runner; 'moomoo' appears in gate names only |
| `scripts/secrets_admin.py` | secret names only (MOOMOO_* keys) |

## Active Trader producers (report only; owned by open PRs #1444 and the alert-sync branch)

- `scripts/active_trader/momentum_alerts.py`: moomoo order book and tape through the OpenD quote context, directly. The data broker has no Level 2 projection, so this is a gap in the broker, not only a producer bypass.
- `scripts/scalp_shadow_logger.py` (feeds the alert pass): Alpaca IEX minute bars directly (`session_rth_bars`). The broker has `daily_bars` but no intraday bars projection.
- `scripts/active_trader/premarket_watch.py` (#1441): moomoo extended-hours 1-minute bars, book and tape directly.

## Migration plan

1. **Prices (quote_price):** every remaining producer that prices a symbol switches to `lib.alert_quotes.broker_quotes` (store read; broker waterfall refresh when stale). Mechanical; covers most of the yfinance and `get_best_quote` rows. Order: portfolio alerts and monitors first (operator-facing), then screeners.
2. **Bars:** add a broker `intraday_bars` projection backed by the existing bar writers; move `watchlist_entry_planner`, `pullback_macd_screener`, `technicals_gap_backfill` and the scalp logger to it.
3. **Finviz:** route reads through the existing Finviz store (finviz ingestion stays the single writer); producers stop calling Finviz exports themselves.
4. **Level 2 / tape:** promote the #1444 microstructure recorder into a broker domain (registry entry, freshness contract), so Active Trader reads book and tape from the Command Center like every other alert.
5. **Option chains:** every chain read goes through `/api/v2/schwab/option-chain` (`lib.alert_quotes.cc_option_chain`); `options_lifecycle_alerts` and `lib/options_pipeline/paper_position_alerts` are next.
6. **Ratchet:** each migration removes its file from `BYPASS_ALLOWLIST`. Extend the guard to fail on the one-import-down set once it is small.
