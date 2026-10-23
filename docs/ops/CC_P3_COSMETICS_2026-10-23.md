# Command Center v3 — P3 cosmetic fixes from the site validation (2026-10-23)

```
Status:      PR-OPEN (branch feat/cc-p3-cosmetics-20261023)
as_of:       2026-10-23T12:30:00-04:00
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0 · presentation only (no API, broker, Telegram or DB effect)
Approval:    operator, 2026-10-23 ~11:25 ET, "I approved" — the P3 mockups in ~/.cache/rtc/site-crawl/mockups/P3_MOCKUPS.html
Source:      docs/ops/SITE_VALIDATION_2026-10-23_53aa1b619.md §4.3 (PR #2015)
Tests:       src/lib/asOfDisplay.test.ts, src/lib/displayLabels.test.ts, src/lib/tradingDeepLink.test.ts (in npm run build);
             scripts/test_metric_strip_labels.mjs (updated); e2e/p3-cosmetics.spec.ts (mocked API, 1440 + 412 px)
```

The site validation listed seven P3 (cosmetic) items: five visual mockups and two text items. The operator approved all of
them. This change builds six of them. The seventh was already covered by an open PR (see "Not in this PR").

## What changed

| # | Surface | Before | After | Where |
|---|---|---|---|---|
| 1 | Header **TRADING** tile | At 1440 px the value was cut to `47.9% win · 238 trades · $…`, which hid the P&L the tile exists to show. The price stamp read `Prices 16:45 ET · Finviz after-hours 12/12 sy…`, and the VIX line read `trade_ai_run_summary · 02:21` (a UTC clock). | The value is `47.9% win · 238 · $25,505 P&L` and wraps to at most two lines inside the tile. The price stamp is `Prices 16:45 ET · after-hours · 12/12`. The VIX line is `scanner · 17:30 run`. The full text of all three is in the tooltip (TRADING: `47.9% win rate · 238 trades · $25,505 P&L`). | `MetricStrip.tsx`, `lib/displayLabels.ts` (`tradingTileValue`, `shortPriceStamp`, `vixProvenance`) |
| 2 | **Rotation advisory** withheld notice (Portfolio, Intelligence, Rotation → Review) | The notice was the largest text on the page, written as sentences, with raw ISO stamps in microseconds and UTC. | One amber line: `Rotation advisory withheld`, then the reasons as chips (`account data stale`, `position evidence stale`, `stop claim unsupported`), then `Source as of Oct 22 (date only) · checked Oct 23 08:09 ET`. The sentences, the raw stamps and the reason codes are in the tooltip. When the advisory is READY (Rotation → Review) the line is neutral, not amber. | `RotationPublicationNotice.tsx`, `lib/rotationPublication.ts` (`rotationReasonChips`) |
| 3 | **Active Trader** KPI captions | `.at-kpi span` was nowrap + ellipsis, so captions were cut (`TRIGGERED + back-in…`). | Captions wrap. | `pages/activeTrader.css` |
| 4 | **Strategy → Leaderboard** and the snapshot list | Raw identifiers: `fib_retracement_bounce`, `maintain_current`, `review_risk_reward`. | Human labels (`Fib Retracement Bounce`, `Pullback MACD Reversal`, `Review Risk Reward`). The identifier is in the tooltip and in `data-strategy-id`. Known acronyms (MACD, REIT, VWAP …) stay upper-case. | `StrategyHub.tsx`, `lib/displayLabels.ts` (`humanizeIdentifier`) |
| 6 | Legacy Trading `?tab=` URLs | `?tab=Entry Desk`, `Manual ToS`, `Broker Recon`, `Schwab Accounts` and `Broker Proposals` opened the right desk, but the retired name stayed in the address bar, so copied links carried it forward. | Before the desk mounts, the hub rewrites them to the canonical URL with a history **replace**: `?tab=Proposals&section=path-a`, `?tab=Open+Trades&drawer=recon`, `?tab=Broker+Orders&section=schwab-accounts`, `?tab=Proposals`. Other keys (symbol, proposal, `pq_*`, hash) are kept. Case and `+` variants are normalised too. | `lib/tradingDeepLink.ts` (`canonicalTradingSearch`), `TradingHub.tsx` |
| 7 | **Date-only `as_of`** values | A date-only value widened by its producer to `2026-10-22T00:00:00+00:00` rendered as UTC midnight, which is 20:00 ET the day before. | Shown as a date: `Oct 22 (date only)`. | `lib/asOfDisplay.ts` (`dateOnlyPart`, `fmtAsOf`), used by the rotation notice, by `fmtDeskTimestamp` (shared desk formatter) and by the header tile meta line |

### The date-only rule

A value is **date-only** when it is a bare `YYYY-MM-DD`, or a stamp at exactly `00:00:00(.000…)` UTC (`Z` or `+00:00`).
A date-only value is shown as `Mon D (date only)` and is never converted to a zone. Every other zoned stamp is shown in ET.
An unzoned stamp is shown as published, because converting it would mean assuming a zone.

Known edge: a real observation at exactly 20:00:00.000 EDT is 00:00:00 UTC, so it would read as date-only. Producers stamp
with seconds and microseconds, so a whole-second UTC midnight is in practice always a widened date. The raw value always
stays in the tooltip or the drill.

The producer side is **not** changed here. Schwab account `source_as_of` is still widened to UTC midnight. That is item 18
of the site validation, with the publication-gate owner. This PR only stops the UI from inventing a clock.

### Header geometry

The TRADING value is the only line in the header that may wrap. It is clamped at two lines (`VALUE_WRAP`,
`-webkit-line-clamp: 2`), so the strip height stays bounded. Every other line stays nowrap + ellipsis.
`scripts/test_metric_strip_labels.mjs` now asserts that exactly one tile sets `wrapValue`. Coverage stays on the price
stamp's face, as a bare `12/12` ratio, because the operator pinned it visible even when quotes are healthy.

## Not in this PR

- **Item 5, Trade AI tiles name their population.** This is covered by open PR **#1990**. Its GO, WAIT and Manual review
  tile hints read `today's universe · N rows`, and their tooltip says the header counts the latest run only. Building it
  here as well would have conflicted in `tradeAiOpportunities.ts` and `TradeAiOpportunities.tsx`. If #1990 is dropped,
  the approved wording ("whole scanner universe (not the latest run)") belongs in `buildTiles`.
- The producer fix for the date-only Schwab `source_as_of` (above).

## Evidence

- `npm run build` passes. It runs `asOfDisplay` (23 checks), `displayLabels` (30), `tradingDeepLink` (53, 12 of them new)
  and `metric_strip_header_truth` (50).
- `e2e/p3-cosmetics.spec.ts` was run against a hermetic static server: 10/10 pass on this branch, and 10/10 fail on
  origin/main `80e93c99f`. The server has no proxy, and every `/api/**` call is mocked. The neighbouring specs
  (`trading-tabs-open-trades`, `active-trader-alerts`, `run_health_agreement`, `scheduler-operations`,
  `trade-ai-opportunities`) pass 22/22.
- Before and after screenshots at 1440 px and 412 px are in `~/.cache/rtc/p3ui/`, with `shots.json`. They were rendered
  from the site-crawl captured JSON, read locally. No request reached the live server: the leak counter was 0, and the
  static server logged 0 unmocked API calls.
