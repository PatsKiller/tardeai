# Advisory Desk maturity baseline — 2026-08-12

Status:      HISTORICAL
as_of:       2026-08-12T14:39:24-04:00
Measured at: efcc51365 / not measured

Goal: reach a **4 / 10** operator-facing maturity, using the Morgan Stanley
Full Portfolio Report (`Full_Portfolio_Report_10Aug2026.pdf`) as a **field
template only** (not a data source). This file is the honest field-gap map and
the rubric that defines what 4/10 means. It is read-only evidence — no claim
below is asserted without a verified source location.

---

## 1. Field-gap map (MS report → our system)

| MS report field | Status | Verified location |
|---|---|---|
| Account / total value | PRESENT | `holdings.json` → `portfolio_totals.total_value` |
| Per-position shares | PRESENT | `holdings.json` → `shares` |
| Per-position price | PRESENT | `holdings.json` → `price` |
| Per-position market value | PRESENT | `holdings.json` → `market_value` |
| Cost basis (adjusted, aggregate) | PRESENT | `holdings.json` → `cost_basis` + `cost_basis_source` (`csv_lot` / `broker_api` / `txn_history`) |
| Per-lot adjusted cost | **PARTIAL** | `schwab_cost_basis_lots.cost_basis` is aggregate-only; `opened_date` is NULL across all rows → per-lot adjusted cost + per-lot term NOT available |
| Holding period LT/ST | PRESENT (derived) | `tax_lots.json` → `lot_date` → `_load_lot_basis().holding_period`; **V (VISA) has no lot date in either source → `None`** |
| Unrealized gain/loss ($ and %) | PRESENT | `holdings.json` → `gain_loss`, `gain_loss_pct` |
| Performance QTD | **ABSENT** | not in `performance_history.json.periods` (1D/1W/1M/3M/6M/YTD/1Y only) |
| Performance YTD | PRESENT | `performance_history.json.periods.YTD` |
| Performance inception | PRESENT | `performance_attribution.json.inception_return` |
| Time-weighted return (TWR) | **ABSENT (documented non-goal)** | money-weighted CAGR (`port_cagr`) + attribution used instead |
| Benchmark | PRESENT | `performance_attribution.json.benchmark_label`, `bench_cagr` |
| Portfolio P/E, P/B, P/S, P/CF | PRESENT (partial) | `ticker_enrichment_cache.json` → `_load_portfolio_analytics()`; **direct-equity only, ~21% market-value coverage** |
| Top 10 holdings | PRESENT | `_load_portfolio_analytics().top_10` |
| Asset allocation / sector | PRESENT (partial) | `_load_portfolio_analytics().sector_breakdown` (direct-equity only) |
| Style box (value/blend/growth) | **ABSENT** | no 3x3 look-through; `style_classification.style_box_available = False`, Hermes research recommended |
| Account details | PRESENT | `holdings.json` → `account` |

### Genuinely absent (require new work, not wiring)

1. **True TWR** — documented non-goal; money-weighted CAGR + attribution is the
   current performance model.
2. **Per-lot adjusted cost + per-lot term** — the broker's aggregate adjusted
   cost is captured, but `schwab_cost_basis_lots` carries no `opened_date`, so
   per-lot adjusted cost and per-lot LT/ST term are not reconstructable from
   the broker export. Needs a fresh Schwab Gain/Loss export that includes
   acquisition dates, or a `trade_transactions` reconstruction that captures
   the adjusted (wash-sale/ROC) basis.
3. **Morningstar-style value/blend/growth box** — no 3x3 style box; only
   direct-equity multiples. Funds/ETFs (~79% of market value) need look-through
   or Hermes research.

### Known data-quality flags (not blockers, must not be silently presented)

- `performance_history.json.periods.3M.change_pct = 73.31` is internally
  inconsistent with its own `change = $56,156` (~4.6% on a ~$1.22M base) and
  uses `source: account-aggregated`. `1Y` (118.8%) is also `account-aggregated`
  and still `building`. These are surfaced with their `source` and `building`
  flags; they are **not** asserted as authoritative returns.
