# Phase 8D — Strategy Quality Readiness Matrix (Read-Only)

**Date:** 2026-05-22
**Status:** READ-ONLY PREP — Full Phase 8D remains BLOCKED

## Evidence Tiers

| Tier | Closed Trades | Status | Allowed Actions |
|------|--------------|--------|-----------------|
| 5+ | Full baseline | FULL_8D_READY | Read-only review, tentative conclusions |
| 3–4 | Baseline building | READONLY_REVIEW_READY | Read-only observations, no decisions |
| 1–2 | Early signal | BASELINE_BUILDING | Monitor only |
| 0 | No evidence | NOT_READY | No review possible |

## Per-Strategy Readiness

| Strategy | Closed | Wins | Losses | PnL | Status | Evidence Gap |
|----------|--------|------|--------|-----|--------|-------------|
| **dividend_growth_compounder** | 2 | 1 | 0 | $27 | BASELINE_BUILDING | Need 1+ more closed trades. 3 open positions may close soon. |
| **earnings_catalyst** | 2 | 1 | 1 | $247 | BASELINE_BUILDING | Need 1+ more. Mixed results (1 target hit, 1 instant stop). |
| **swing_breakout** | 2 | 2 | 0 | $163 | BASELINE_BUILDING | Need 1+ more. Both wins but small R (0.23 avg). |
| **momentum_scalp** | 2 | 0 | 2 | -$246 | BASELINE_BUILDING | 0% WR concerning. Need 3+ to confirm or flag for review. |
| **reit_income** | 1 | 0 | 0 | $0 | BASELINE_BUILDING | 1 orphan close (partial fill). 1 position open. Need real closes. |
| **swing_trade** | 1 | 0 | 1 | -$15 | BASELINE_BUILDING | 1 broker-closed loss. 1 position open. Need more data. |
| **core_growth_compounder** | 0 | — | — | — | NOT_READY | 0 trades. 1 proposal pending. ATM-eligible but no fills yet. |
| **recovery_watch** | 0 | — | — | — | NOT_READY | 0 trades despite 10 proposals. All rejected/expired/deferred. |
| **gap_and_go** | 0 | — | — | — | NOT_READY | Same-day skip by ATM. 4 proposals, 0 trades. |
| **speculative_growth** | 0 | — | — | — | NOT_READY | 0 trades. 4 proposals all rejected/expired. |
| **defense_thesis** | 0 | — | — | — | NOT_READY | 0 trades. 1 proposal expired. |
| **sector_rotation** | 0 | — | — | — | NOT_READY | 0 trades. 1 proposal expired. |
| **fib_retracement_bounce** | 0 | — | — | — | NOT_READY | 0 trades. B-1 excluded until 2026-05-25. |
| **earnings_post_momentum** | 0 | — | — | — | NOT_READY | 0 trades. B-1 excluded. |
| **earnings_pre_buildup** | 0 | — | — | — | NOT_READY | 0 trades. No proposals. |
| **bond_income** | 0 | — | — | — | NOT_READY | 0 trades. No proposals. |
| **cash_or_stable** | 0 | — | — | — | NOT_READY | Cash strategy — not traded. |
| **core_index** | 0 | — | — | — | NOT_READY | 0 trades. No proposals. |
| **covered_call_income** | 0 | — | — | — | NOT_READY | Options strategy — not in paper scope. |
| **high_yield_income_bdc** | 0 | — | — | — | NOT_READY | 0 trades. No proposals. |
| **income_add** | 0 | — | — | — | NOT_READY | 0 trades. No proposals. |
| **international_dividend** | 0 | — | — | — | NOT_READY | 0 trades. No proposals. |
| **tax_loss_harvest** | 0 | — | — | — | NOT_READY | Seasonal strategy — not active. |

## Summary

| Status | Count | Strategies |
|--------|-------|------------|
| FULL_8D_READY (5+) | **0** | — |
| READONLY_REVIEW_READY (3-4) | **0** | — |
| BASELINE_BUILDING (1-2) | **6** | dividend_growth, earnings_catalyst, swing_breakout, momentum_scalp, reit_income, swing_trade |
| NOT_READY (0) | **17** | All others |

## Key Gaps

### Why 17 strategies have zero trades
1. **B-1 excluded (5):** swing_breakout*, swing_trade*, earnings_post_momentum, recovery_watch, fib_retracement — deferred until 2026-05-25
2. **Same-day skip (2):** momentum_scalp*, gap_and_go — ATM cadence too slow for intraday
3. **No proposals generated (8):** bond_income, core_index, covered_call, earnings_pre, high_yield, income_add, international_div, tax_loss
4. **Proposals rejected/expired (2):** speculative_growth, recovery_watch — failed downstream gates

*These have trades from manual/pre-ATM period but are excluded from ATM active.

### What would unlock more evidence
1. **B-1 expires 2026-05-25** — unblocks 5 strategies for ATM on Monday
2. **max_new_per_day=1** limits throughput — consider raising to 2-3 after clean burn-in
3. **Income/dividend strategies need time** — these are long-hold strategies, closes take weeks/months
4. **Recovery proposals blocked** — 10 proposals, 0 trades. Likely spread/volume gates. Investigate.

## Phase 8D Full Review Requirements

To unlock full Phase 8D for any strategy:
- ≥ 5 closed trades with clean exit data
- Route audit verified
- Stop protection confirmed
- Exit reasons properly categorized
- R-multiple calculated
- No orphan/partial-fill artifacts counted as real trades

**Current: 0 strategies qualify. Full Phase 8D remains BLOCKED.**

## Recommended Evidence Targets

| Target | Current | Needed | Estimated Timeline |
|--------|---------|--------|-------------------|
| Total closed trades | 11 | 20+ | 1-3 weeks |
| Any strategy at 5+ closed | 0 | 1+ | 2-4 weeks |
| dividend_growth at 3+ closed | 2 | 3+ | Days (3 positions open) |
| momentum_scalp at 3+ closed | 2 | 3+ | 1-2 weeks (same-day skip) |
| Strategies with baselines | 0 | 3+ | 2-4 weeks |
