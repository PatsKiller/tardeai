# Defense Desk v1 — Sector Momentum · Posture · (Hedge/Short foundations) — 2026-07-17

Status:      ACTIVE
as_of:       2026-07-17T23:47:44-04:00
Measured at: efcc51365 / not measured

Commits `c332fd6f..fbfb2598`. Operator intent: "the system doesn't tell me when sector
momentum is changing… tell me what to be careful of and give me short-side plays."
This session shipped the **visibility core (A+E+F) + D1** per the prompt's time-box clause;
B/C/D2-D5 are the next Defense session with every capability pre-verified.
Diagnosis + capability matrix: `docs/_findings/defense_desk_v1_diagnosis_2026-07-17.md`.

## Shipped
- **WS-A** `sector_momentum_engine.py` (nightly 17:25wd): RS 5/20/60 vs SPY from
  ticker_prices (5y depth — no warm-up; DATE-ALIGNED series after the held-ETF repricer-row
  mismatch), slope, breadth (% members >20DMA fail-soft), four quadrants
  (config/sector_momentum.json), Hermes sector pulse (hermes_score_history) + news pressure
  (guarded negatives; sentiment lane currently idle — fail-soft). Persists
  sector_momentum_state. **Transitions only**: 2-close debounce, ≤4 lines/day, severity by
  BOOK weight, Telegram digest. Debounce unit test 6/6. Live day-1: Technology LAGGING
  (RS20 −9.0, breadth 22%), Industrials LAGGING, Energy/Healthcare/Financials LEADING.
- **Would-have-fired** (`--backfill N`, hypothetical, labeled): Tech → LAGGING **Jul 13**;
  debounced alert fires **Jul 14** — 3 sessions before the operator's complaint. Threshold-
  tuning evidence, never a backtest claim.
- **WS-E/F**: `/api/v2/defense/posture` + **Trade → Defense** page (posture spine w/
  expandable sector rows, net-exposure line, whf fold, honest build-status rows for B/C/D)
  + compact Home posture strip linking in.
- **D1** `config/account_capabilities.json`: **Taxable short-stock VERIFIED** (account
  type=MARGIN, buyingPower 2×) — advisories permitted with stop/max-loss/≤2% cap when D4
  ships; IRAs = inverse ETF + covered calls; `options_level` = OPERATOR-FILL (menus degrade
  until filled).

## Deferred to Defense session 2 (all pre-verified viable)
WS-B chains (get_option_chain works through the fence) + short-float chips (fields captured;
persistence/as-of dating to build) · WS-C move-out advisory (+ rotation "not_yet" =
verdict-clarity wait by design — config decision pending) · WS-D2-D5 hedge menus, CC
defensive feed, defensive_short paper strategy, inverse-ETF paper track. Shadow windows for
C and D5 start when they ship (July 30 combined review may slip for them; GG unaffected).

## Gotchas
- Sector book weights are DIRECT sector holdings only — SCHG (~$269K growth fund) shows
  under Growth Equity, so Technology book% understates true tech exposure until the D2
  lookthrough; the page states this on every expanded row.
- News sentiment lane is idle (0 scored negatives in 5d over 3,487 rows) — news-pressure
  column reads 0 until that lane resumes; it colors, never triggers.
- Cron entries need `cd` — caught for the FOURTH time today on this desk's cron.
