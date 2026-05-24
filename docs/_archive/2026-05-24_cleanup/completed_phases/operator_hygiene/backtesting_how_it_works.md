# How Backtesting Works — Current State (2026-05-21)

## Two Backtesting Engines

### 1. Enterprise Price-Replay Backtester (NEW — Real OHLC)

**`enterprise_backtester.py`** — Replays actual daily OHLC bars from yfinance against historical signals. Deterministic results from real price data.

**Modes:**
- **Replay Actual Trades** — Takes every closed trade from journal, replays entry date forward with real high/low bars, checks if stop/target hit. Compares replay result to actual outcome.
- **Replay Untaken Proposals** — Takes proposals that were rejected/expired (never traded), replays to see what would have happened.
- **Per-Strategy Replay** — Filter to one of 23 strategies.

**What it measures:**
- Real P&L from actual price bars (not simulated)
- MAE (max adverse excursion — worst drawdown from entry)
- MFE (max favorable excursion — best unrealized profit from entry)
- Hold time, exit reason (stop/target/timeout)
- Replay vs actual comparison (outcome match rate)

### 2. LLM Trade Analyzer + Strategy Incubator Backtester

**`backtest_analyzer.py`** — Three capabilities:

**A) LLM Entry/Exit Grading** — For each closed trade, asks the LLM:
- Was entry early, optimal, late, or chased?
- What was the optimal entry price?
- Was the thesis correct?
- Grade: A-F for entry and exit
- Includes Finviz daily+weekly chart URLs for visual context

**B) Strategy Pattern Backtesting on Incubator** — Takes a strategy (e.g. fib_retracement_bounce), finds all incubator symbols classified for it, replays the signal date forward with strategy-specific stop/target from YAML configs using real OHLC bars.

**C) Finviz Chart Integration** — Every result includes clickable chart URLs for visual pattern verification.

### 3. Legacy Probability Backtester (Original)

**`strategy_backtester.py`** — The original placeholder. Uses score-based probability simulation, not real price data. Still available but superseded by the enterprise engine.

## All 23 Strategies

| # | Strategy | Type | Backtest-able |
|---|----------|------|--------------|
| 1 | momentum_scalp | Intraday | NO (daily bars) |
| 2 | gap_and_go | Intraday | NO (daily bars) |
| 3 | swing_breakout | Multi-day | YES |
| 4 | swing_trade | Multi-day | YES |
| 5 | recovery_watch | Multi-day | YES |
| 6 | earnings_catalyst | Event | YES |
| 7 | earnings_post_momentum | Event | YES |
| 8 | earnings_pre_buildup | Event | YES |
| 9 | speculative_growth | Growth | YES |
| 10 | sector_rotation | Rotation | YES |
| 11 | fib_retracement_bounce | Technical | YES |
| 12 | dividend_growth_compounder | Income | YES |
| 13 | defense_thesis | Thematic | YES |
| 14 | core_growth_compounder | Core | YES |
| 15 | core_index | Core | YES |
| 16 | covered_call_income | Income | YES |
| 17 | high_yield_income_bdc | Income | YES |
| 18 | income_add | Income | YES |
| 19 | reit_income | Income | YES |
| 20 | international_dividend | Income | YES |
| 21 | bond_income | Fixed income | YES |
| 22 | tax_loss_harvest | Tax | YES |
| 23 | cash_or_stable | Defensive | YES |

21 of 23 strategies are backtest-able with daily bars. The 2 intraday strategies (momentum_scalp, gap_and_go) require minute-level data not yet available.

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

## Dashboard (Rewritten 2026-05-21)

View at `/v2/backtesting` — 7 interactive tabs using recharts:

| Tab | Content |
|-----|---------|
| **Overview** | Win rate by strategy (clickable bars), R-multiple histogram, missed proposals impact |
| **Strategy** | Table with win rate, avg R, total P&L, profit factor, expectancy R, max drawdown. Click row → filters Trades tab |
| **Trades** | All simulated trades with symbol, strategy, entry/exit, P&L, R-multiple. Null strategy_ids handled gracefully |
| **Missed** | Proposals not traded: would-win/would-lose counts, P&L left on table, full table |
| **Results** | Per-run result cards with mini equity curve sparklines. Click card → expand full equity curve with KPIs |
| **Runs** | All backtest runs with type filter (replay_trades, replay_proposals, champion) |
| **Trail Analysis** | Trailing stop simulation results. Per-strategy table: fixed P&L vs 5%/8%/10%/15% trail P&L, optimal %, recommendation. Per-trade detail with LLM-generated lessons |

### Trailing Stop Analysis Engine

**Script:** `scripts/trailing_stop_analyzer.py`

For each closed trade, fetches Alpaca OHLCV bars for the holding period and simulates 4 trailing stop percentages vs the fixed stop actually used. Determines high-water mark, optimal trail %, and improvement.

**API endpoints:**
- `GET /api/v2/backtesting/trailing-stop-analysis` — returns per-trade and per-strategy results
- `POST /api/v2/backtesting/run-trailing-analysis` — triggers background backfill

**Database:** `trailing_stop_analysis` table with per-trade simulation results, `agent_intelligence_rules` for strategy-level recommendations.

**Key findings (2026-05-21, 7 trades):** Average improvement of +3.09% vs fixed stops. EVC (screener): 5% trail would have turned -5.05% loss into +4.94% gain.
