# PHASE 194A — MFE/MAE Units Fix (Data-Integrity)

Status:      HISTORICAL
as_of:       2026-06-02T12:59:18-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · data-quality fix · no execution / no stop / no order / no GO-WAIT changes**

---

## Root cause
`paper_trades.max_favorable_excursion` / `max_adverse_excursion` were written in **two different
units** by two scripts:
| Writer | Unit written | When |
|---|---|---|
| `paper_trade_monitor.py:264` | **percent** (`(price-entry)/entry*100`) | live, each monitor cycle |
| `trade_execution_analyzer.py:233` | **R-multiple** (`mfe_r`) | post-trade, from bars |

Same column, two units → whichever ran last won. Result: some rows held %, some held R, and some
were impossible as a max (MFE < realized favorable move). The column was unusable for learning.

## Fix
1. **Code (durable):** `trade_execution_analyzer.py` now writes **percent**
   (`(mfe_price-entry)/entry*100`) to `paper_trades`, consistent with `paper_trade_monitor.py`.
   The R-multiple keeps its correct home in `trade_mfe_analysis.mfe_r`; the dollar
   profit-left-on-table is `trade_mfe_analysis.money_left`.
2. **Backfill:** re-ran the (fixed) analyzer → bar-based MFE for **3** closed trades; set
   `paper_trades` MFE% from `trade_mfe_analysis.mfe_price` for those.
3. **Honest nulling:** **21** closed trades have **no entry/exit timestamps** (→ no bars → no
   reliable MFE). Their corrupt MFE values were set to **NULL** (honest "unknown") rather than left
   wrong. This is a secondary data-quality finding (timestamp capture) — Phase 195 candidate.
4. **Reconciler:** `reconcile_protection_advisory_outcomes.py` now sources give-back from the
   **authoritative bar analysis** (`money_left` $, `mfe_price` %). Trades without bar analysis get
   `gave_back_profit=null`, `mfe_source='none'` — **not scored** (no fabrication). Added columns
   `profit_left_on_table_usd`, `mfe_source`.

## Corrected results (replaces the retracted 41.7%)
| Metric | Value |
|---|---|
| Closed trades | 24 |
| Measurable (bar-based MFE) | **3** |
| Unmeasurable (no timestamps) | 21 |
| Of measurable, gave back profit | **3 / 3** |
| **Total profit left on table (measurable)** | **$414.68** |

| Trade | Realized | Left on table ($) | Note |
|---|---|---|---|
| ASPN | $0.00 | **$265.44** | peaked +8.9%, round-tripped to flat — textbook give-back |
| NVDA | −$4.90 | $102.83 | was +3.6% then closed a small loss |
| INFU | +$67.83 | $46.41 | winner that left more on the table |

Small sample, but **trustworthy** — every value traces to bar data, not a corrupted column.

## Endpoint
`GET /api/v2/atm/protection-advisory-outcomes` summary now reports
`baseline_measurable_with_bar_mfe`, `baseline_unmeasurable_no_mfe`,
`baseline_gaveback_rate_pct_of_measurable` (100%), and `baseline_profit_left_on_table_usd` ($414.68).

## Guardrail
Read-only on broker (analyzer fetches historical bars = market data). DB writes limited to MFE
columns + outcomes table. No execution, no stop/order changes, Level 7 prohibited.
