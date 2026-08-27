# ATM Lifecycle v1.4 — Manual Close Review Report

**Date:** 2026-05-26  
**Backup:** `backups/pre_v1_4_manual_close_review_20260526_1737.tgz`  

## What Was Built

| Deliverable | Status |
|-------------|--------|
| `atm_manual_close_review_decisions` table | CREATED |
| `GET /api/v2/atm/manual-close-review` | LIVE — 6 positions, 0 resolved |
| `POST /api/v2/atm/manual-close-review` | LIVE — records review only |
| Manual Close Review panel in ATMControlRoom.tsx | LIVE — 6 rows with Review button |

## Positions in Manual Close Review

| Trade | Symbol | Strategy | Days | Stop | Shares |
|-------|--------|----------|------|------|--------|
| #1 | SMX | momentum_scalp | 19d | $1.23 | 1550 |
| #2 | MNKD | gap_and_go | 19d | $3.38 | 561 |
| #4 | EVC | screener | 15d | $7.71 | 390 |
| #9 | INFU | earnings_catalyst | 15d | $7.97 | 357 |
| #20 | GCTS | momentum_scalp | 13d | $1.42 | 1875 |
| #23 | GCTS | momentum_scalp | 13d | MISSING | 1875 |

## Safety

- ALPACA_MODE=paper, LLM_DISABLE=true, no orders placed, no positions modified
- POST rejects execution-like fields (execute, sell, close_now, quantity, price, etc.)
- Returns: "Review decision recorded only. No order was placed."

## Screenshot

`screenshots/manual_close_review_v1_4.png`

## Rollback

```bash
git revert HEAD
psql -c "DROP TABLE IF EXISTS atm_manual_close_review_decisions"
```
