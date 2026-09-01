# PHASE 191B — Open-Trade Profit-Protection Audit

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~11:00 ET · Alpaca **paper** only · Engine: `scripts/profit_protection_advisory.py`
(fresh live quotes; advisory-only). Marks are live-quote-dependent and move intraday.

---

## Audit (snapshot)

| Trade | Sym | Strat | Entry | Live px | uPnL | uPnL% | Broker stop | stop_order_id | Stop dist % | Locks profit? | Profit locked | Giveback if stopped | uR (vs stop) | TP? | Trailing met? | Advisory needed? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 48 | **ANY** | unknown_sync | 3.23 | ~4.02 | **+$402** | **+20.1%** | 3.07 | ✅ | ~24% | **NO** (below entry) | $0 | ~$588 | ~4.9 | NO | no | **YES (urgent)** |
| 43 | **SNOW** | unknown_sync | 236.50 | ~256 | **+$158** | **+8.3%** | 254.38 | ✅ | ~0.6% | **YES** | ~$143 | ~$13 | n/a | NO | no | **YES (take-profit)** |
| 47 | TMHC | swing_breakout | 71.61 | ~71.6 | ≈$0 | -0.1% | 68.02 | ✅ | ~5% | NO | $0 | ~$97 | ~0 | NO | no | no |
| 28 | NWG | dividend_growth_compounder | 15.84 | ~15.87 | +$64 | +2.1% | 15.05 | ✅ | ~5% | NO | $0 | — | 0.1 | NO | no | no |
| 31 | AGNC | reit_income | 10.22 | ~10.30 | +$25 | +0.8% | 9.71 | ✅ | ~6% | NO | $0 | — | 0.0 | NO | no | no |
| 33 | CMCSA | dividend_growth_compounder | 24.97 | ~24.9 | -$16 | -0.5% | 23.61 | ✅ | ~5% | NO | $0 | — | neg | NO | no | no |

MFE/MAE: not populated for the `unknown_sync` positions; available for proposal-originated trades
where the monitor recorded excursions.

## Key observations
- **ANY (urgent):** +20% gain but the broker stop (3.07) sits **below** entry (3.23) → it locks
  **zero** profit; if stopped, ~$588 of paper value relative to current price is surrendered. No
  take-profit, no trailing. This is the strongest profit-protection concern.
- **SNOW (take-profit):** +8.3%; the stop (254.38) is **above** entry (236.50) → already locks
  ~$143 of profit, so giveback is small (~$13). The gap is the **missing take-profit**, not a loose
  stop.
- **TMHC / NWG / AGNC / CMCSA:** below review thresholds → no advisory.

## Counts
reviewed **6** · take-profit missing **6** · stop-quality advisory **1** (ANY) · profit-lock
advisory **1** (ANY) · trailing-eligible **0** · operator-action-required **2** (ANY, SNOW).
