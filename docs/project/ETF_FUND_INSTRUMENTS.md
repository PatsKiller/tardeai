# ETFs & Funds as first-class instruments

**Status:** Active (shipped 2026-06-18)
**Gap closed:** discovery/research/proposals/rotations surfaced only individual stocks. ETFs and funds — the
natural way to fill an underweight sleeve (Defense → ITA/XAR, Energy → XLE) or hedge an overweight one
(Nasdaq → PSQ) — were invisible, and there was no instrument-type or long/short concept anywhere.

## Instrument typing

- `scripts/classify_instruments.py` (weekly cron Sat 06:30) gives every symbol an `instrument_type`
  (`stock | etf | fund | inverse_etf`) + `direction_hint`, persisted to `symbol_profiles`. Sources, in
  order: the curated `config/etf_fund_universe.json` → sector/description heuristics → mutual-fund code
  heuristic (5-letter ending in X) → **yfinance `quoteType`** (authoritative — ETF/MUTUALFUND/EQUITY; this
  catches any ETF/fund flowing through, not just the curated set; found 32 ETFs vs 24 by heuristic alone).
- **Expense ratio** captured from yfinance (`netExpenseRatio`/`annualReportExpenseRatio`, normalized to a
  fraction since yfinance is inconsistent) → `symbol_profiles.expense_ratio`. E.g. SCHD 0.06%, SPY 0.094%,
  SQQQ 0.95%.

## Analyst view for baskets

ETFs/funds don't get sell-side price targets (analysts cover companies, not baskets), so
`scripts/etf_analyst_enrich.py` (weekly cron Sat 07:00) produces an honest **holdings look-through**: it
pulls each ETF's top holdings + weights (yfinance `funds_data`), fetches the constituents' analyst targets,
and computes the **holdings-weighted average analyst upside** (requires ≥2 covered constituents, else
omitted — a 1-stock "look-through" isn't a basket view). Stored in `symbol_profiles.analyst_look_through_pct`
+ `analyst_basis`. E.g. ITA +12.8% (4 constituents), PPA +12.1%, SOXX +12.9%. Surfaced as the card's analyst
block (`rating: "look-through"`).

## Curated sleeve universe

`config/etf_fund_universe.json` maps ETFs/funds to the rotation sleeves (`config/rotation_sector_targets.json`
themes) with a `direction`: long ETFs (sector/broad/thematic/income/bond) + `inverse_etf` shorts
(SH/PSQ/SQQQ/SARK/…). This is what lets an underweight sleeve surface its long ETF and an overweight sleeve
surface an inverse hedge.

## Wired into rotation, research, UI

- **Rotation summary** (`/api/v2/rotation/summary`) returns `etf_candidates`: a **LONG** ETF for each
  underweight sleeve (ITA/XAR Defense, XLE/XOP Energy) and an **INVERSE/SHORT** hedge for each overweight
  sleeve (SARK for AI mega-cap, PSQ for Nasdaq 100), each with price, instrument type, expense, rationale.
- **Research candidates** carry `instrument_type`; the card layer exposes `instrument_type`, `expense_ratio`,
  and the look-through analyst.
- **Research seeding** (`/api/v2/rotation/research-gaps`) now seeds the sleeve ETFs as `watch_directives` so
  TradeAI + Hermes research baskets too — not just stocks.
- **UI** (`/v3/rotation`): an **ETF / Fund Sleeve Plays** section (LONG/SHORT tags, instrument badges,
  expense, price) + instrument badges on research candidates.

## Long / short

`direction` flows end-to-end: long ETFs (own it) vs `inverse_etf` shorts (own the inverse, which is short
exposure). The rotation engine surfaces shorts only as **advisory hedges** for overweight sleeves — review
only, nothing is placed.

## Roadmap

- Full-market ETF reference (currently a curated sleeve universe + any ETF that enters the system via
  quoteType; a ~3,000-ETF reference feed would enable thematic ETF *discovery* beyond the curated set).
- Broader constituent analyst coverage so more ETFs get a look-through (today limited to ETFs whose top
  holdings already have analyst targets in the system).
- ETF/short proposals in `auto_proposal_generator` (the proposal model would need an `instrument_type` +
  `side` column; rotations already carry direction).
