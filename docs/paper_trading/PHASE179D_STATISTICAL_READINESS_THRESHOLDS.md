# Phase 179D: Statistical Readiness Thresholds

Status:      HISTORICAL
as_of:       2026-06-01T23:21:01-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Live trading PROHIBITED — Level 7 PROHIBITED

## Readiness Levels

### Level P0 — Not Enough Data

- Fewer than 100 closed usable paper trades
- No statistical conclusions possible
- Focus on infrastructure, field completeness, pipeline quality
- **Current status: HERE (24 trades)**

### Level P1 — Early Signal

- 100–499 usable closed trades
- Preliminary strategy-level patterns visible
- Win rate directional but not conclusive
- Profit factor indicative but high variance
- Begin tracking per-strategy sample sizes
- Minimum per-strategy for any signal: 20 trades

### Level P2 — Developing

- 500–999 usable closed trades
- Strategy-level performance comparison begins
- Drawdown patterns observable
- Hold time distributions meaningful
- Begin shadow-vs-actual scoring comparison
- Minimum per active strategy: 50 trades

### Level P3 — Meaningful

- 1,000–1,999 usable closed trades
- Win rate confidence intervals narrow enough for comparison
- Profit factor stable across 30-day windows
- Strategy attribution statistically significant
- Hermes audit coverage should be >= 80%
- Backtest comparison coverage should be >= 70%
- Minimum per active strategy: 100 trades

### Level P4 — Strong Paper Evidence

- 2,000–3,999 usable closed trades
- Journal completeness >= 95%
- Exit reason completeness >= 98%
- Strategy attribution >= 98%
- Win rate confidence interval < +/- 3%
- Profit factor stable across rolling 60-day windows
- Drawdown within defined policy limits
- Hermes audit coverage >= 90%
- Backtest comparison coverage >= 85%
- Learning loop linkage >= 85%
- Shadow scoring evaluated for at least 500 trades
- No unresolved stop geometry defects
- Minimum per active strategy: 200 trades

### Level P5 — Live-Readiness Candidate

- 4,000+ usable closed trades
- Journal completeness >= 95%
- Exit reason completeness >= 98%
- Stop type completeness >= 95%
- Hold time completeness >= 95%
- Strategy attribution >= 98%
- No unresolved stop geometry defects
- No unresolved broker/order defects
- Backtest/live alignment proven (< 15% divergence)
- Hermes learning loop active and verified
- Shadow-vs-actual scoring evaluated
- Max drawdown within policy (< 10% of paper account)
- Profit factor >= 1.5 across all active strategies (aggregate)
- Win rate >= 40% across all active strategies (aggregate)
- Expectancy positive across rolling 90-day windows
- Operational reliability >= 99% (cron/timer success rate)
- Alert quality verified (< 5% false positive rate)
- Paper/live separation verified and tested
- **Level 7 remains PROHIBITED until separately approved by operator**

## Data Quality Requirements at Each Level

| Field | P1 | P2 | P3 | P4 | P5 |
|-------|----|----|----|----|-----|
| strategy_id | 95% | 98% | 99% | 99% | 99% |
| entry_price | 95% | 98% | 99% | 99% | 99% |
| exit_price | 80% | 90% | 95% | 98% | 99% |
| exit_reason | 80% | 90% | 95% | 98% | 99% |
| stop_loss | 90% | 95% | 98% | 99% | 99% |
| target | 90% | 95% | 98% | 99% | 99% |
| dollar_size | 95% | 98% | 99% | 99% | 99% |
| dollar_risk | 80% | 90% | 95% | 98% | 99% |
| pnl | 80% | 90% | 95% | 98% | 99% |
| r_multiple | 60% | 75% | 85% | 95% | 98% |
| hold_time | 50% | 75% | 90% | 95% | 98% |
| catalyst | 40% | 60% | 75% | 85% | 90% |
| market_regime | 70% | 80% | 90% | 95% | 98% |
| MAE/MFE | 50% | 65% | 80% | 90% | 95% |
| post_analyzed | 20% | 40% | 60% | 80% | 90% |

## Current vs Required (P1 entry)

| Field | Current | P1 Req | Gap |
|-------|---------|--------|-----|
| Closed trades | 24 | 100 | -76 |
| strategy_id | 100% | 95% | PASS |
| exit_reason | 100% | 80% | PASS |
| exit_price | 75% | 80% | -5% |
| pnl | 75% | 80% | -5% |
| hold_time | 8% | 50% | -42% CRITICAL |
| r_multiple | 67% | 60% | PASS |
| catalyst | 54% | 40% | PASS |
| Hermes linkage | 0% | N/A | — |
| Backtest linkage | 0% | N/A | — |

## Promotion Rules

- No level can be promoted without **operator review and approval**
- Level promotion requires sustained performance across at least **2 rolling windows**
- Any strategy below minimum sample count is excluded from level assessment
- Aggregate metrics must meet threshold with and without best-performing strategy
- No strategy with negative expectancy over 100+ trades qualifies at P4+
- Level demotion triggers if rolling metrics fall below threshold for 2 consecutive windows