- `ticker_enrichment_cache.json` tags all ETFs/funds as
  `sector=Financial, industry=Exchange Traded Fund` (and mis-tags `SPCX` as
  `Industrials/Aerospace & Defense`). The analytics loader therefore gates
  valuation + sector on a direct-equity signal (`pe` and `pb` both populated)
  rather than trusting the fund tags.

---

## 2. Rubric — what 4/10 means

Ten dimensions, each 0–1. Target = 4.0.

| # | Dimension | Weight | Current | Notes |
|---|---|---|---|---|
| 1 | Data truth (basis, lots, holding period) | 1 | 0.5 | Aggregate adjusted cost + derived LT/ST live; per-lot adjusted cost + VISA lot date missing |
| 2 | Portfolio analytics (multiples/sector/top-10) | 1 | 0.4 | Direct-equity only; no look-through |
| 3 | Performance (YTD/inception/benchmark) | 1 | 0.5 | YTD/inception/CAGR/benchmark live; QTD + true TWR missing |
| 4 | Thesis governance | 1 | 0.8 | `desk@v5` living thesis wired into metadata |
| 5 | Evidence bundle richness | 1 | 0.7 | 14-item bundle; sufficiency gate live |
| 6 | LLM opinion layer | 1 | 0.4 | DeepSeek live but unproven in shadow; coverage < actionable set |
| 7 | Web surface | 1 | 0.3 | API `/v3/advisory` live; single-page UI not yet shipped |
| 8 | Feedback loop | 1 | 0.2 | Feedback schema live; empty in practice |
| 9 | Shadow run / promotion | 1 | 0.3 | Shadow session machinery live; < 10 sessions run |
| 10 | Operator-facing label hygiene | 1 | 0.9 | `s4_*` keys renamed; sprint/phase labels swept from output |

**Current score: ~5.0 / 10** across the deterministic data-truth + surface
tracks. The LLM/shadow/web/feedback tracks (6–9) pull the **operator-facing**
maturity down to the ~4/10 line until the shadow run proves them. The rubric is
deliberately conservative: a dimension stays low until it has **run evidence**,
not just code.

---

## 3. What this sprint wired (and verified)

- Renamed `s4_*` metadata keys → `invariant_violation_count`,
  `untrusted_lot_count`, `listing_date_coverage`, `instrument_identity_coverage`
  (consumers `api_v3_advisory.py`, `shadow_session.py` updated).
- Added `holding_period` (LT/ST/MIXED) + per-lot term to `_load_lot_basis`.
- Added `adjusted_cost`, `cost_basis_source`, `basis_partial` to holding rows.
- Added `_load_portfolio_analytics` (weighted PE/PB/PS/PCF, sector, top-10,
  style classification) and `_load_performance` (period returns, CAGR, alpha,
  Sharpe/Sortino, max drawdown, benchmark).
- Added `_load_living_thesis` surfacing `desk@v5` governing context.
- Exposed all of the above via `_row_view` + desk metadata.

Every item above was verified with a live `build_advisory_desk(force=True)`
run (`validation_ok=True`, `plausibility_gate=PASS`, 53 rows).

---

## 4. Fill methods for genuinely-absent fields

| Field | Fill method |
|---|---|
| True TWR | Money-weighted CAGR is the accepted model; true TWR stays a documented non-goal unless the operator re-scopes performance methodology |
| Per-lot adjusted cost + term | Re-export Schwab Gain/Loss with acquisition dates, or extend `trade_transactions` reconstruction with wash-sale/ROC adjustments |
| Style box | Look-through for funds/ETFs, else Hermes research (`hermes_request@v1`) per unclassified bucket |
| QTD | Add a quarter-start snapshot value to `performance_history.json` generation |
