# Holdings workspace v2 discovery and acceptance
Scope: /wealth/portfolio/holdings. Operator-approved layout is a private local visual reference; no sample positions, account identifiers or amounts are copied here. Its verified SHA256 is 0c94b2107e8023c271f1376fe12856c75976205075b3a9793790550eddf5239a.

## Source-to-page trace
[CODE] Stored holdings/enrichment/technical/basis and stop observations → existing broker/CIO/n8n producers → holdings.json, enrichment cache, cost_basis_anchors and stop-read fields → scripts/api_v2.py::portfolio_holdings → scripts/lib/cio_truth.py::holdings_payload → api_v2.py::_cio_holdings_with_evidence → GET /api/v2/portfolio/holdings → portfolio/adapter.ts::adaptHoldings → liveProps.ts::holdingsProps → HoldingsLive.tsx → HoldingsPage.tsx → workspaceV2/Workspace.tsx. Existing snapshot publication continues to drive the shell top bar. No producer or broker call originates in the workspace.
[CODE] Separate reads inspected: aggregate performance_history.json reader has no demonstrated per-row economic-period contract, and its live API may write a YTD pin; it is not called. The separate live-stops route calls a broker helper and is not called. Stored holdings protection fields are reused. Symbol-headlines is an existing guarded news_articles SELECT reader, with source/link/publication clock; upcoming dates must come from existing calendars, not inferred dates.
[CODE] Existing dividend-calendar-refresh n8n lane and LaneRunReceipt@v2 are registered; this source has live_arg:null. portfolio_dividend_calendar.py derives annual/monthly forecasts from static KNOWN_SCHEDULES and separately reads declared dates from ticker_dividend_data (sync_dividend_data.py producer). Forecast is not received income; static yield is not a current verified book yield. No duplicate scheduler or activation is introduced.

## Implemented small batch
- [x] One table; six columns; security groups with account subrows; account mode keeps source order.
- [x] Small positions collapse below $100, except unrealized loss at least $100; cash/sweep collapse separately.
- [x] AND filters: period (served estimates/unrealized only), sector/Funds/Cash, account, gain/loss sign, protection, size, query; reset; shared URL state and CSV population.
- [x] Display sums with n-of-m and partial coverage; missing is not zero; invested/cash distinct; weighted remaining-basis average only over complete covered basis.
- [x] Top-three contributors and detractors, plus Other; protection gaps restricted to the material filter population.
- [x] Closed/open lock, warning, news, calendar, shield and neutral icons from approved markup; text accompanies icons. Pending/stale/unknown records never earn a closed Protected lock.
- [x] Evidence retains all original source clocks, unknown definitions, account-measure disclosure and four row drawer tabs: Position, Fundamentals, Levels, Protection.
- [ ] Browser acceptance: all filters in combination, URL history/reload, CSV, cash/small/group expand, evidence/account disclosures, each row detail tab and Escape/focus return at 390/412/1280/1440.
- [ ] Publish qualified batch on latest live head, then repeat affected live views at all four widths and check exact build.
- [ ] News panel: connect existing stored-only guarded symbol-headlines reader; inspect source, publication time and working contextual links.
- [ ] Upcoming panel: connect existing declared-date reader; estimates separate from declarations/receipts.
- [ ] Full period-profit, received-income, tax type, cash yield and per-account result contracts: upstream gaps listed below, not fabricated.

## Explicit missing contracts / next backend work
- Per-row 1W/1M/3M/YTD/1Y/custom economic profit, period starts, realized profit and received income are not served by holdings. Those controls stay disabled. Last-session is a price-change estimate with UNKNOWN observation date; since-purchase means remaining-position unrealized only.
- No served tax/account-tax classification; filter withheld. No inferred tax labels.
- Cash yield and YTD cash receipts are not served. Missing is not zero.
- Stable confirmed security identity is not guaranteed. Existing ticker-keyed identity caveats remain; no invented logos or CUSIP verification.
- Backend materialization changes belong in established n8n producers, with versioned stored contracts, source/build timestamps, coverage, idempotency, bounded retries/recovery and observable failure receipts. Reuse retained CIO memory and existing stores.
- Fundamentals four Unknown cards remain owned by its assigned worker; source and static-yield provenance findings were routed to Claude and that owner. Holdings files do not overlap Fundamentals.

