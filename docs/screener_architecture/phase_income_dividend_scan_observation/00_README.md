# Income/Dividend Screener Observation

**Status:** COMPLETE — Pipeline working, no proposals created (legitimate blockers)
**Date:** 2026-05-21

## What We Ran

1. **5 income/dividend Finviz screeners** manually: div_growth_quality (92 tickers), dividend_aristocrats (705), income_candidates (546), high_yield_bdc_reit (338), reit_income_scan. 11 new tickers discovered.

2. **Weekly incubator builder** refreshed: 122 dividend_growth_compounder, 29 income_add, 5 reit_income, 2 bond_income candidates in incubator.

3. **Production promoter** ran with MAP-4 family thresholds.

## Promoter Results

| Candidate | Strategy | Result | Reason |
|-----------|----------|--------|--------|
| NEE | dividend_growth_compounder | BLOCKED | `rr_below_minimum` + `quote_never_checked` |
| AIAI | various | SKIPPED | spread 37.4% too wide for all families |
| AMPG | various | BLOCKED | `quote_never_checked` |
| EZGO | recovery_watch | SKIPPED | spread 19.0% > 5.0% |
| CVM | recovery_watch | SKIPPED | spread 14.9% > 5.0% |

**Family thresholds correctly applied:**
- "spread_37.4pct > 3.0% for GAP_EVENT" ← momentum gate preserved
- "spread_37.4pct > 5.0% for TECHNICAL_PATTERN" ← swing gate applied
- "spread_37.4pct > 5.0% for SPECULATIVE_GROWTH" ← growth gate applied

## Why No Income/Dividend Proposals Yet

1. **Score gate**: Only 1 of 122 dividend candidates (NEE) has score ≥ 30 (the promotion threshold). Income stocks get low scores because the scoring system is momentum-oriented (high RVOL, gap, catalyst = high score).

2. **Quote gate**: NEE blocked by `quote_never_checked` — the pre-promotion readiness policy requires an execution-eligible quote before promotion.

3. **Latest scan decision**: NEE's most recent scan was AVOID (score 13) — the promoter uses the latest scan, not the best historical scan.

## Root Cause of Low Income Scores

The `trade_ai_scans` scoring system awards points for:
- High RVOL (relative volume) → income stocks have low RVOL
- Large gap % → income stocks have small gaps
- Catalyst verification → income stocks often have no "catalyst"
- High daily change % → income stocks are stable

This means income stocks consistently score 10-20 (below the 30 threshold), even though they're valid dividend candidates.

## Recommendations for SCREENER-MAP-5

1. **Lower score floor for DIVIDEND_INCOME family** from 30 to 15 or 10 in the classification candidate query
2. **Add dividend-specific scoring** — yield, payout ratio, consecutive years of dividend growth should boost score
3. **Run proactive quote refresh** on income candidates so `quote_never_checked` is resolved
4. **Consider classification confidence** as a promotion signal (NEE has confidence=1.0)

## Safety

- Proposals created: **0** (all blocked by legitimate gates)
- Trades created: **0**
- Orders submitted: **0**
- Strategy activation changed: **NO**
- YAML/Finviz changed: **NO**
- ALPACA_MODE=paper
