# Trading hub (Command Center v3 `/v3/trading`)

Status:      ACTIVE
as_of:       2026-10-22T16:30:00-04:00
Measured at: branches feat/trading-tabs-open-trades-20261022 (#1949) and feat/trade-ai-opportunities-20261022 (base origin/main b9804fa57) / not measured on the served release

The operator approved the Gate 3 designs on 2026-10-22 (`OpenTrades.dc.html`, `Main.dc.html`) and the
consolidation of the Trading tabs from eight to four. This document records the shape after that change:
which tabs exist, where every retired tab went, what the Open Trades desk reads, and the accuracy rules the
intelligence endpoint follows.

## Tabs

| Tab | What it is | Source |
|---|---|---|
| Trade AI (default) | Opportunities page (Gate 3 `Main.dc.html`) | `/api/v2/trade-ai/scanner`, `/api/v2/trade-ai/candidates`, `/api/v3/active-trader/alerts` |
| Options | Options desk (Gate 3, separate PR) | `/api/v2/options/*` |
| Open Trades | Protect-first position desk (this change) | `/api/v2/open-trades/intelligence`, `/api/v2/broker-reconciliation` (drawer) |
| Proposals | Path B broker queue, plus the Path A Entry Desk as a section (`section=path-a`) | `/api/v2/broker-proposals`, Entry Desk endpoints |

**Broker Orders is a desk, not a tab.** It opens only from its Telegram approval links
(`/v3/go/order/<intent>` → `?tab=Broker+Orders&intent=…`) and from `?tab=Broker+Orders`. The header shows it as
the selected desk when it is open. Its per-order 2FA flow (`BrokerOrders`) is unchanged.

## Retired tabs and where they went

Defined once in `apps/command-center-v3/src/lib/tradingDeepLink.ts` (`LEGACY_TAB_TARGETS`,
`legacyTradingRedirect`), tested in `tradingDeepLink.test.ts` and `e2e/trading-tabs-open-trades.spec.ts`. Old
Telegram messages, bookmarks and Reports links keep working.

| Old link | Now |
|---|---|
| `?tab=Entry+Desk`, `?tab=Manual+ToS`, `/v3/manual-execution` | Proposals · Path A section (`?tab=Proposals&section=path-a`), symbol kept |
| `?tab=Broker+Recon` | Open Trades with the Broker reconciliation drawer open (`drawer=recon`) |
| `?tab=Schwab+Accounts` | Broker Orders desk with the Schwab account monitor section (`section=schwab-accounts`) |
| `?tab=Scalp[&symbol=X]` | `/v3/active-trader?tab=Scalp[&symbol=X]` — the scalp setups panel and the live scalp list (`components/tradeai/ScalpLiveSignals.tsx`) |
| `?tab=ATM+Controls` | `/v3/system/broker-access#automation-controls` — `ATMControlPanel` unchanged, including EMERGENCY_STOP and PAUSED_ENTRIES |
| `?tab=Execution` | `/v3/journal` (execution quality lives on the Journal) |

Producers updated to the new targets: `scripts/lib/telegram_rich.cc_trading_url` (entry alerts →
Active Trader → Scalp), `src/lib/alertsCenter.ts`, `scripts/reports_portal.py` (broker-manual line →
Proposals · Path A), the triage chip for recon breaks (`tradingCommandTriage.ts` → Open Trades recon drawer),
`scripts/capture_cc_v3_trading_desks.py` and `scripts/cc_v3_playwright_audit.py`. `scripts/health_agent.py`
already pointed only at Proposals, Options and Broker Orders, all still valid; it was not changed.
`WatchlistHub.tsx` and `WatchlistProposeModal.tsx` still link `?tab=Entry+Desk`; the redirect handles it, and
those files belong to the Watch lane.

## Trade AI — Opportunities page

`components/tradeai/TradeAiOpportunities.tsx`, model `lib/tradeAiOpportunities.ts` (pure;
`tradeAiOpportunities.test.ts`), e2e `e2e/trade-ai-opportunities.spec.ts`. Gate 3 design `Main.dc.html`.

- **Reads existing endpoints only**: `/api/v2/trade-ai/scanner` (the hub's existing poll, passed in),
  `/api/v2/trade-ai/candidates` (Shared Momentum drawer summary; the full panel renders only when opened) and
  `/api/v3/active-trader/alerts` (served Level 2 entry signals).
- **Six filter tiles**: GO, WAIT, Manual review, Grade ★4+, Float < 5M, RVOL ≥ 10× — counted over the scanner
  universe the payload serves. Clicking a tile, a float, an RVOL or a sector adds a removable filter chip.
- **Float-first table** (Symbol · Float · Vol · RVOL · Chg · Catalyst · grade · validation · Act · Decision · L2)
  with column sort, or **Cards**. A float of 0 is shown as unknown, never as micro float.
- **AI analysis panel**: decision, catalyst headline, the scanner's existing critic when it ran, scanner facts
  (score, setup grade, scan catalyst verification), and **Level 2 · tape**. Entry chips map the served
  `l2.spread_bps`, `l2.depth_ratio` and `signals.detail` (`supply_thinning`, `ask_refill`, `book_pull`,
  `volume_acceleration`, `high_break`, `vwap_distance`) from the latest Active Trader decision for the symbol;
  a book older than 15 s is flagged stale. Exit chips (tape flip, volume climax, ask wall, close below prior low,
  VWAP loss) are computed only by the exit watch for open scalps and are not served for scanner names, so they
  show "—" with that reason. A symbol with no decision row shows NOT WATCHED.
- **Gate 2 fields** — catalyst type, catalyst grade (★), validation, the action score and the five AI checks —
  come from the CIO prospect record (AGENTS.md §26), which does not exist yet. They render "—" with a tooltip;
  the Grade ★4+ tile and the grade / Act sorts are disabled until a row carries them. The model reads
  `catalyst_type`, `catalyst_grade`, `catalyst_validation`, `catalyst_validation_ok` and `action_score` if the
  scanner payload ever serves them; nothing is invented.
- **Drawers**: Shared Momentum (collapsed; was the panel at the top of the tab) and Scanner tools (the previous
  scanner view: run health, run history, sector mix, Thinkorswim copy, Warrior audit).

## Open Trades desk

`components/OpenTradesDesk.tsx`, model `lib/openTradesDesk.ts` (pure; `openTradesDesk.test.ts`).

- **Headline**: positions and accounts (write-offs excluded), unrealized P/L excluding write-offs, how many
  positions have no basis, and how many positions (and dollars) have no working stop.
- **Freshness chips**: marks (latest and oldest mark time, count of stale marks), broker stop snapshot time,
  cost-basis gaps.
- **Protect first**: positions with no working broker stop, largest dollar exposure first. Funds that cannot
  take a stop order and fractional positions are "n/a", never "no working stop".
- **One table** with a PAPER badge on paper rows, filters (all, no working stop, stop near, losing, paper),
  account filter and sort. Each mark shows its own age; a stale mark hides the day move.
- **Detail panel**: tiles, stop history (broker order, coverage, pilot placement, stop alerts, advisor),
  advisory note, and three actions:
  - **Arm stop (2FA)…** opens `PositionDecisionCardV4` for the position, unchanged. The Stage 2c
    protective-stop ARM, preflight, per-order 2FA, Modify and Cancel controls are that card's own code;
    the desk only decides when to render it. A `?symbol=X` deep link selects X and opens its card.
  - **Protective put ideas** links to the Options desk.
  - **Snooze 1 week** posts the same advisory stop-alert snooze the card's "Ignore 1 week" uses
    (`/api/v2/holdings/stop-snooze`); it never touches a broker stop.
- **Drawers**: Broker reconciliation (paper account `tradeai_automated` only, latest run), Write-offs, Small
  positions, Protection advisory (labelled paper account only), Excluded rows, How this page works.
- The time-exit widget (`TimeExitProposals`) is no longer rendered. The component files
  `OpenTradesIntelligence.tsx` and `TimeExitProposals.tsx` are left in place, unused.
- The hub header open count reads `summary.active_positions` from the intelligence endpoint, not
  `paper_trades`.

## Open Trades intelligence accuracy (`scripts/open_trades_intelligence.py`)

Each rule is pinned by `tests/test_open_trades_accuracy_20261022.py` (gate `open_trades_accuracy_20261022`).

1. **Mark = `canonical_mark` with its own time**: `canonical_mark_as_of`, else `canonical_mark_ingested_at`,
   else the row's update time. The holdings `price` alias is used only when a row has no canonical or current
   mark. Rows without a holdings mark (paper) use the `market_quotes` row.
2. **One quote source per row**: mark, day move and time come from the same source; the row says which
   (`quote_source`).
3. **P/L = shares × mark − cost basis** (`market_value` = shares × mark). The broker's cached `gain_loss` is
   not used.
4. **Day move hidden when stale**: a mark older than `PRICE_STALE_HOURS` (18 h) or with no time sets
   `mark_stale` and `today_move_pct = null`.
5. **Times compared as datetimes**: `last_price_update` / `oldest_price_update` are computed from parsed
   datetimes (naive values are host-local Eastern), not a string max over mixed naive and UTC values.
6. **Stop proximity from the row's mark**: `stop_distance_pct`, and `stop_near` within 2%.
7. **Write-offs out of the headline**: a worthless or delisted ticker (`worthless`) is excluded from
   `total_unrealized_pnl` and `active_positions` and listed in `write_offs[]`
   (`write_off_unrealized_pnl`).
8. **No "large gain unprotected" for funds or small positions**: never raised for a fund that cannot take a
   stop order (`holding_family.is_unstoppable_fund`) or a non-paper position under `SMALL_POSITION_USD`
   ($500); a small position is also never "Needs protection review".
9. **Account labels from `broker_accounts.display_name`** (`account_label`, `summary.account_labels`), with
   the holdings-key aliases `schwab_roth → schwab_roth_ira`, `alpaca_paper → tradeai_automated`.

New response fields: per row `quote_source`, `mark_as_of`, `mark_age_hours`, `mark_stale`,
`stop_distance_pct`, `small_position`, `write_off_pnl`, `account_label`; summary `active_positions`,
`oldest_price_update`, `stale_price_count`, `price_stale_after_hours`, `write_off_count`,
`write_off_unrealized_pnl`, `total_unrealized_pnl_excludes`, `unpriced_basis_count`, `small_position_count`,
`small_position_usd`, `account_labels`; top level `write_offs`. Existing fields keep their names.

## Watchlist and directive membership (`watchlist_state`, fixed 2026-10-22)

Root cause: the membership lookup in `build_intelligence()` called `_db_query`, which the module never
defined; the `NameError` was swallowed, so every row read `watchlist_state: none`. Now
`_watch_membership()` reads through the Watch data broker, not SQL in this file:
`lib.data_broker.watch_domains.membership_watchlist` (watchlist_items, status active/researched — the one
membership list) and `lib.data_broker.watch_intelligence.active_ticker_directives(strict=True)` (the
watch_directives projection owner per `config/data_source_authority.json`). Both raise on a DB error, so a
failed lookup is logged and every row reports `watchlist_state` and `directive_state` = `unavailable` (never
`none`); `summary.watch_membership` is `ok` or `unavailable`. The UI treats `unavailable` like `none` (no
tag). Pinned by `tests/test_open_trades_watchlist_state_20261022.py` (gate
`open_trades_watchlist_state_20261022`).

## Triage chips

`tradingCommandTriage.ts`: the near-stop chip's samples now come from the `stop_near` flag (it filtered on
`near_stop`, which the endpoint never emits, and fell back to the first positions — names with no stop). The
unprotected chip skips funds that cannot take a stop, small positions and write-offs.

## Known gaps

- The intelligence endpoint still reads `holdings.json` directly (allowlisted in
  `tests/fixtures/holdings_json_direct_readers_allowlist_20261005.txt`); moving it to the positions projection
  is a §26 migration step, not part of this change.
