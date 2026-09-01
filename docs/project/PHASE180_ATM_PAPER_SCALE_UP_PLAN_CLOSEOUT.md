# Phase 180: ATM Paper Trading Scale-Up Plan — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-01T23:26:38-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Status**: COMPLETE

## Results

### Paper-Only Guardrails: VERIFIED

- ALPACA_MODE=paper: YES
- Live endpoint blocked in code: YES
- LIVE_TRADING_ENABLED: NOT SET (false)
- LLM_DISABLE_LIVE_EXECUTION: true
- Live trading gate: `allowed=False, mode=PAPER`
- Kill switch available: YES (multiple mechanisms)

### Account Size: $100,000 (Alpaca paper)

### Current ATM Configuration

| Setting | Current | Stage 1 (Proposed) |
|---------|---------|-------------------|
| Max concurrent | 6 | 10 |
| Max new/day | 3 | 25 |
| Max % per trade | 10% | 5% |
| Evaluation cadence | 15 min | 15 min |
| Same-day skip | momentum_scalp, gap_and_go | NONE (allow all) |

### Daily Trade Ramp Plan

| Stage | Trades/Day | Entry | Duration |
|-------|-----------|-------|----------|
| Stage 1 | 25-50 | Now | Week 1-2 |
| Stage 2 | 50-100 | After 100 trades | Week 3-4 |
| Stage 3 | 100-200 | After 500 trades | Week 5-8 |
| Stage 4 | 200+ | After 1,500 trades | Week 9+ |

### Max Paper Trade Size

- Stage 1: $5,000 (5% of $100K)
- Stage 2: $3,000 (3%)
- Stage 3: $2,000 (2%)
- Stage 4: $1,500 (1.5%)

### Max Concurrent Positions

- Stage 1: 10
- Stage 2: 15
- Stage 3: 20
- Stage 4: 25

### Max Daily Paper Loss

- All stages: $5,000 (5% of paper account)
- Per-account: $2,500 (Stage 1), $5,000 (Stage 2+)

### Journal Completeness Required

- Strategy: >= 98%
- Exit reason: >= 95%
- PnL: >= 95%
- Hold time: >= 90%
- Stop loss: >= 95%

### Safety Confirmations

- Level 7: **PROHIBITED**
- Live broker access: **ZERO**
- All trades paper-only: **CONFIRMED**
- Kill switch available: **YES**

### Next Gate

Phase 181: Paper Trade Closed-Loop Learning Validation

## Deliverables

- [x] Phase 180A: `docs/atm/PHASE180A_ATM_CURRENT_CONFIGURATION_AUDIT.md`
- [x] Phase 180B: `docs/atm/PHASE180B_ATM_PAPER_SCALE_UP_RISK_POLICY.md`
- [x] Phase 180C: `docs/atm/PHASE180C_ATM_PAPER_VOLUME_RAMP_SCHEDULE.md`
- [x] Phase 180D: `docs/atm/PHASE180D_ATM_PAPER_ONLY_GUARDRAILS_REPORT.md`
- [x] Phase 180E: `docs/atm/PHASE180E_ATM_PAPER_SCALE_DASHBOARD_REPORT.md`
- [x] Phase 180F: This closeout document
