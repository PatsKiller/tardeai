# Monthly Grok Meta-Review Design

## scripts/monthly_grok_trade_meta_review.py

Modes: --dry-run, --dry-run --no-model, --dry-run --allow-grok, --apply --confirm-monthly-meta-write

Default: --dry-run --no-model (no API call, no DB write)

## Eligibility
- Completed month with >= 1 Stage 1 analysis
- Configurable minimum review count (default 3)

## Inputs
- All Stage 1 analyses for the month
- All Stage 2 delayed reviews for the month
- Journal-learning summary
- Paper-vs-backtest comparison
- Strategy rollups
- Missed proposal impact

## Output
monthly_llm_meta_reviews row

## Safety
- Grok ONLY with explicit --allow-grok flag
- Budget cap: configurable per month
- No trading actions
- No strategy mutations
- No cron in v3.9
