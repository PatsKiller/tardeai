# Paper vs Backtest Comparison Design

## Questions This Answers
1. What did the strategy backtest expect for this symbol?
2. What happened in paper trading?
3. Was the trade taken or missed?
4. If missed, would it have won or lost?
5. What was the R-multiple paper vs simulated?
6. Did stop/trailing match policy?
7. What should be learned?

## Comparison Model
Join lifecycle_trace → paper_trades (closed) → paper_execution_quality → strategy config.
Compare: expected win rate vs actual, expected R vs actual R, expected hold time vs actual.

## Missing Links
- Backtest results not linked to proposal/signal IDs
- Simulated trades not stored with same schema as paper trades
- No missed-proposal impact calculation yet
