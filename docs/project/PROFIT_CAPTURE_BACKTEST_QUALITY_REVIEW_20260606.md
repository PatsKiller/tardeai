# Profit-Capture Rule Backtest — Quality Review (2026-06-06)

**Status:** Review complete. Verdict: **NOT decision-grade.** Evidence-only; `DO_NOT_GRAFT` upheld.

## Current endpoint / UI state (canonical layer)

- 196 closed trades (all sources)
- 34 bar-measurable trades
- 13 measurable winners
- 9 winners with give-back
- **$1,239.29** canonical money left on table
- best current shadow rule: **`trail5_after_2R`**
- reported recovery estimate: ~**$2,728** (raw, single-peak, all 34 trades)

## Verdict

- The backtest **harness is directionally useful** and the evidence/action separation worked
  (nothing grafted; shadow gate refuses every family).
- The **evidence is not decision-grade.** Magnitudes are overstated and the optimized population is
  partly phantom. No threshold change is defensible.
- **No graft allowed.**

## Main weaknesses (evidence)

### 1. Raw sample overstated
`sample_size=34` counts the whole measurable population. Rules only act on trigger-eligible trades:
**≥2R = 11, ≥3R = 6.** `trail8_after_3R` is effectively n=6, not 34.

### 2. Reliable / effective sample missing (the decisive number)
Genuinely usable evidence = **winners with reliable MFE** (≥10 bars analyzed, valid planned stop):
- winners with ≥10-bar MFE = **2**
- winners with ≥20-bar MFE = **1**
- reliable recoverable give-back ≈ **$674** (from 2 trades)

The reported `confidence='high'` on this is wrong — the heuristic keys off raw `sample_size ≥ 20`.

### 3. MFE inputs unreliable for most trades
- **21 of 34 (62%) have ≤3 bars** of MFE analysis; **11 have a single bar.** These carry **$3,440 of
  $7,588 (45%)** of total max-profit.
- Extreme `mfe_r` are artifacts of tiny/corrupt planned stops: **SNOW mfe_r=48.5** (3 bars),
  **MRVL mfe_r=39.7** (1 bar). An mfe_r that large implies a ~0.4% stop — a bad risk denominator.

### 4. Mixed winners/losers objective (single-peak approximation)
- Measurable universe is **21 losers vs 13 winners.**
- **78% of the optimized "money left" ($4,325 of $5,564) comes from losing trades**, not winner
  give-back ($1,239). Largest contributor `ANY / unknown_sync` is a **loser with realized $0** but
  $1,838 "money left"; `unknown_sync` (a sync/import tag) is **33%** of total max-profit.
- The single-peak model assumes a floor binds only *after* the true peak → **premature_exit_cost = 0**,
  which is structurally optimistic. With 1-bar MFE there is no path to order stop-trigger vs later profit.

### 5. Concentration
Top 1 trade = **24%**, top 3 = **43%** of total max-profit. Removing 2–3 corrupted-MFE trades collapses
the headline recovery.

### 6. Insufficient per-family evidence
Family samples are tiny (swing ≈ 13, momentum ≈ 6, income ≈ 5, position = 1). None meets the
20-trade evidence floor.

## What is valid

The directional signal — trailing/locking after a profit threshold reduces give-back — is plausible
and internally consistent. The infrastructure is sound; only the *evidence magnitude* is not yet
trustworthy.

## Required remediation

1. **Data-quality gate** — exclude `bars_analyzed < N` (≥10), `mfe_r` outliers (> max), require valid
   `planned_stop`, `max_profit > 0`.
2. **Winners-only give-back variant** — separate winner give-back from loser/breakeven risk-control.
3. **Effective / reliable sample reporting** — raw vs quality-eligible vs triggered vs winner vs reliable.
4. **Confidence heuristic fix** — base confidence on `reliable_sample_size`, not raw `n`.
5. **Honest premature-exit cost** — mark `premature_exit_cost_known=false` under single-peak MFE;
   label recovery `upper_bound` / `approximation`.
6. **Maintain `DO_NOT_GRAFT`** until reliable evidence floor is met.

Implementation tracked in `PROFIT_CAPTURE_RULE_BACKTEST_HARDENING_20260606.md`.