## Verification
[VERIFIED] node --test scripts/tests/holdings-workspace.test.mjs: 11 passed, 0 failed. Covers independent expected arithmetic, partial/missing/zero, account/security mode, floor pin, AND/CSV parity, URL reset, top movers reconciliation and each protection/icon state.
[VERIFIED] flock -w 20 /data/agent-tmp/s2-heavy-1.lock npm run build: exit 0; contract/design/shell/performance gates, TypeScript and Vite passed (86 modules). Build receipt is not live acceptance.
Rollback was snapshotted before the first implementation edit and verified against all eight original immutable assets. Current live head must be merged before promotion; deployment uses the shared atomic activation script and automatic rollback.

## Stored-only wire inventory
Inventory below records names/types/coverage only from one authorized local stored-only response capture. No financial values or identifiers are exported. It describes that capture, not current freshness. "Shown" means mapped to the workspace, existing row drawer or retained evidence; "not shown" remains inspectable upstream. Missing requested fields are explicitly "not served" above.

Capture file mtime UTC: 2026-11-15T20:03:58.615163Z; rows: 30.

### Row fields

| Field | JSON types | Non-null rows | State |
|---|---|---|---|
| _basis_rebased_from | float | 5/30 | not shown |
| _rebuild_source | str | 22/30 | not shown |
| account | str | 30/30 | shown |
| account_id | str | 30/30 | not shown |
| account_key | str | 30/30 | shown |
| account_label | str | 30/30 | shown |
| account_scope | str | 1/30 | not shown |
| adjusted_for_transfer | NoneType | 0/30 | not shown |
| analysis_note | str | 7/30 | not shown |
| analyst_rating | NoneType | 0/30 | shown |
| analytical_market_value | float | 25/30 | not shown |
| analytical_unrealized_pl_usd | NoneType, float | 24/30 | not shown |
| as_of | str | 30/30 | not shown |
| asset_type | str | 30/30 | shown |
| atr | NoneType, float | 23/30 | not shown |
| avg_cost | float | 30/30 | shown |
| basis_partial | bool | 19/30 | not shown |
| basis_status | str | 22/30 | not shown |
| basis_truth | dict | 25/30 | not shown |
| beta | NoneType, float | 22/30 | shown |
| broker | str | 30/30 | not shown |
| broker_actual_shares | float | 30/30 | not shown |
| broker_avg_price | float | 30/30 | not shown |
| broker_day_pl | float | 24/30 | not shown |
| broker_day_pl_at | str | 24/30 | not shown |
| broker_day_pl_price | float | 24/30 | not shown |
| broker_ingested_at | str | 30/30 | not shown |
| broker_market_value | float | 30/30 | not shown |
| broker_position_as_of | str | 30/30 | not shown |
| broker_position_as_of_at | str | 30/30 | not shown |
| broker_position_price | float | 30/30 | not shown |
| broker_protected | bool | 25/30 | not shown |
| broker_shares | float | 30/30 | not shown |
| broker_source | str | 30/30 | not shown |
| bucket | str | 29/30 | not shown |
| business_date | str | 1/30 | not shown |
| calculation_version | str | 1/30 | not shown |
| canonical_mark | float | 25/30 | not shown |
| canonical_mark_as_of | NoneType | 0/30 | not shown |
| canonical_mark_ingested_at | str | 25/30 | not shown |
| canonical_mark_source | str | 25/30 | not shown |
| canonical_mark_type | str | 25/30 | not shown |
| company | str | 30/30 | shown |
| conflict_reason | NoneType, str | 4/30 | not shown |
| conflicted | bool | 28/30 | not shown |
| contract_version | str | 1/30 | not shown |
| cost_basis | NoneType, float | 24/30 | not shown |
| cost_basis_broker | NoneType, float | 24/30 | not shown |
| cost_basis_note | NoneType, str | 13/30 | not shown |
| cost_basis_source | NoneType, str | 24/30 | not shown |
| cost_basis_total | float | 30/30 | shown |
| current_account | str | 30/30 | not shown |
| current_price | float | 30/30 | shown |
| current_price_is_alias_of | str | 25/30 | not shown |
| data_available | bool | 30/30 | not shown |
| day_change | float, int | 30/30 | shown |
| day_change_broker_check | dict | 24/30 | not shown |
| day_change_broker_pl_diff | float | 22/30 | not shown |
| day_change_mark_price | float | 23/30 | not shown |
| day_change_pct | float, int | 30/30 | shown |
| delisted | bool | 22/30 | not shown |
| enrichment_as_of | str | 30/30 | not shown |
| entitlement_state | str | 1/30 | not shown |
| eps_next_y | NoneType | 0/30 | shown |
| eps_ttm | NoneType | 0/30 | shown |
| fib | NoneType, dict | 24/30 | shown |
| forward_pe | NoneType, float | 12/30 | shown |
| freshness_state | str | 1/30 | not shown |
| gain_loss | NoneType, float | 24/30 | shown |
| gain_loss_pct | NoneType, float | 24/30 | shown |
| implied_price_from_mv | float | 28/30 | not shown |
| industry | str | 30/30 | shown |
| insider_own_pct | NoneType, float | 12/30 | shown |
| inst_own_pct | NoneType, float | 14/30 | shown |
| is_cash | bool | 30/30 | not shown |
| last_reconciled_at | NoneType, str | 6/30 | not shown |
| last_reconciliation_source | NoneType, str | 6/30 | not shown |
| llm_action | NoneType, str | 25/30 | not shown |
| llm_at | NoneType, str | 25/30 | not shown |
| llm_confidence | NoneType, int | 25/30 | not shown |
| llm_data_i_doubt | NoneType, str | 25/30 | not shown |
| llm_evidence | list | 30/30 | not shown |
| llm_health | NoneType, str | 25/30 | not shown |
| llm_lots | int | 30/30 | not shown |
| llm_summary | NoneType, dict | 25/30 | not shown |
| lookthrough | list | 30/30 | not shown |
| lookthrough_status | str | 30/30 | not shown |
| lots_shares | NoneType, float | 17/30 | not shown |
| market_cap_b | NoneType, float | 14/30 | shown |
| market_session | str | 1/30 | not shown |
| market_value | float | 30/30 | shown |
| market_value_as_of | str | 30/30 | not shown |
| market_value_source | str | 30/30 | not shown |
| mv_basis | str | 30/30 | not shown |
| name | str | 30/30 | shown |
| normalization_status | NoneType | 0/30 | not shown |
| normalized_after_transfer | NoneType | 0/30 | not shown |
| normalized_at | str | 1/30 | not shown |
| observation | dict | 1/30 | not shown |
| official_close | NoneType | 0/30 | not shown |
| official_close_as_of | NoneType | 0/30 | not shown |
| original_source_account | NoneType | 0/30 | not shown |
| pe | NoneType, float | 12/30 | shown |
| peg | NoneType, float | 9/30 | shown |
| perf_ytd_pct | NoneType, float | 23/30 | shown |
| performance_adjusted | NoneType | 0/30 | not shown |
| pi_score | NoneType, int | 25/30 | not shown |
| portfolio_pct | float | 30/30 | shown |
| position_clock | dict | 30/30 | not shown |
| price | float | 30/30 | shown |
| price_as_of | str | 30/30 | shown |
| price_bar_end | NoneType, str | 23/30 | not shown |
| price_field_role | str | 22/30 | not shown |
| price_live | bool | 30/30 | not shown |
| price_source | str | 30/30 | not shown |
| price_stale | bool | 25/30 | not shown |
| prior_close | NoneType, float | 23/30 | not shown |
| profile_source | str | 30/30 | shown |
| profile_updated_at | str | 30/30 | shown |
| protection | dict | 30/30 | shown |
| protection_stale | NoneType, bool | 29/30 | shown |
| protection_state | str | 30/30 | shown |
| provider_observed_at | str | 1/30 | not shown |
| proxy | dict | 1/30 | not shown |
| quality_state | str | 1/30 | not shown |
| quantity | float | 30/30 | shown |
| quote_change_pct | NoneType, float | 23/30 | not shown |
| quote_feed | NoneType, str | 23/30 | not shown |
| quote_inserted_at | NoneType, str | 23/30 | not shown |
| quote_price | NoneType, float | 23/30 | not shown |
| quote_session | NoneType, str | 23/30 | not shown |
| quote_source | str | 30/30 | not shown |
| received_at | str | 1/30 | not shown |
| recom_score | NoneType | 0/30 | not shown |
| reference_basis | NoneType, str | 23/30 | not shown |
| rsi | NoneType, float | 24/30 | shown |
| rsi_status | NoneType, str | 25/30 | not shown |
| sector | str | 30/30 | shown |
| sector_freshness | dict | 30/30 | not shown |
| sector_kind | str | 30/30 | not shown |
| security_guid | str | 23/30 | not shown |
| security_guid_source | str | 23/30 | not shown |
| share_drift | NoneType, int | 27/30 | not shown |
| share_drift_source | NoneType, str | 1/30 | not shown |
| share_drift_status | NoneType, str | 27/30 | not shown |
| shares | float | 30/30 | shown |
| shares_synced_at | str | 27/30 | not shown |
| short_float_pct | NoneType, float | 14/30 | shown |
| signal | str | 30/30 | not shown |
| sma200_pct | NoneType, float | 24/30 | shown |
| sma20_pct | NoneType, float | 24/30 | shown |
| sma50_pct | NoneType, float | 24/30 | shown |
| source | str | 30/30 | not shown |
| source_identity | str | 1/30 | not shown |
| source_timestamp | str | 30/30 | not shown |
| stop_captured_at | NoneType, str | 9/30 | not shown |
| stop_evidence | dict | 25/30 | not shown |
| stop_history | NoneType, dict | 8/30 | not shown |
| stop_note | NoneType, str | 8/30 | not shown |
| stop_observation | NoneType, dict | 8/30 | not shown |
| stop_order_id | NoneType, str | 8/30 | not shown |
| stop_order_type | NoneType, str | 8/30 | not shown |
| stop_price | NoneType, float | 9/30 | shown |
| stop_qty | NoneType, float | 8/30 | not shown |
| stop_source | str | 25/30 | shown |
| stop_state | str | 25/30 | not shown |
| stop_state_observed | str | 25/30 | not shown |
| symbol | str | 30/30 | shown |
| sync_run_id | int | 30/30 | not shown |
| system_shares | float | 30/30 | not shown |
| transfer_display_note | NoneType | 0/30 | not shown |
| transfer_history | list | 30/30 | not shown |
| transfer_history_tag | NoneType | 0/30 | not shown |
| updated_at | str | 30/30 | not shown |
| week52_high_pct | NoneType, float | 23/30 | shown |
| yield_pct | NoneType, float | 2/30 | shown |

