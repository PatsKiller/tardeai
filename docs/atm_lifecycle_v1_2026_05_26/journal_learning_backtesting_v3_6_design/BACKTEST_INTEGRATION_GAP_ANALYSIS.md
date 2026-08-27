# Backtest Integration Gap Analysis

## Is backtesting connected to proposal/signal IDs?
NO — backtest runs use strategy config but don't link to specific proposals or signals.

## Is backtesting connected to lifecycle_trace?
NO — lifecycle_trace tracks real trades, backtests are simulated.

## Are simulated trades comparable to paper trades?
PARTIALLY — same strategy YAML defines both, but schema differs.

## Are missed proposals mapped to backtest results?
NO — no mechanism to compare "what was proposed but not traded" against backtest.

## Does BLMN duplicate repair remove contamination?
YES — #37 is now closed as duplicate_submit_race, so journal/learning metrics should exclude it.
However, historical strategy_lesson_rollup may need refresh to exclude ghost rows.

## Missing Fields
- Backtest result lacks source signal/proposal ID
- No trade-case-study view exists
- TCA not included in learning pipeline
- Stop audit not included in learning pipeline
