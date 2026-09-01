# Phase 186A: Stage 1 Pipeline Pre-Run Safety

Status:      HISTORICAL
as_of:       2026-06-02T00:21:42-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02
**Mode**: PAPER ONLY

## Safety Verification

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| ALPACA_MODE | paper | paper | PASS |
| ENABLE_ALPACA_PAPER | true | true | PASS |
| LIVE_TRADING_ENABLED | unset/false | NOT SET | PASS |
| LLM_DISABLE_LIVE_EXECUTION | true | true | PASS |
| Paper endpoint | paper-api.alpaca.markets | paper-api.alpaca.markets | PASS |
| Live endpoint blocked | RuntimeError if non-paper | Code line 48-49 | PASS |
| Live trading gate | allowed=False | allowed=False, mode=PAPER | PASS |
| Level 7 | PROHIBITED | PROHIBITED | PASS |

## Stage 1 Config Verification

| Setting | Expected | Actual | Status |
|---------|----------|--------|--------|
| max_concurrent | 10 | 10 | PASS |
| max_new_per_day | 25 | 25 | PASS |
| max_pct_per_trade | 0.05 (5%) | 0.05 | PASS |
| max_pct_per_strategy | 20 | 20 | PASS |
| max_pct_per_sector | 30 | 30 | PASS |
| daily_loss_pause | 2.5% | 2.5 | PASS |
| momentum_scalp | ALLOWED | Not in skip list | PASS |
| gap_and_go | SKIPPED | In skip list | PASS |
| B-1 observation | disabled | false | PASS |

## Account Status

| Metric | Value |
|--------|-------|
| Account status | ACTIVE |
| Equity | $102,107.13 |
| Buying power | $376,907.08 |
| Cash | $85,759.81 |
| Open paper positions | 6 |
| Open positions (Alpaca) | 6 (AGNC, ANY, CMCSA, NWG, SNOW, TMHC) |
| Today new trades | 0 |
| Available slots | 4 (10 max - 6 open) |
| Kill switch | Available (manual_kill_switch_only=true) |

## Result: ALL CHECKS PASS — safe to proceed
