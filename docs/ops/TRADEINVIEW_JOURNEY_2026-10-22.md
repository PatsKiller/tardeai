# TradeInView — the per-trade journey (2026-10-22)

```
Status:      BUILT (branch feat/tradeinview-journey-20261022). Read-only page + projection; no migration, no lane, no writer.
as_of:       2026-10-22T17:00:00-04:00
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0 · no broker code, no broker call, no order / 2FA path
Tests:       tests/test_trade_journey_20261022.py (gate trade_journey_20261022);
             CC-v3 node test src/lib/tradeJourneyModel.test.ts (in `npm run build`);
             e2e apps/command-center-v3/e2e/trade-journey.spec.ts (NAVN fixture)
```

Operator, 2026-10-22, verbatim: *"navn was one of the top picks with the highest conviction. I got into it a few days
ago. I got stopped out today. I want to make sure that the trade and view actually tracks where that stock came from. I
didn't pick it on my own. It came from internal. It examines the ups and downs and what was the cause of getting out and
advises me on when to get back in. All on the same data backend. Not a separate work stream."*

## What the page is

`/v3/journal` (nav **TradeInView**) opens on **trade journeys**, in the Gate 3 mockup design (freshness chips, one
table, a detail panel, drawers). The previous journal (analytics, tagging queue, costs, import, …) is one click away as
**Classic journal** (`?view=classic`); every legacy link that names a tab (`?tab=Options`, the StrategyHub /
AI-critique `journal_tab` hand-off) opens it unchanged.

| Part | What it shows | From |
|---|---|---|
| Freshness chips | Fills · Holdings · Stops · CIO · Re-entry desk · Origin links · Record (interim or CIO store) — each with its age and a tooltip naming its store | the payload's `freshness[]` |
| Filters | All · Needs a look · Open · Closed · From internal · Your picks | `?filter=` |
| Table (one) | symbol, **origin badge** (`INTERNAL · Home #4 · 86` / `YOUR PICK` / `ORIGIN ?`), account, entry, exit or mark, P/L, why it ended, conflicts | `journeys[]` |
| Detail panel | where it came from (label + evidence lines), tiles, **price band** (daily candles, entry / stop steps / exit lines, re-entry zone, high/low dots, held span), **timeline** (origin → entry fill → each stop level → CIO conviction / stance / rank changes → exit fill + cause), conflicts, **post-exit review** (facts first; model note labelled ADVISORY with its model), **When to get back in** (desk state, zone, invalidation, target, reclaim-the-exit reference, distance, conditions met, **Set alert…**, Open in Watch) | `journeys[i]` + `GET …/trade-journeys/{trade_id}` for the bars |
| Drawers | Conflicts (shown, not resolved) · Data gaps · How this page works | payload |

**Set alert** opens the existing `ReEntryAlertArmModal` (POST `/api/v2/watch/alerts`, advisory notification, note tag
`tradeinview-reentry`). It is the only write the page can cause. Nothing sizes, places, moves or cancels an order.

`?symbol=NAVN` (Open Trades and Watch deep links) selects that symbol's most recent journey; `?trade=<trade_id>` selects
one trade.

## One record — the projection (AGENTS.md §26.3)

`GET /api/v3/data-broker/trade-journeys[?days=30&symbol=X]` and `GET /api/v3/data-broker/trade-journeys/{trade_id}` →
`scripts/lib/data_broker/trade_journey.py` (catalog id `trade_journey`, contract `TradeJourneys@v1`, row
`TradeJourney@v1`). Read-only SELECTs and file reads, zero provider calls, no writes (a test fakes the DB and fails on
any non-SELECT).

* **When the CIO prospect store is live** (`lib.data_broker.cio_prospect.get_prospects` returns `source.kind == "store"`),
  every journey takes the prospect's `stage`, `conviction`, `stance` and `conflicts`, and — when the prospect record
  carries them — its own `origin`, `lifecycle_events`, `exit_review` and `re_entry` blocks (`from_cio_prospect`). A
  shadow build is not read (switching a surface onto it is §17). Prospect conflicts are added to the journey's own,
  never merged away.
