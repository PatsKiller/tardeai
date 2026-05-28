# v4.0 Gaps

## P0
1. No recurring backtest cron exists
2. 872 backtest trades have 0 LLM reviews
3. Backtest results from May 21 are stale

## P1
4. trade_llm_reviews has no backtest_trade_id column
5. LLM analyzer only queries paper_trades
6. No triggered re-run on strategy config change
7. No backtest freshness monitoring

## P2
8. Trade inspector cannot drill into backtest trades
9. No paper-vs-backtest side-by-side for V/AXTI

## P3
10. Enterprise backtester runtime unknown (may be slow for 96 symbols)
