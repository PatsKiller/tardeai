# ATM Lifecycle v1.2 — Overdue Decision Workflow Report

**Date:** 2026-05-26  
**Commit:** (pending)  
**Backup:** `backups/pre_v1_2_overdue_decision_workflow_20260526_1703.tgz`  

## Files Changed

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added GET/POST `/api/v2/atm/overdue-decisions` |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Added decision queue section with form |

## Migration

Table `atm_overdue_position_decisions` created with:
- decision_id, operator, lifecycle_id, paper_trade_id, symbol, strategy fields
- decision enum: keep_open, review_for_manual_close, review_stop_or_trailing_adjustment, missing_data_verify_first, strategy_mismatch_investigate
- 5 indexes (trade, lifecycle, symbol, status, created_at)
- Records operator intent only — does NOT trigger execution

## API Endpoints

### GET /api/v2/atm/overdue-decisions

Returns:
- `summary.overdue_count`: 10
- `summary.high_risk_count`: 10
- `summary.stop_missing_count`: 2
- `summary.recorded_decisions`: 0
- `summary.missing_decisions`: 10
- `positions`: array of overdue positions with decision status

### POST /api/v2/atm/overdue-decisions

Accepts: `paper_trade_id`, `symbol`, `decision`, `decision_reason`, `operator_note`

Safety enforcement:
- Rejects any field named execute, close, sell, order, quantity, price, broker_order, cancel, replace
- Decision must be one of 5 allowed values
- Returns: `"Decision recorded only. No order was placed."`
- Writes lifecycle_event with stage=operator_review (non-fatal)

## Overdue Positions

| Symbol | Strategy | Days | Stop | Risk |
|--------|----------|------|------|------|
| GCTS | momentum_scalp | 13d | $1.42 | HIGH |
| GCTS | momentum_scalp | 13d | MISSING | HIGH |
| GCTS | momentum_scalp | 13d | $1.42 | HIGH |
| FLYW | momentum_scalp | 14d | MISSING | HIGH |
| BLBD | earnings_catalyst | 14d | $76.23 | HIGH |
| BLBD | earnings_catalyst | 14d | $80.24 | HIGH |
| INFU | earnings_catalyst | 15d | $7.97 | HIGH |
| EVC | screener | 15d | $7.71 | HIGH |
| MNKD | gap_and_go | 19d | $3.38 | HIGH |
| SMX | momentum_scalp | 19d | $1.23 | HIGH |

## Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| manual_kill_switch_only | true |
| ATM mode | not changed |
| Orders placed | NONE |
| Positions modified | NONE |
| Proposals expired | NONE |

## Frontend Build

`npm run build` — clean, 259ms

## Screenshot

`screenshots/atm_overdue_decision_queue_v1_2.png`

## Rollback

```bash
git revert HEAD
psql -c "DROP TABLE IF EXISTS atm_overdue_position_decisions"
```

## Next Recommended Action

John should review each of the 10 overdue positions via the ATM Control Room and record decisions. After all 10 have decisions, proceed to stale proposal hygiene.
