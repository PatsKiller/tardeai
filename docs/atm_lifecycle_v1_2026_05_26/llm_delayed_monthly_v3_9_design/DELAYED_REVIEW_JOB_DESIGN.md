# Delayed Trade LLM Reviewer Design

## scripts/delayed_trade_llm_reviewer.py

Modes: --dry-run, --dry-run --allow-local-llm, --apply --confirm-llm-review-write

## Eligibility
- Trade closed >= 7 calendar days ago
- Stage 1 close_analysis exists in trade_llm_reviews
- delayed_review does NOT already exist for this trade
- Post-close price/outcome data available

## Inputs
- Stage 1 output (from trade_llm_reviews)
- Post-close price movement (from market data or journal)
- Backtest comparison (from paper-vs-backtest if available)
- Journal outcome (exit_reason, pnl, R-multiple)
- TCA/slippage (from paper_execution_quality)
- Stop audit (from lifecycle_events stage=stop_change)

## Output
trade_llm_reviews row: review_stage='delayed_review'
Fields: revised_assessment, outcome_comparison, missed_signal, updated_lesson, confidence

## Safety
- No broker writes, no orders, no stop changes
- Local LLM only (no Grok for delayed review)
