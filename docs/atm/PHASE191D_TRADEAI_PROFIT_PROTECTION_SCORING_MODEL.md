# PHASE 191D — TradeAI Profit-Protection Scoring Model

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Implemented:** `scripts/profit_protection_advisory.py` → `score()`. **Advisory only — never moves
stops or places orders.**

---

## Inputs (per open paper trade)
unrealized R (vs planned_stop, else vs broker stop) · unrealized % · unrealized $ · distance to
current stop ($/%) · profit locked by stop · giveback if stopped now · strategy family · ATR/vol
(when available) · time in trade · catalyst/regime (when available) · current spread/liquidity ·
take-profit exists · trailing active · stop verified · quote freshness.

Risk basis: if `planned_stop` exists, R uses it; otherwise the **broker stop** is used as the risk
basis (the fix for `unknown_sync` positions that previously produced no advisory).

## Thresholds (documented, tunable)
| Name | Value | Meaning |
|---|---|---|
| `GAIN_PCT_REVIEW` | 3.0% | start paying attention |
| `GAIN_PCT_LOCK` | 8.0% | meaningful gain → lock/breakeven advisory |
| `LARGE_GAIN_USD` | $250 | large $ gain → take-profit advisory |
| `GIVEBACK_FRACTION_URGENT` | 0.5 | >50% of unrealized gain surrendered if stopped → urgent |
| `QUOTE_FRESH_MIN` | 30 min | older → cannot advise on live giveback |

## Output actions
`NO_ACTION` · `REVIEW_STOP` · `MOVE_TO_BREAKEVEN_ADVISORY` · `LOCK_PROFIT_ADVISORY` ·
`TRAILING_STOP_ADVISORY` · `TAKE_PROFIT_ADVISORY` · `PARTIAL_PROFIT_ADVISORY` ·
`URGENT_PROTECTION_REVIEW`. Data states: `OK` / `QUOTE_STALE` / `STRATEGY_METADATA_MISSING`.

## Decision logic (priority)
1. Quote stale → `REVIEW_STOP` (data_state `QUOTE_STALE`) — no live giveback advice.
2. Large gain ($≥250) **and** stop does not protect ≥50% of it → `URGENT_PROTECTION_REVIEW`.
3. Gain ≥ 8% and stop below entry → `LOCK_PROFIT_ADVISORY`.
4. Gain 3–8% and stop below entry → `MOVE_TO_BREAKEVEN_ADVISORY`.
5. Large gain and no take-profit → `TAKE_PROFIT_ADVISORY`.
6. Trailing tier met → `TRAILING_STOP_ADVISORY`.
7. Gain ≥ 3% → `REVIEW_STOP`; else `NO_ACTION`.
Supporting advisories (e.g. TAKE_PROFIT + LOCK_PROFIT) are attached alongside the primary action.

## Live result (persisted to `atm_profit_protection_advisories`)
| Sym | Action | Supporting | Why |
|---|---|---|---|
| ANY | **URGENT_PROTECTION_REVIEW** | TAKE_PROFIT, LOCK_PROFIT | +20%, stop below entry, ~100% giveback |
| SNOW | **TAKE_PROFIT_ADVISORY** | TAKE_PROFIT | +8.3%, stop already locks profit → not urgent |
| NWG/AGNC/CMCSA/TMHC | NO_ACTION | — | below review threshold |

The model deliberately distinguishes ANY (loose stop, urgent) from SNOW (stop locks profit, only
TP missing) — proving it scores stop **quality**, not just gain size.
