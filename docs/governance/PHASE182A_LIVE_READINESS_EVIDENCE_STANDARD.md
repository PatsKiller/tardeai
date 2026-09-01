# Phase 182A: Live-Readiness Evidence Standard

Status:      HISTORICAL
as_of:       2026-06-01T23:31:03-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Status**: DEFINED — Live trading PROHIBITED

## Purpose

This document defines the minimum evidence required before any future live automation discussion can even begin. Meeting these requirements does NOT automatically enable live trading — it merely qualifies the system for operator review.

## Minimum Requirements

### Sample Size

- 2,000+ usable closed paper trades for preliminary review
- 4,000+ usable closed paper trades for stronger evidence
- At least 100 trades per active strategy (or strategy excluded)
- Minimum 50 trades per strategy for any statistical conclusion

### Data Quality

| Field | Minimum |
|-------|---------|
| Journal completeness (aggregate) | >= 95% |
| Strategy attribution | >= 98% |
| Exit reason completeness | >= 98% |
| Stop type completeness | >= 95% |
| Hold time completeness | >= 95% |
| PnL completeness | >= 98% |
| R multiple completeness | >= 95% |
| Entry price completeness | >= 99% |
| Exit price completeness | >= 98% |

### Performance

| Metric | Minimum |
|--------|---------|
| Aggregate win rate | >= 40% |
| Aggregate profit factor | >= 1.5 |
| Positive expectancy | >= 90-day rolling windows |
| Max drawdown | <= 10% of paper account |
| No strategy with negative expectancy over 100+ trades |
| Performance consistent across market regimes |

### Learning Loop

| Requirement | Minimum |
|-------------|---------|
| Hermes audit coverage | >= 95% of closed trades |
| Backtest comparison coverage | >= 90% |
| Learning loop linkage | >= 90% |
| Shadow scoring evaluated | >= 500 trades |
| Post-trade analysis coverage | >= 80% |

### Operational

| Requirement | Minimum |
|-------------|---------|
| System uptime | >= 99% (cron/timer success) |
| No unresolved stop geometry defects | 0 |
| No unresolved broker/order defects | 0 |
| No uncontrolled live API keys | 0 |
| Paper/live separation verified | YES |
| Alert quality (false positive rate) | < 5% |
| Kill switch tested | Within 30 days |

### Governance

| Requirement | Minimum |
|-------------|---------|
| Operator explicit approval | REQUIRED |
| Level 7 prohibition review | SEPARATE PROCESS |
| Six-month minimum paper validation period | ENFORCED |
| All strategies individually reviewed | REQUIRED |
| Risk policy documented and reviewed | REQUIRED |
| Emergency stop procedure tested | REQUIRED |
