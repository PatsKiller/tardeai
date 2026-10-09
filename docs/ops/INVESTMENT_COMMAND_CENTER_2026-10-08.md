# Investment Command Center — PR-A: engine, CIO memory, ranking, filters, modal, Telegram line (2026-10-08)

Your request (/plan, 2026-10-08): the dashboard should evolve from an alerting system into an Investment Command
Center:
- **One modal per ticker**, with:
  - market data and technicals, with a chart;
  - Street targets and upside;
  - a risk/reward ladder;
  - portfolio context and a stance;
  - a 0–100 conviction score built from six factors;
  - an AI summary.
- **A ranking engine with global filters**, so 500+ opportunities can be narrowed to the top 5 in under 30 seconds.
- **All curated data persisted in CIO memory.**

Additions made during the build:
- "Make sure these changes resonate in telegram alerts also."
- "Do we need LLM every night?" The answer is no: PR-B briefs are change-driven (see Plan).

## What ships in PR-A

| Piece | Where |
|---|---|
| Rules: weights, thresholds, types, conditions, stance, presets, material change, Telegram | `config/opportunity_conviction.yaml` |
| Engine (pure + batched gather) | `scripts/lib/data_broker/opportunity.py` |
| New readers | `price_stats.py` (52-week range, 1W/1M change, SMA20/50/200, average volume, RVOL from ticker_prices + market_ohlcv_bars), `ohlc_bars.py` (daily candles), `entry_plan.get_entry_ladders` (T1–T3, prices only), `positions_context.py` |
| Bug fix | `analyst_rollup.get_analyst_rollup` returned `{}` for every caller: the pills file is a list. The Watch street-rating gap-fill from pills now works, carrying its `as_of`. |
| CIO memory | `scripts/lib/cio_opportunity_store.py`: `data/cio/cio_opportunity_assessments.jsonl` holds the version history (a version only on material change); `cio_opportunity_projection.json` holds the latest ranking. Registered as a CIO intelligence-fabric producer and the `opportunity_assessment` authority domain. |
| Curator (deterministic, zero LLM, zero provider calls) | `scripts/cio_opportunity_curator.py`, lane `cio-opportunity-curator`, every 30 minutes 09:00–16:30 ET on weekdays. Needs a cron grant. |
| API | `GET /api/v3/opportunities` (presets, filters, sorts, facets) and `GET /api/v3/opportunities/{symbol}` (curated assessment plus a live overlay, candles, CIO thesis, version history) |
| UI | Watch → **Opportunities** tab (ranking table, presets, global filters); the **Investment Opportunity modal** (`components/opportunity/*`, `primitives/Modal.tsx`); the **Home "Top opportunities"** widget. Clicking a ticker opens the modal from Watch cards, the decision board, Communications and the Re-entry desk. `?opp=SYMBOL` opens it from a link. |
| Telegram | `scripts/lib/opportunity_alert.enrich`, called at the single chokepoint `telegram_alert.send_telegram`. Entry, re-entry, reward, risk and watchlist alerts that name a curated symbol gain one line: `🧭 Conviction 71/100 · #237 of 1,332 · R:R 4.1x · Upside +34% · ADD — Open in Command Center`. It is read-only, idempotent, skipped when the projection is over 26 hours old, and never raises. |

## Engine rules (summary)

- **Risk/reward:**
  - Entry is the plan's suggested entry, otherwise the zone midpoint, otherwise the strategy card's ideal entry,
    otherwise the current price.
  - The invalidation level is the plan's, otherwise the strategy card's, otherwise 2×ATR below entry.
  - T1–T3 come from the plan's exit ladder, otherwise the plan or strategy target, otherwise the Street mean and
    high.
  - **R:R uses the primary target.** Plan ladders set T1 at +1R, so measuring to T1 would make every planned R:R
    exactly 1.0.
  - R:R is flagged and not scored when risk is under 1% or R:R is above 15×.
  - Mechanical levels count for less than a real plan: strategy card 0.75, ATR and analyst 0.6.
- **Factors:**
  - **Technical:** Hermes momentum and setup quality, otherwise MA alignment adjusted by RSI.
  - **Fundamental:** fundamental_data (sparse, about 14 names).
  - **Analyst:** recommendation mean and upside. Dropped when fewer than 3 analysts cover the name or the upside is
    over 150%, which is flagged.
  - **Momentum:** 1-week and 1-month change, plus relative volume.
  - **Risk/Reward:** from R:R, weighted by level trust.
  - **Portfolio Fit:** position weight and sector concentration.
- **Conviction** is the weighted mean of the factors present. Missing factors are re-weighted away, and `coverage`
  shows how much of the score rests on real inputs.
