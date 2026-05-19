# SCALP-COUNT-2 Post-Restart Validation

**Date:** 2026-05-19

## API Count Reconciliation

| Field | Value |
|-------|-------|
| Run GO | 2 |
| Run WAIT | 5 |
| Run NO GO | 62 |
| Scanned this run | 69 |
| **Reconcile** | **2 + 5 + 62 = 69 OK** |
| Universe | 1421 (separate) |

## Regression

| Check | Result |
|-------|--------|
| Canonical regression | 11/11 PASS |
| Full unittest discovery | 475/475 PASS |
| Frontend build | Clean (216ms) |
| Telegram poller | Active — firing at :58, :00, :02 |
| Q-1 quote refresh | Active — firing, 0 targets |
| WATCH-2 maturity alerts | Active — cron block present |
| GOV-1 | Active |
| Phase 9C | Active |

## Cron Blocks Present

- GOV-1
- Phase 9C
- Q-1
- WATCH-2

## Safety

| Check | Pre | Post |
|-------|-----|------|
| ALPACA_MODE | paper | paper |
| LLM_DISABLE | true | true |
| Holdings | $1,194,457 | $1,194,457 |
| .env staged | NO | NO |
| Trades | 0 | 0 |
