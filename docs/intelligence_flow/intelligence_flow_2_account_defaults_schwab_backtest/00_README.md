# INTELLIGENCE-FLOW-2 — Fix Account Defaults + Schwab Backtesting

**Date:** 2026-05-22

## Fixes Applied

1. **ATM auto-approver:** Removed `"alpaca_paper"` fallback. Now fails closed
   with `account_resolution_missing` if proposal has no target_account.

2. **Auto-proposal generator:** Replaced hardcoded `"ALPACA_PAPER"` with
   `_resolve_proposal_account()` that reads from ATM config.

3. **Proposal schema:** Dropped `DEFAULT 'TOS_PAPER'` from proposed_account column.

4. **Canonical closed trade adapter:** New script extracts account-agnostic
   closed trades from paper_trades + trade_closed for backtesting.

## Schwab Backtesting Status

- Schwab accounts (rollover_ira, roth_ira, taxable): backtest_enabled=true
- Schwab execution: DISABLED (auto_execution_capable=false, no routing adapter)
- Schwab closed trades found: 0 (no imports yet — schwab_reconstructor exists)
- Canonical adapter ready to ingest when Schwab data is imported

## What Was NOT Changed

- No trading behavior changed
- No orders/trades/approvals created
- No Schwab execution enabled
- No strategy activation changed
- No YAML/Finviz/env changed
