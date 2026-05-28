# v3.9 Delayed Review + Monthly Meta-Review Implementation Plan

## Stage 2 — Delayed Post-Close Review
- Trigger: ~7 days after trade close
- Model: local LLM
- Eligibility: Stage 1 exists, delayed_review doesn't exist, post-close data available
- Compares Stage 1 assessment vs actual outcome
- Writes trade_llm_reviews (review_stage='delayed_review')

## Stage 3 — Monthly Meta-Review
- Trigger: monthly (1st of month)
- Model: Grok or configured external
- Eligibility: completed month, minimum Stage 1/2 reviews exist
- Summarizes patterns, strengths, weaknesses, strategy lessons
- Writes monthly_llm_meta_reviews

## Manual Dry-Run Flow (default)
1. Run delayed_trade_llm_reviewer.py --dry-run (no model, no DB)
2. Review eligible trades and planned inputs
3. Run --dry-run --allow-local-llm (model call, no DB)
4. Review model output quality
5. Run --apply --confirm-llm-review-write (writes row)

## Future Cron Flow (deferred)
- Not scheduled in v3.9
- Designed for operator approval after manual validation

## Safety
- No trading actions from any LLM output
- No automatic strategy changes
- Grok only with explicit --allow-grok flag
- No cron in v3.9