- **Type and stance:**
  - **EXIT** needs conviction ≤35 *and* coverage ≥0.8, so an income ETF with no analyst data never shows EXIT.
  - **TRIM** applies when the position is ≥12% of the book.
  - **ADD** needs conviction ≥70 and R:R ≥2, the same bar as the Add-On type.
  - The prose is conditional and passes `execution_language.find_imperative`.
- **MBI_BEHAVIOR = 0.** No behaviour key is ever stored. The store refuses `stop`, `limit`, `shares` and the rest
  at any depth.

## Measured on live data (worktree dry run, 2026-10-08 ~09:00 ET)

- **Universe and runtime:** 1,412 names, 1,332 rankable, 1,359 with R:R. One full pass takes 5–8.5 seconds.
- **Factor coverage:** technical 1,402, momentum 1,324, risk/reward 1,279, analyst 581, fundamental 14, portfolio
  fit 1,412.
- **Top-5 preset:** conviction ≥80, R:R ≥2, coverage ≥0.8. 21 names qualify, and the query answers in 0.04 seconds.
- **NFLX detail** (1.35 seconds):
  - support 66.72 / 64.75 and resistance 70.48 / 72.27; trend bearish; SMA200 83.13;
  - 45 analysts, mean target $93.66 (+34%);
  - ladder T1 73.30 / T2 83.60 (primary) / T3 93.66, at R:R 4.1×;
  - position 400 shares at $68.22;
  - stance ADD (conviction 71).

## Known gaps

- **Realized gain/loss and days held show as "pending".** Their authority is positions_store (`realized_lots` and
  `position_lots`, which reproduce the broker), and that store is SHADOW until you approve the phase-3 reader batch.
  A FIFO over trade_transactions was tried and rejected: it crossed SCHD's split and transfers and showed +$138,787
  realized.
- **Fundamental scores are sparse.** `fundamental_data` covers about 21 symbols.
- **Analyst targets can be stale.** The pills file carries 2026-08 Yahoo data for some names; the modal shows the
  `as_of` and flags stale or implausible targets.

## PR-B (next)

- **AI briefs:**
  - DeepSeek Flash lane `cio_investment_brief`, with grounding enforced and both execution guards.
  - Written into the CIO symbol thesis, carrying the prior fields forward.
  - Change-driven: a brief is written only when the top ~150 or a held name gets a new material-change version
    since its last brief, or the brief has passed its TTL. Expect roughly 10–40 a night, under $0.50.
  - Generated on open for anything else.
- **Click-any-ticker** across the remaining pages.
- **Optional n8n coordination:** brief-refresh events, nightly fan-out, and curator staleness raised as a
  Communications event.

## Company, catalysts and news in the modal (2026-10-08, later)

Your feedback: "nothing here on what company does or latest news, catalyst".

**What the modal now shows:**
- **About:** the `symbol_profiles` business description (3,332 of 3,334 symbols have one) and the next earnings date.
- **Catalysts:** typed `catalyst_events` from the last 90 days, newest first. Untyped `other` rows are excluded.
  Each row shows its type, headline, date and a low-confidence flag. A scheduled earnings date appears as an
  upcoming catalyst.
- **Latest news:** `news_articles` from the last 45 days. Same-headline duplicates across feeds collapse to one, and
  headlines already shown as a catalyst are left out.

The readers are `catalyst_record.get_symbol_news`, `get_symbol_catalysts` and `title_key`. Windows and limits are
set under `modal:` in `config/opportunity_conviction.yaml`.

**Why the top names had no news:** the weekday `news_ingestion.py --priority` run is capped at 60 symbols. That cap
fills with proposals, holdings and the watchlist, so the CIO's ranked names never got fetched. AOSL, rank #1, had zero
articles in 90 days.

**The fix:** `news_lane.top_n`, 25 by default, adds the top-ranked names from the CIO projection as an extra lane on
top of the cap. It uses free RSS providers only and runs twice a day (12:30 and 00:30 ET). To roll back, set
`news_lane.enabled: false`.

**Why some About texts were one-liners ("Ceva Inc — Semiconductors."):** 1,074 profiles held a stub that
Finviz synthesizes when the yfinance lookup comes back empty. A stub counted as fresh for 30 days, so it was never
retried, and ranked names were not in the profile job's universe at all.

**The fix:** `profile_lane` in the same config. `build_symbol_profiles.py` now also covers the CIO's top 150 ranked
names. A stub is retried after 7 days, at most 150 per run, best-ranked first. The existing weekday 06:45 and Sunday
19:00 runs pick this up, so no crontab change is needed. The dry run selected 202 symbols, including the stubs GDS,
DNA and QTEX; nothing was written.

**Also fixed in the modal:**
- The CIO summary no longer cuts off mid-word, and has a "more" toggle.
- A "none" consensus now shows "—".
- Earnings dates now show the correct day in ET.
