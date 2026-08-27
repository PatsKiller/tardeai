# LLM Backtesting API Design

## GET /api/v2/lifecycle/llm-review-status
Summary of all LLM reviews: total generated, pending, missing.

## GET /api/v2/lifecycle/trade-llm-review?paper_trade_id=N
Returns stored LLM analysis for a specific trade. Does NOT call LLM.

## GET /api/v2/lifecycle/monthly-llm-meta-review?month=YYYY-MM
Returns stored monthly meta-review. Does NOT call LLM.

## POST endpoints (DEFERRED — requires separate approval)
- POST /api/v2/lifecycle/generate-trade-review (triggers Stage 1 or 2)
- POST /api/v2/lifecycle/generate-monthly-review (triggers Stage 3)
