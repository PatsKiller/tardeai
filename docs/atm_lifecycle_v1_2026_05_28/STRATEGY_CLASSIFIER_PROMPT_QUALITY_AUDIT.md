# Strategy Classifier Prompt Quality Audit

**Date:** 2026-05-28

## Why ADBE Was Classified as dividend_growth_compounder (Before Fix)

The original prompt (`strategy_classifier_v1.md`) had three critical flaws:

1. **ADBE listed as example dividend stock**: Line 4 said `dividend_growth_compounder: Large-cap dividend stocks held long-term (V, PFE, ADBE)`. ADBE (Adobe) is NOT a dividend stock — it pays no dividend. The prompt gave the model permission to classify it as one.

2. **Hold period = strategy**: Line 29 said `Hold 30+ days with dividend stock = dividend_growth_compounder`. The model interpreted any long hold as "dividend stock" since it had no way to verify dividend status from the trade data.

3. **No escape hatch**: The prompt offered no `unknown` or `needs_review` option. The model was forced to pick a strategy from the list even when evidence was insufficient.

## Whether Model Was Forced to Choose

Yes. The prompt said "Return ONLY valid JSON: one strategy_id only" with no option to say "I don't know." The fallback was `screener` with low confidence, but the rules biased toward `dividend_growth_compounder` for any long hold.

## Whether unknown/needs_review Was Allowed

No. The original prompt listed only concrete strategies. Neither `unknown` nor `needs_review` appeared.

## Evidence Fields Available in Trade Data

| Field | Available | Useful For |
|-------|-----------|------------|
| trade_id | Yes | Identification |
| symbol | Yes | Known stock lookup |
| broker | Yes | Account context |
| account | Yes | Account type |
| entry_price | Yes | Price analysis |
| exit_price | Yes | Price analysis |
| pnl | Yes | Win/loss |
| pnl_pct | Yes | Return magnitude |
| entry_date | Yes | Timing |
| exit_date | Yes | Timing |
| hold_days | Yes | Duration |
| source_table | Yes | Data source |

## Evidence Fields Missing (Critical)

| Field | Impact |
|-------|--------|
| strategy_id/tag | Cannot confirm intended strategy |
| proposal/thesis | Cannot confirm entry rationale |
| catalyst | Cannot confirm earnings/event play |
| dividend yield | Cannot confirm dividend strategy |
| sector/industry | Cannot confirm sector rotation |
| market cap | Cannot confirm scalp vs swing |
| RVOL | Cannot confirm momentum |
| technical indicators | Cannot confirm fib/breakout |
| stop history | Cannot confirm risk approach |

## Conclusion

With only price, dates, and PnL available, the classifier cannot reliably distinguish between most strategies. The correct behavior is to classify as `needs_review` and require additional metadata before applying strategy labels. The original prompt's bias toward `dividend_growth_compounder` was the root cause of false classifications.
