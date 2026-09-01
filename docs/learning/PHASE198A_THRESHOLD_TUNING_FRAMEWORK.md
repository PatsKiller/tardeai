# PHASE 198A — Advisory Threshold Tuning Framework

Status:      HISTORICAL
as_of:       2026-06-02T13:48:02-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · learning/backtest · recommendation only (no auto-apply, not GO/WAIT)**

---

## What it does
Backtests the 191D advisory thresholds against **bar-validated** closed-trade outcomes.
`scripts/tune_advisory_thresholds.py`:
1. Reconstructs each measurable closed trade's **MFE-peak decision point** (unrealized %/$/giveback,
   stop-locks-profit) from `trade_mfe_analysis` + `paper_trades`.
2. Replays the **exact live scoring** (`profit_protection_advisory.score`, with its module-global
   thresholds monkeypatched per candidate — so there is **no logic divergence**).
3. For each threshold combination, measures **give-back capture** (of trades that actually gave back,
   how many would the model have flagged for protection at their peak), **flag rate** (over-flagging
   proxy), and **missed give-back $**.
4. Recommends the setting with max capture, then least over-flagging — **advisory only**.

Sweep grid: `GAIN_PCT_LOCK ∈ {3,5,6,8,10}`, `LARGE_GAIN_USD ∈ {100,150,250,400}`,
`GIVEBACK_FRACTION_URGENT ∈ {0.3,0.4,0.5,0.6}` (the give-back levers; `GAIN_PCT_REVIEW`/
`QUOTE_FRESH_MIN` held).

## Result (2026-06-02, 24 cases, 20 gave back)
| | thresholds | capture | flag rate | missed give-back $ |
|---|---|---|---|---|
| **Current** | LOCK 8 / $250 / 0.5 | **55%** | 62.5% | $606 |
| **Recommended** | LOCK 10 / $250 / 0.3 | 55% | **58.3%** | $606 |

## Honest reading
- **Capture caps at 55% across *all* threshold combos.** The 9 uncaptured give-back trades peaked
  **below ~3%** gain — tiny, noise-level give-backs where protection is correctly *not* worth
  flagging. Lowering thresholds further would not catch them without massive over-flagging.
- The recommended change (LOCK 8→10) yields the **same capture with fewer false positives** — a
  marginal improvement (flag rate 62.5%→58.3%, FP 4→3).
- **Sample is small (24) and synthetic** — these are *retrospective* applications; **no live-advised
  trade has closed yet**. So the recommendation is informative, not actionable.

## Recommendation
**Do not change the live thresholds yet.** The current settings are reasonable (55% capture, no false
sense of precision). Re-run the framework as **real advised trades (ANY/SNOW and future) close** and
produce `confirmed`/`contradicted` accuracy; tune when the sample is real and larger.

## Surfacing & scheduling
- Endpoint `GET /api/v2/atm/advisory-threshold-tuning` (latest run; frontend-neutral v2/v3).
- Added to `run_protection_pipeline.sh` (refreshes each pipeline run).
- Persists to `advisory_threshold_tuning`.

## Guardrail
Read-only on broker. Writes only the tuning summary table. Reuses the live `score()` (no divergence).
No execution, no stop/order changes, no GO/WAIT/strategy mutation, Level 7 prohibited. Thresholds are
advisory-model params and are **never auto-applied**.