* **Until then, an interim adapter** builds the identical shape and labels the page
  `interim — CIO prospect store not live`:

| Field | Interim source |
|---|---|
| closed trades | `schwab_round_trips` (canary excluded), last `days` |
| open trades | `lib.portfolio_positions.load_store` (holdings_accounts, the one accessor) + `latest_quote` projection mark; entry fill = `trade_transactions` buys after the last sell |
| origin | `trade_recommendation_links` + `recommendation_registry` (learning loop PR1) when present; else the CIO opportunity version in force at the entry (`cio_opportunity_assessments.jsonl` via `CIOOpportunityStore`: rank on Home, conviction, stance) + the latest CIO `BUY_READY` / `ENTRY_NEAR` in `cio_entry_states` within 10 days before the entry |
| stop path | `stop_last_known` (one durable row per observed stop order; `stop_lifecycle` is rebuilt every scan) |
| conviction / stance changes | the opportunity history versions and `cio_entry_states` transitions between entry and exit |
| price band | `ohlc_bars` projection (`market_ohlcv_bars` daily; `ticker_prices` closes fallback) |
| re-entry | the re-entry desk snapshot `data/runtime/reentry_decision_desk_latest.json` — **the same record Watch "Re-entry near" reads** (written by `reentry_decision_desk.build_decision_desk`; the page never recomputes the desk) |
| advisory note | `ui_prefs` `portfolio.reentry.llm_insights.v1` (`:quality` rows), labelled advisory |

### Reading the cio_prospect record (PR #1944)

