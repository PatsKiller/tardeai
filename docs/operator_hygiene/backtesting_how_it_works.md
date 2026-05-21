# How Backtesting Works — Current State (2026-05-21)

## What It Is

The backtester is a **simplified Monte Carlo simulation** that takes historical screener signals and asks: "If we had traded every GO signal with a fixed stop/target model, what would the results look like?"

It does **not** replay actual market data bar-by-bar. It uses the screener's GO decision + score as the only input and simulates outcomes probabilistically.

## What It Tests

**Screener GO signals** — every time the Trade AI screener marked a symbol as "GO" with a score, the backtester treats that as a hypothetical entry signal and simulates the trade outcome.

It is NOT testing:
- Past trades you actually took (that's the Paper Journal)
- Trades you missed (that would require a different engine)
- Real price action after the signal (no OHLCV bar replay)

## How Simulation Works

For each GO signal:

1. **Entry**: Signal price + 0.1% slippage
2. **Stop**: 5% below entry (fixed)
3. **Target**: 8% above entry (fixed, giving 1.6:1 R:R)
4. **Outcome**: Determined by signal score as probability:
   - Score 75 → 50% chance of hitting target
   - Score 50 → 33% chance of hitting target
   - Score 100 → 67% chance of hitting target
   - Formula: `hit_probability = score / 150`
5. **If target NOT hit**: 60% chance stop hit, 40% chance random exit between stop and half-target
6. **Deterministic**: Same signal always produces same result (seeded by symbol+time hash)

## Per-Strategy Filtering

When run with `--strategy momentum_scalp`:
- Looks up symbols that have proposals classified as `momentum_scalp` in the last 90 days
- Filters GO signals to only those symbols
- This means: "How would momentum_scalp candidates have performed if we traded all GO signals on them?"

When run with `--all-strategies`:
- Runs each strategy config through the same filter
- Strategies with 0 matching proposal symbols get 0 trades

## What the Numbers Mean

| Metric | Meaning |
|--------|---------|
| Win Rate | % of simulated trades that hit target |
| Profit Factor | Gross profit / gross loss (>1.0 = profitable) |
| Expectancy (R) | Average R-multiple per trade (>0 = profitable) |
| Sample Status | `insufficient` (<30), `insight_only` (30-99), `shadow_candidate` (100+) |

## Current Results (2026-05-21)

| Strategy | Trades | Win Rate | Profit Factor | Status |
|----------|--------|----------|---------------|--------|
| all_signals | 59 | 33.9% | 0.61 | insight_only |
| momentum_scalp | 20 | 30.0% | 1.38 | insufficient |
| swing_breakout | 7 | 28.6% | 2.64 | insufficient |
| gap_and_go | 7 | 42.9% | 0.37 | insufficient |
| swing_trade | 4 | 75.0% | 20.17 | insufficient |

**Warning**: All results are insufficient sample size. swing_trade's 75% win rate on 4 trades is statistically meaningless.

## Limitations (Important)

1. **No real price data**: Outcomes are simulated from score probability, not actual price movement after the signal
2. **Fixed stop/target**: Uses 5%/8% for everything — real strategies use different levels per setup
3. **No spread/volume modeling**: Assumes infinite liquidity at any price
4. **No time decay**: A signal from 2 weeks ago and one from yesterday are treated identically
5. **No intrabar data**: Can't model gap-ups, intraday reversals, or overnight risk
6. **Deterministic seed**: Re-running produces identical results (not a flaw, but means no variance analysis)

## What Would Make It Better

1. **Actual OHLCV replay**: Use `price_cache.json` (1604 days of daily data for portfolio symbols) to simulate real price paths after signal entry
2. **Strategy-specific stop/target**: Pull from YAML configs instead of fixed 5%/8%
3. **Volume/spread filtering**: Skip signals where actual volume was too low for the proposed position size
4. **Walk-forward testing**: Train on first half of data, test on second half
5. **Missed trade analysis**: Compare "what we traded" vs "what the screener said GO on but we didn't trade"

## How to Run

```bash
# All strategies
.venv/bin/python scripts/strategy_backtester.py --all-strategies --apply --json

# Single strategy
.venv/bin/python scripts/strategy_backtester.py --strategy momentum_scalp --apply --json

# Dry run (no DB writes)
.venv/bin/python scripts/strategy_backtester.py --all-strategies --dry-run --json
```

## Database Tables

| Table | Purpose |
|-------|---------|
| `backtest_datasets` | Source data snapshots (4 datasets, scan-based) |
| `strategy_backtest_runs` | Each run's metadata (strategy, dates, config) |
| `strategy_backtest_trades` | Individual simulated trades with entry/exit/pnl |
| `strategy_backtest_results` | Aggregated metrics per run (win rate, PF, expectancy) |
| `challenger_definitions` | Champion/challenger experiment configs (empty — not yet used) |
| `champion_challenger_results` | A/B comparison results (empty — not yet used) |

## Dashboard

View at `/v2/backtesting` — shows runs, trades, results, and challenger comparisons.
