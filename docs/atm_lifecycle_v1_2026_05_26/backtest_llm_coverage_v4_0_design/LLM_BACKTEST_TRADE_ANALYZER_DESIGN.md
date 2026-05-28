# LLM Analyzer for Backtest Trades Design

## Extend trade_close_llm_analyzer.py

New flag: --source backtest|paper (default: paper)

When --source backtest:
- Query strategy_backtest_trades instead of paper_trades
- Build input snapshot from backtest trade data
- Write trade_llm_reviews with source_table='strategy_backtest_trades'
- Same prompt, model, safety controls

## Schema Extension
```sql
ALTER TABLE trade_llm_reviews ADD COLUMN IF NOT EXISTS backtest_trade_id BIGINT;
ALTER TABLE trade_llm_reviews ADD COLUMN IF NOT EXISTS source_table TEXT DEFAULT 'paper_trades';
```

## Coverage Target
- 872 existing backtest trades → Stage 1 close analyses
- Process in batches: --limit 50 per run
- Estimated: 18 runs to cover all 872 trades
- Local LLM only, no Grok

## Safety
- No broker writes
- No paper_trades changes
- No order placement
- Backtest analysis only
