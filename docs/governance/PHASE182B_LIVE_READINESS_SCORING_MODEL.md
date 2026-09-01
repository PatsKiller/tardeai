# Phase 182B: Live Readiness Scoring Model

Status:      HISTORICAL
as_of:       2026-06-01T23:31:03-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Status**: DEFINED — Live trading PROHIBITED

## Scoring Dimensions (100 points total)

### 1. Sample Size (20 points)

| Trades | Points |
|--------|--------|
| < 100 | 0 |
| 100-499 | 4 |
| 500-999 | 8 |
| 1,000-1,999 | 12 |
| 2,000-3,999 | 16 |
| 4,000+ | 20 |

### 2. Journal Quality (15 points)

| Completeness | Points |
|-------------|--------|
| < 80% | 0 |
| 80-89% | 5 |
| 90-94% | 10 |
| 95%+ | 15 |

### 3. Strategy Performance (20 points)

| Metric | Points |
|--------|--------|
| Profit factor < 1.0 | 0 |
| Profit factor 1.0-1.49 | 5 |
| Profit factor 1.5-2.0 | 10 |
| Profit factor 2.0+ | 15 |
| Win rate >= 40% (bonus) | +5 |

### 4. Risk Control (15 points)

| Metric | Points |
|--------|--------|
| Max drawdown > 15% | 0 |
| Max drawdown 10-15% | 5 |
| Max drawdown 5-10% | 10 |
| Max drawdown < 5% | 15 |

### 5. Backtest Alignment (10 points)

| Coverage | Points |
|----------|--------|
| < 50% | 0 |
| 50-74% | 3 |
| 75-89% | 6 |
| 90%+ | 10 |

### 6. Hermes Audit Quality (5 points)

| Coverage | Points |
|----------|--------|
| < 50% | 0 |
| 50-79% | 2 |
| 80%+ | 5 |

### 7. Shadow Learning Accuracy (5 points)

| Evaluated | Points |
|-----------|--------|
| < 100 trades | 0 |
| 100-499 | 2 |
| 500+ | 5 |

### 8. Operational Reliability (5 points)

| Uptime | Points |
|--------|--------|
| < 95% | 0 |
| 95-98% | 2 |
| 99%+ | 5 |

### 9. Alert Quality (3 points)

| False positive rate | Points |
|--------------------|--------|
| > 10% | 0 |
| 5-10% | 1 |
| < 5% | 3 |

### 10. Paper/Live Separation (2 points)

| Verified | Points |
|----------|--------|
| Not verified | 0 |
| Verified | 2 |

## Readiness Thresholds

| Score | Level | Action |
|-------|-------|--------|
| 0-29 | NOT READY | Continue paper trading |
| 30-49 | EARLY | Fix gaps, increase volume |
| 50-69 | DEVELOPING | Address specific weaknesses |
| 70-84 | APPROACHING | Prepare for operator review |
| 85-100 | CANDIDATE | Submit for live-readiness review |

**Current Score: ~8/100** (sample size 0 + journal ~5 + performance ~3 + risk ~0)

## Hard Blockers (Any = FAIL regardless of score)

- Sample size < 2,000
- Any unresolved stop geometry defect
- Paper/live separation not verified
- Level 7 not separately approved
- Operator has not given explicit approval
- Kill switch not tested within 30 days