### Root fields

| Field | JSON type | State |
|---|---|---|
| account_value_change_1d | float | not shown |
| account_value_change_1d_start | float | not shown |
| account_value_change_1d_start_as_of | str | not shown |
| account_value_change_1d_status | str | not shown |
| as_of | str | shown (rows/evidence) |
| clock_provenance | dict | shown (rows/evidence) |
| count | int | shown (rows/evidence) |
| enrichment_as_of | str | not shown |
| equity_curve | list | not shown |
| evidence | dict | shown (rows/evidence) |
| freshness | dict | shown (rows/evidence) |
| generated_at | str | shown (rows/evidence) |
| holdings | list | shown (rows/evidence) |
| last_repriced | str | shown (rows/evidence) |
| measures | dict | shown (rows/evidence) |
| measures_input_gap | NoneType | shown (rows/evidence) |
| measures_materialized_at | str | shown (rows/evidence) |
| metrics | list | shown (rows/evidence) |
| position_count | int | shown (rows/evidence) |
| position_counts | dict | shown (rows/evidence) |
| positions_as_of | str | shown (rows/evidence) |
| pricing | dict | shown (rows/evidence) |
| quote_as_of | str | not shown |
| reconciliation | dict | shown (rows/evidence) |
| reconciliation_status | str | shown (rows/evidence) |
| reprice_source | str | not shown |
| scope_coverage | dict | shown (rows/evidence) |
| source_coverage | dict | shown (rows/evidence) |
| stops_read | dict | shown (rows/evidence) |
| today_change | float | not shown |
| today_change_basis | str | not shown |
| today_change_finviz_estimate | float | not shown |
| today_change_label | str | not shown |
| today_change_measure | str | not shown |
| today_change_status | str | not shown |
| total_cash | float | not shown |
| total_value | float | not shown |
| total_value_basis | str | not shown |
| total_value_finviz_delta | NoneType | not shown |
| total_value_finviz_estimate | NoneType | not shown |
| total_value_finviz_marks_at | str | not shown |
| total_value_measure | str | not shown |
| truth | dict | shown (rows/evidence) |
| valuation_as_of | str | shown (rows/evidence) |
| verified_daily_pnl | NoneType | not shown |
| verified_daily_pnl_status | str | not shown |


