# v3.9 Validation and Rollback

## Validation
- Delayed reviewer --dry-run produces eligible trade list
- Monthly reviewer --dry-run --no-model shows planned inputs
- No model called in default mode
- No Grok called unless explicit flag
- No cron installed
- No trading actions

## Rollback
- git revert HEAD
- DELETE FROM trade_llm_reviews WHERE review_stage='delayed_review' (if any written)
- DELETE FROM monthly_llm_meta_reviews (if any written)
