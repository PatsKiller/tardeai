# SCHWAB-BT-IMPORT-1 — Schwab Backtesting Enabled

**Date:** 2026-05-22

## Key Finding
**119 Schwab closed trades already exist in trade_closed table!**

| Account | Trades | Total PnL | Period |
|---------|--------|-----------|--------|
| schwab_rollover_ira | 74 | $104,125.82 | 2022-11 to 2026-04 |
| schwab_taxable | 37 | -$335.23 | 2025-07 to 2026-02 |
| schwab_roth | 8 | -$1,070.36 | 2022-11 to 2026-02 |

## What Was Done
- Fixed canonical adapter to map trade_closed columns (open_date/close_date/buy_price/sell_price)
- Added schwab_roth to backtest-enabled accounts
- Verified: 130 canonical closed trades flow through adapter (11 Alpaca + 119 Schwab)
- All trades tagged with account_label and broker

## Schwab Execution: DISABLED
- auto_execution_capable=false on all 3 Schwab accounts
- No routing adapter configured
- No orders possible
