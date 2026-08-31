# Phase 180C: ATM Paper Trade Volume Ramp Schedule

Status:      HISTORICAL
as_of:       2026-06-01T23:26:38-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Level 7 PROHIBITED

## Ramp Stages

### Stage 1: Validation (Week 1-2)

**Target**: 25-50 paper trades/day

**Config Changes**:
- `max_new_per_day`: 3 → 25
- `max_concurrent`: 6 → 10
- `max_pct_per_trade`: 10% → 5%
- Remove `same_day_skip_strategies` for momentum_scalp (allow intraday)

**Entry Criteria**:
- ATM currently active and healthy
- hold_time_min computation fixed (currently 8%)
- exit_price and pnl computation verified for all close paths

**Exit Criteria (promote to Stage 2)**:
- 100+ closed trades accumulated
- Journal completeness: exit_reason >= 95%, pnl >= 95%
- No stop geometry defects in last 50 trades
- System uptime >= 99% (cron/timer success)

**Rollback Criteria**:
- Data quality < 90% on any critical field
- > 3 stop geometry defects
- Paper account equity < $90K (10% loss)
- Kill switch fires

**Daily Monitoring**:
- Run `python scripts/paper_trade_statistics.py` at EOD
- Review proposal → approval → fill → close pipeline
- Check journal completeness dashboard

---

### Stage 2: Scale (Week 3-4)

**Target**: 50-100 paper trades/day

**Config Changes**:
- `max_new_per_day`: 25 → 50
- `max_concurrent`: 10 → 15
- `max_pct_per_trade`: 5% → 3%
- Enable all strategies including overnight/swing for paper
- ATM evaluation frequency: 15min → 10min

**Entry Criteria**:
- Stage 1 exit criteria met
- 100+ closed trades
- hold_time populated >= 80%
- R multiple populated >= 75%

**Exit Criteria (promote to Stage 3)**:
- 500+ closed trades accumulated
- Strategy distribution: >= 5 strategies with 30+ trades each
- Journal completeness: all critical fields >= 90%
- Hermes audit pipeline connected (even if 0% coverage initially)

**Rollback Criteria**:
- Data quality regression below Stage 1 thresholds
- Max daily loss triggered 3+ times
- Fill rate < 70% (proposals approved but not filled)
- Paper account equity < $85K

---

### Stage 3: Diversification (Week 5-8)

**Target**: 100-200 paper trades/day

**Config Changes**:
- `max_new_per_day`: 50 → 100
- `max_concurrent`: 15 → 20
- `max_pct_per_trade`: 3% → 2%
- Enable strategy-specific proposal generation cadence
- Run screeners on expanded universe

**Entry Criteria**:
- Stage 2 exit criteria met
- 500+ closed trades
- >= 5 strategies with 50+ closed trades each
- Hermes audit pipeline operational

**Exit Criteria (promote to Stage 4)**:
- 1,500+ closed trades
- All active strategies with 100+ trades
- Journal completeness >= 95% all fields
- Hermes audit coverage >= 50%
- Backtest comparison operational

**Rollback Criteria**:
- Any critical field completeness < 85%
- Profit factor < 0.5 over rolling 200 trades
- Win rate < 25% over rolling 200 trades

---

### Stage 4: Statistical Power (Week 9+)

**Target**: 200+ paper trades/day

**Config Changes**:
- `max_new_per_day`: 100 → 200
- `max_concurrent`: 20 → 25
- `max_pct_per_trade`: 2% → 1.5%
- Full strategy coverage required

**Entry Criteria**:
- Stage 3 exit criteria met
- 1,500+ closed trades
- Data quality >= 95%

**Exit Criteria (target achieved)**:
- 2,000+ usable closed trades → P4 readiness
- 4,000+ usable closed trades → P5 candidate
- Journal completeness >= 95%
- Exit reason completeness >= 98%
- Strategy attribution >= 98%

**Kill Switch**:
- Paper account equity < $80K → pause and investigate
- Data quality < 90% → halt new trades, fix pipeline
- > 10 consecutive losses → 1 hour pause

---

## Estimated Timeline

| Milestone | Est. Date | Trades |
|-----------|-----------|--------|
| Stage 1 start | 2026-06-02 | 0 → 100 |
| Stage 1 → 2 | ~2026-06-09 | 100+ |
| Stage 2 → 3 | ~2026-06-23 | 500+ |
| P3 (1,000) | ~2026-07-07 | 1,000 |
| P4 (2,000) | ~2026-07-21 | 2,000 |
| P5 (4,000) | ~2026-08-18 | 4,000 |

*Estimates assume average fill rates and market conditions. Actual timeline may vary.*

## Data Quality Monitoring

At each stage, the following must be verified daily:

```
python scripts/paper_trade_statistics.py
```

Dashboard automatically shows readiness level on Paper Trading Status page.