## Parallel completion tranche — 2026-11-15

User prioritized Holdings live and explicitly authorized subagents. Worktree /data/worktrees/tradeai-wt-codex-holdings-v2, branch wt/codex-holdings-v2. Fundamentals six-column implementation is preserved separately at c1ccb0ad3, outside this Holdings release.

- [VERIFIED] node --test scripts/tests/holdings-workspace.test.mjs: 15 tests pass. Independent cases cover grouping before the size floor, small securities in mover rankings, expanded-account weights, and cash applicability in account mode.
- [CODE] Served sub-cent marks use format::price. Nonzero marks do not round to zero. Mixed-security summary prices and average costs are not applicable; account fields remain intact.
- [CODE] Focusable protection status preserves reason, next step, read clock and reported freshness. Pending/stale records never become active. Partial current coverage uses a closed amber lock; unknown uses the neutral dash-circle.
- [CODE] News: existing ingestion -> Postgres news_articles -> api_v2::_symbol_headlines stored SELECT -> StoredNews::decodeStoredNews -> exact title/source/link/publication clock. Explicit user reads, max four concurrent; filter changes abort and fence older results.
- [VERIFIED] Independent BEFORE browser reproduced sub-cent rounding and account-cash applicability defects at all four widths. Private evidence /tmp/codex-holdings-browser-before.json.
- [DOC-CLAIM] Sourced yield contract 9a48fe4b7 prepared but not activated. Existing n8n lane remains owner; no duplicate. Static schedule does not establish current book yield.
- [CODE] Authorized stored holdings response has no per-row stop price. No live-stops or broker call; absent price remains unserved.

Next: integrate actual current live release; run checks and clean build; independently inspect production bundle at 390/412/1280/1440; package rollback-ready release; activation dry-run then serialize activation; verify served SHA and every affected live view. Deployment is not complete from this checkpoint.
