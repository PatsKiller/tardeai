# LLM Backtesting Job Design

## Job 1: trade_close_llm_analyzer.py
- Runs after trade close (cron or event-driven)
- Local 3.14B LLM
- Writes trade_llm_reviews (stage=close_analysis)
- Modes: --dry-run, --apply
- Timeout: 120s per trade
- Cost: local only (free)

## Job 2: delayed_trade_llm_reviewer.py
- Runs daily, finds trades closed ~7 days ago without Stage 2 review
- Local LLM
- Writes trade_llm_reviews (stage=delayed_review)
- Modes: --dry-run, --apply

## Job 3: monthly_grok_trade_meta_review.py
- Runs monthly (1st of month)
- Grok API (external, cost-controlled)
- Writes monthly_llm_meta_reviews
- Modes: --dry-run, --apply
- Budget cap: configurable per month

All jobs: no trading actions, no broker writes, no stop modifications.
