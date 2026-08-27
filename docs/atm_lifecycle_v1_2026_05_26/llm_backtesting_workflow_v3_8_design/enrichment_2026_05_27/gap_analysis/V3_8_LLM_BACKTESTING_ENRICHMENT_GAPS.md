# v3.8 LLM Backtesting Enrichment Gaps

## P0
1. No table to store LLM trade reviews (trade_llm_reviews is designed but not created)
2. No prompt versioning system
3. No model-call audit trail
4. No input snapshot hash mechanism
5. No model timeout/failure capture
6. No guardrail preventing LLM output from mutating strategy/trades

## P1
7. No one-week delayed review scheduler
8. No monthly Grok review job
9. Post-close price movement source unclear (no dedicated price history table for review)
10. Backtest results not linked to paper_trade_id/trace_id
11. External context cache (Google-derived) not structured

## P2
12. UI lacks LLM review status panel (v3.7 shows not_configured)
13. Monthly meta-review not surfaced anywhere
14. No side-by-side Stage 1 vs Stage 2 comparison view

## P3
15. Monolithic api_v2.py (20K+ lines) — LLM endpoints add more
16. Duplicated learning/backtest helper logic across scripts