PR #1944 (`feat/cio-prospect-p0-p1-20261022`) puts the position lifecycle on the same record
(`scripts/lib/cio_prospect_lifecycle.py`): `origin` (`classification`, `summary`, `linkage`, `at_entry.surfaces`),
`position_lifecycle` (fills, `observed_stops`, `excursion`, `exit_cause.class`, `pnl`), `post_exit_review` (`facts`,
`noise_vs_trend`, `prose` — null until a registered capability exists), `reentry_advice` (Re-Entry Decision Desk
classifier: `state`, `conditions`, `levels`, `alert_levels`), `stage_phase` and the append-only `lifecycle_events`.
`from_cio_prospect` maps those blocks into this page's row shape (tested against a record in that shape), only when the
record's `position_lifecycle.round_trip_key` is this row's round trip; what the record does not carry (the price band,
the desk's invalidation and target, the alert seed) keeps the interim value. Exit classes map 1:1
(`manual_sell` → manual, `unknown_no_stop_history` → unknown); conflicts (`values[2]`, `note`) keep both sides.

The interim rules were aligned with that module so the page does not change words when the store goes live: the same
origin label (`Home #4 · conviction 86 · CIO BUY_READY 10-16`), the same exit classes, and the same close-basis
noise-or-trend-break rule. One difference, kept on purpose and stated: an exit **below** the last stop (a stop-market
gapping through) is a stop-out here; the lifecycle rule (within 0.5 % of the stop) calls it a manual sell. When #1944
merges, the interim adapter should call its pure functions instead of these (one classifier, §13.5) — follow-up.

## The rules (deterministic, tested)

* **Origin is never guessed.** INTERNAL needs a recorded link, an opportunity version in force at the entry, or a CIO
  entry call in the 10 days before. YOUR PICK needs the linker's `operator_initiated`. Otherwise ORIGIN ? with why.
  The origin is what was in force **at the entry** — a later rank (NAVN #1 on 10-22) is a change shown in the timeline,
  not the origin.
* **An open position whose buy is not in the ledger** (`approximate_entries`) gets an entry time from the earliest of
  the first stop observed on that position and just before the first CIO opportunity version that marks it owned. The
  row says so (`entry.at_basis`, "(date approximate)" in the timeline, ≈ on the tile) and the origin is looked up at
  that time. Measured 2026-10-22: without it, NAVN (bought 10-19, buy not in the ledger read here) showed
  "Origin unknown".
* **Exit cause** (`classify_exit`): a closed trade's exit within 0.6 % above (or anywhere below) the last observed stop
  is a stop-out; it is a **trailing ratchet** when the stop had been raised at least once ("locked in a gain" only when
  the last stop was at or above the entry); at the plan target (−0.5 %) is a target; no observed stop at all is
  unknown (no stop history); anything else is a manual sell. An open position whose latest mark is at or
  below the working stop is **stop likely filled — not confirmed** (flagged with a conflict until the fill syncs).
* **Review facts first**: entry, exit, return, held, high/low while held (daily bars), share of the run-up kept and the
  giveback from the high, stop path, cause, noise or trend break (exit-day close vs SMA20 / SMA50 and the giveback,
  close-basis), conviction at entry → now. The model note is shown only when stored, under an ADVISORY chip with its
  model, after the facts.
* **Conflicts are shown, never resolved** (§26.5): holdings still show a position whose stop likely filled; the CIO
  still treats a closed trade as owned; the re-entry desk still says CURRENTLY HELD after the exit.

## NAVN, measured 2026-10-22 (read-only)

* Round trip `srt:607228` (journal, read-only capture on #1944's branch): bought **2026-10-19 11:01 ET @ $25.64**,
  sold **2026-10-22 15:59 ET @ $26.02**, net **+$189.73**. Stop read (operator, relayed): 24.31 → 24.59 → 24.70 →
  24.97 → 25.51 → 25.61 → 26.02, all replaced, the last **filled** — so the cause is a **trailing stop (ratchet)** that
  locked in a gain; the order is known, the times were not relayed (the page says "time n/r", never invents one).
* CIO opportunity history: v26 2026-10-16 09:00 ET **#4, conviction 85.6, WATCH** ("conviction 78→86, rank band
  30→4"); v27 2026-10-22 11:30 ET #1, 87.6, ADD, owned. CIO entry state **BUY_READY 2026-10-16 13:40 ET**. So the
  origin at the entry is **Home #4 · conviction 86 · CIO BUY_READY 10-16**, and the move to #1 / ADD — while the stop
  was trailing — shows in the timeline.
* Daily closes: peak 26.625 on 10-21, so the trade kept 39 % of the run-up and gave back 2.27 % from the high, with the
  exit-day close above SMA20 and SMA50 — **noise, trend intact** by the rule above.
* Holdings still listed 500 sh (cost basis $12,820) at 16:30 ET and the CIO book still says ADD · owned: both are shown
  as conflicts until the position store catches up.
* Re-entry desk (16:33 ET): zone $24.80–$25.10, invalidation $23.90, target $30.00, price $26.02 (+3.7 % from the zone),
  state CURRENTLY HELD (holdings not resynced) — a conflict until the next sync.

The NAVN fixture in `tests/test_trade_journey_20261022.py` uses these numbers. Illustrative only: the desk state WAIT
and its criteria (today's row says CURRENTLY HELD), RSI 61 and the stored model note.

## What it cannot see

* Stops the scan never observed (Schwab blind since 2026-10-14 unless an operator level was recorded with
  `scripts/record_last_known_stop.py`): the stop path is then short or empty and the cause falls back to manual/unknown.
* A sell not yet in `trade_transactions` → no closed round trip; the open position plus its stop shows the likely exit.
* Origin links before learning loop PR1's migration is applied: `link_status = unavailable` (chip + gap), origin from
  the CIO history only; open positions are not linked by the PR1 linker (closed round trips only).
* Intraday path: bars are daily; high/low while held are daily highs/lows.

## Operator decisions (§17)

None to merge this page beyond the normal review: it reads existing stores through a registered projection and changes
no ranking. Switching it onto the cio_prospect store is the P3(d) reader batch (Open Trades + Re-entry) of
`docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md` §7. Removing the Classic journal is a later release.
