# LLM Backtesting Validation and Rollback

## Validation
- Dry-run each job
- Verify structured JSON output
- BLMN repaired row produces clean analysis
- APPS repair row produces clean analysis
- No orders placed
- No broker writes
- Model call logging verified

## Rollback
- Delete trade_llm_reviews rows
- Delete monthly_llm_meta_reviews rows
- Drop tables if needed
- git revert
