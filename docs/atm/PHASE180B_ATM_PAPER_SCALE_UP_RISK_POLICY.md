# Phase 180B: ATM Paper Scale-Up Risk Policy

Status:      HISTORICAL
as_of:       2026-06-01T23:26:38-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Level 7 PROHIBITED

## Objective

Scale paper trade volume from ~4 trades/day to 25-200+ trades/day using the full $100K Alpaca paper account, while maintaining data quality and risk discipline.

## Non-Negotiable Rules

1. Paper account ONLY — `ALPACA_MODE=paper`
2. No live broker access
3. No Level 7
4. `LLM_DISABLE_LIVE_EXECUTION=true`
5. Every trade must have: strategy, entry, stop, target, reason
6. Every closed trade must have: exit_reason, pnl, hold_time

## Position Limits (Scaled)

| Setting | Current | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|---------|---------|---------|---------|---------|---------|
| Max concurrent | 6 | 10 | 15 | 20 | 25 |
| Max new/day | 3 | 25 | 50 | 100 | 200 |
| Max % per trade | 10% | 5% | 3% | 2% | 1.5% |
| Max $ per trade | $10K | $5K | $3K | $2K | $1.5K |
| Max % per strategy | 25% | 20% | 15% | 15% | 15% |
| Max % per sector | 35% | 30% | 25% | 25% | 25% |

**Key insight**: As volume scales up, position size must scale DOWN to avoid paper account exhaustion and to generate more diverse trade samples.

## Per-Trade Risk

| Setting | Value |
|---------|-------|
| Max risk per trade | 1% of paper account ($1,000) |
| Target risk per trade | 0.5% of paper account ($500) |
| Max stop distance | 5% from entry |
| Min R:R | 1.5:1 |
| Stop required | YES (always) |
| Target required | YES (always) |

## Daily Limits

| Setting | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|---------|---------|---------|---------|---------|
| Max new trades/day | 25 | 50 | 100 | 200 |
| Max daily $ loss | $2,500 (2.5%) | $5,000 (5%) | $5,000 (5%) | $5,000 (5%) |
| Max consecutive losses | 5 (pause 30min) | 7 (pause 30min) | 10 (pause 30min) | 10 (pause 30min) |
| Max daily $ notional | $50K | $75K | $100K | $150K |

## Strategy Distribution Policy

Goal: Generate trades across ALL active strategies, not just momentum_scalp.

| Strategy | Min % of daily trades | Target trades/week |
|----------|----------------------|-------------------|
| momentum_scalp | 15% | 25-50 |
| swing_breakout | 15% | 25-50 |
| swing_trade | 15% | 25-50 |
| earnings_catalyst | 10% | 15-25 |
| gap_and_go | 10% | 15-25 |
| fib_retracement_bounce | 10% | 10-20 |
| dividend_growth_compounder | 5% | 5-15 |
| earnings_pre_buildup | 5% | 5-15 |
| recovery_watch | 5% | 5-10 |
| Others | 10% | 5-10 |

## Data Quality Gates

Before any stage promotion:

| Requirement | Threshold |
|-------------|-----------|
| Strategy tag present | >= 98% |
| Entry price present | >= 99% |
| Exit reason present (closed) | >= 95% |
| PnL computed (closed) | >= 95% |
| Hold time computed (closed) | >= 90% |
| Stop loss present | >= 95% |
| R multiple computed (closed) | >= 85% |

**If data quality drops below threshold, HALT volume increase until fixed.**

## Symbol Universe

- All symbols from active screeners (Finviz, TA scan results)
- No penny stocks (price < $2)
- Min average volume 100K shares
- Diversified across sectors
- No more than 3 concurrent positions in same symbol

## Prohibited Actions

- No live trading
- No live broker API calls
- No Level 7 automation
- No strategy config changes without shadow validation
- No manual price overrides
- No bypassing stop requirements
- No bypassing risk gate
