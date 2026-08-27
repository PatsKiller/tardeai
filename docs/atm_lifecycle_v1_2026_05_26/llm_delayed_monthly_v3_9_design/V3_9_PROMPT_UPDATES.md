# v3.9 Prompt Updates

## Delayed Review Prompt (delayed_review_v1.md already exists)
- Requires: Stage 1 output, post-close price, backtest comparison
- Output: structured JSON with revised_assessment, outcome_comparison

## Monthly Meta-Review Prompt (monthly_meta_v1.md already exists)
- Requires: all Stage 1 + Stage 2 for the month
- Output: patterns, strengths, weaknesses, strategy_lessons, recommendations
- Must include: "This is analysis only. No orders. No strategy changes."
