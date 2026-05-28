# v4.0 Recurring Backtest + LLM Review Coverage Design

## Problem
- 872 backtest trades across 96 symbols (V, AXTI, etc.) exist but are not scheduled for recurring runs
- No backtest cron exists — last runs were May 21, 2026 (manual)
- LLM close-analysis only covers 4 paper_trades, not 872 backtest trades
- Backtest results become stale as strategy configs and market data change

## Two Components

### A. Recurring Backtest Cron
Schedule enterprise_backtester.py or strategy_backtester.py to run periodically.

Proposed schedule:
- Weekly Sunday: full backtest run across all active strategies
- After strategy config change: triggered re-run for affected strategies
- Monthly: comprehensive cross-strategy comparison run

Cron design:
```
# Weekly Sunday backtest (after all weekly jobs)
0 22 * * 0 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/enterprise_backtester.lock $PY scripts/enterprise_backtester.py --all-strategies >> logs/enterprise_backtester.log 2>&1
```

Safety:
- Backtest runs simulated trades only — no real orders
- Results go to strategy_backtest_trades table only
- No paper_trades modification
- No broker writes
- safe_flock prevents overlap

### B. LLM Analyzer for Backtest Trades
Extend trade_close_llm_analyzer.py to also analyze strategy_backtest_trades.

New mode: --source backtest
- Queries strategy_backtest_trades instead of paper_trades
- Same prompt/model/safety
- Writes trade_llm_reviews with paper_trade_id=NULL, backtest_trade_id instead
- Allows Stage 2 delayed review to compare backtest vs paper outcomes

Proposed schema addition:
```sql
ALTER TABLE trade_llm_reviews ADD COLUMN IF NOT EXISTS backtest_trade_id BIGINT;
ALTER TABLE trade_llm_reviews ADD COLUMN IF NOT EXISTS source_table TEXT DEFAULT 'paper_trades';
CREATE INDEX IF NOT EXISTS idx_tlr_backtest ON trade_llm_reviews(backtest_trade_id);
```

### C. Combined Coverage Target
After v4.0:
- 872 backtest trades get LLM close analyses
- 4 paper trades already have Stage 1 reviews
- Weekly fresh backtest runs keep results current
- Journal-learning-summary includes both sources
- Trade inspector can drill into backtest trades

## What v4.0 Will NOT Do
- No live trading
- No broker writes
- No automatic strategy changes from LLM output
- No Grok until Stage 1/2 validated for paper trades
