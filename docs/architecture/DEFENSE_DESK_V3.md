# Defense Desk v3 — Recommendations First · W/M/Q Rotation · Dashboard (2026-07-18)

Status:      ACTIVE
as_of:       2026-07-18T10:11:36-04:00
Measured at: efcc51365 / not measured

Session 3. The cut line INVERTED: WS-R (recommendations) shipped first, design painted
after. Operator verdict on v2 was 1/10 — no recommendations, text too small, colors
regressed, no month/quarter view. v3 answers each, graded at the bottom against the
operator's definition: *a 10 tells me what to do, in which account, and why.*

## WS-R — the recommendations engine (`defense_recommendations.py`, nightly 17:50)
Four groups, every card **complete-or-absent** (12 required fields — instrument,
accounts, direction, size band, entry logic, invalidation, factors-with-values, as-of,
SHADOW/LIVE — field guard unit-tested in `test_defense_recommendations.py`; dropped
cards listed in the payload, never silently missing).

- **R3 Get-Into**: LEADING/IMPROVING sectors underweight vs the neutral map
  (`config/defense_recommendations.json`, equal-weight default, floor 4%): sector ETF
  always + top-2 Hermes-composite constituents passing rails (≥$20M dollar-vol, not
  >12% above 50DMA, no earnings ≤7d). Live day one: Healthcare/Energy/Financials/
  Consumer Staples (book weight ~0% in each).
- **R2 Protect (move-out)**: ≥3 fired factors with values (sector state, <200DMA,
  <50DMA, Hermes 5d slide, RSI<40, sector negatives), tax-gated per account, 10-day
  SHADOW from 2026-07-18 — on-page immediately, Telegram only after promote.
- **R4a Inverse-ETF**: trigger = >10%-book sector WEAKENING/LAGGING or ≥4 sectors
  LAGGING; PSQ when tech-led (QQQ rs20 < −2) else SH; decay warning on every card;
  exit = trigger state exits (2-close).
- **R4b Taxable shorts**: confirmed-LAGGING industry pool → <200DMA & <50DMA, short
  float <10% (anti-squeeze, as-of dated), ≥$25M dollar-vol, ≥$10 price, stop ≤10%
  away, no earnings ≤7d, **NEVER a held symbol**; mandatory buy-stop ~3% above 20DMA,
  max-loss shown, ≤2% of taxable book. Live: KTOS, ACN, GDS.
- **R4d Covered calls**: ≥100-share holdings in WEAKENING/LAGGING sectors →
  21–45 DTE, 0.20–0.30 delta, premium-honesty line. Live: CSCO/ANET/XLI/SPCX.
- **Put structures**: render LOCKED ("unlocks when options level confirmed — fill
  config") — never omitted silently.
- **Paper twins**: short-side cards insert PENDING `paper_trade_proposals`
  (defensive_short / inverse_etf_hedge, $2K, 72h expiry, ≤3 concurrent, dedup) —
  the scoreboard accrues regardless of what the operator does in real money.

## R1 — hedging radar (`options_chain_snapshot.py`, nightly 17:35)
Read-only chains (existing `get_option_chain` fence, strike_count 8) over sector ETFs
+ SPY/QQQ + top-10 holdings — 20/21 covered day one (DIVI has no chain), coverage
stated in-payload. Aggregates only: put/call OI + volume, ATM IV, ~25Δ skew →
`option_chain_snapshots` table. OI deltas vs prior snapshot and P/C-vs-20d-mean accrue
as history builds (n stated). Plain-sentence read per row; labeled positioning
INFERENCE, never order flow. Served with the recommendations at
`/api/v2/defense/recommendations`.

## WS-T — W/M/Q boards
Sectors rank by RS5/RS20/RS60 (already computed nightly); industries by rel1w/rel1m/
rel1q (perf_quarter − SPY 60d client-side; `industry_momentum_state` carries the
perf columns — the prompt's `industry_performance` table never existed). Movement
chips = rank at this timeframe vs the next-longer one (W↔M, M↔Q, Q↔M); one
what-changed line per board. The scatter shares the toggle, plots FULL sector names
(operator request), and fits axes to data so no dot clamps at an edge.

## WS-D3 — dashboard, not data dump
- **DASH scale** in watchTokens (house rule): data 12 · rows 12.5 · section 14 ·
  panel 16 · verdict 22 · chips 10 CAPS only. 7/8/9px banned.
- **Design guard** `scripts/check_design_tokens.sh` — runs inside `npm run build`:
  per-file raw-hex + sub-10px counts may never exceed `config/design_token_baseline.json`
  (197 legacy files frozen — HomeHub alone carries 112; all defense surfaces at 0; new
  files start at 0). Proven blocking a synthetic violation. Three sweeps, three
  regressions — ended by machine.
- **Hierarchy**: Row 1 verdict (22px state line + net exposure / hedges active-advised /
  transitions / VIX) · Row 2 recommendations rail (tabs All·Rollover·Roth·Taxable —
  tabs derive from the capabilities config; there is NO 401k account, it rolled into
  the Rollover IRA 2026-06) · Row 3 rotation (scatter + two boards) · Row 4 collapsed
  folds (radar, spine+drill, whf, build status). Everything reachable in one click.

## Gotchas (new in v3)
- `ticker_enrichment_cache.json` has NO price field — prices come from ticker_prices.
- `git checkout <uncommitted-rewrite>` restored HEAD and destroyed the v3 hub once —
  commit-first before using checkout to clean scratch edits.
- Cron `cd` missed a SIXTH time (17:35 radar entry).
- First-day rails caught real garbage: LDOS advised as short while HELD (held-symbol
  exclusion added), MNTS $4.87 with a 32%-away stop (min_price + max-stop-distance
  added; its paper twin was cancelled with reason).

## Maturity self-score: 6.5/10 (operator scale: "a 10 tells me what to do, in which
account, and why")
What earns it: every group answers do-what/which-account/why with values, per-account
tabs filter correctly, shorts/inverse/CC/rotate-in all live from real state, radar
answers "where are the options hedging."
What caps it: OI deltas and P/C means need ~2 weeks of snapshots to mean anything;
move-out is in a 10-day shadow (unproven); paper-twin scoreboard has zero closed
trades; put structures locked on operator config; constituent picks lean on Hermes
composite which has no defense-specific validation yet. The path from 6.5 → 8 is
letting the shadows and history accrue, then promote; → 10 needs the options level
filled and a proven twin track record.
