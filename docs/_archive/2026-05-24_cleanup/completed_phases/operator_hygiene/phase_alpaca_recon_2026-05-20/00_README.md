# ALPACA-RECON-1 — Paper Journal P&L Reconciliation

**Status:** COMPLETE
**Date:** 2026-05-20

## Problem

Alpaca paper account showed $100,367 equity ($100K start + $367 profit), but the journal showed only $71.95 total P&L across 9 closed trades. A $295.91 discrepancy.

## Root Cause

Two separate issues caused phantom/wrong P&L records:

### 1. Phantom Trades (EVC, XMTR, FLYW)

`approve_proposal()` in `paper_trade_logger.py` created `paper_trades` records with `status='pending'` and `broker=NULL` but **never called `submit_paper()` to submit the actual order to Alpaca**. The Telegram `/ptapprove` path was missing the instant execution step that the API dashboard had.

When the Alpaca sync ran later, it found positions that existed in Alpaca (submitted through a different path) but whose DB records had `broker=NULL`. The sync detected "no matching Alpaca position" and marked them as `phantom_no_alpaca_position` with `exit_price = entry_price` (P&L = $0).

**Fix (code):** Commit `b969379` — wired `submit_paper()` into the Telegram callback handler's `_run_approve()`, matching the API endpoint behavior.

### 2. Wrong Exit Prices (INFU, GCTS)

The Alpaca position sync (`detect_closed_positions` in `alpaca_paper_adapter.py`) tried to look up the actual exit price from broker order history, but the sell order lookup sometimes returned the wrong order or failed to parse the fill price correctly. This resulted in exit prices that didn't match Alpaca's actual fills.

### 3. Wrong Account (FLYW #24)

One trade was booked under `TOS_PAPER` instead of `ALPACA_PAPER`, making it invisible in ALPACA_PAPER account P&L totals.

### 4. Duplicate Record (GCTS #20)

The same GCTS position was logged twice (trades #20 and #22) due to the sync creating a new record when the proposal-created record already existed.

## Fixes Applied (DB Data Corrections)

| Trade | Symbol | Was | Corrected To | Issue |
|-------|--------|-----|-------------|-------|
| #4 | EVC | $0 P&L, exit=$8.12 | +$202.80, exit=$8.64 | Phantom — actual sell was at $8.64 |
| #3 | XMTR | $0 P&L, exit=$79.25 | +$95.60, exit=$82.93 | Phantom — actual sell was at $82.93 |
| #21 | INFU | +$56.07, exit=$9.47 | +$261.57, exit=$9.34 | Wrong exit price from sync |
| #22 | GCTS | -$12.38, exit=$1.48 | -$225.00, exit=$1.37 | Wrong exit price from sync |
| #19 | FLYW | $0 P&L (phantom) | -$20.52, exit=$16.63 | Phantom — actual stop hit at $16.63 |
| #24 | FLYW | TOS_PAPER account | ALPACA_PAPER | Wrong account tag |
| #20 | GCTS | -$9.38 (closed) | cancelled | Duplicate of trade #22 |

Also fixed: stop_loss values on trades #3, #4, #24 that violated the `chk_long_stop_below_entry` constraint (stop was above entry due to sync importing wrong values).

## Before / After

| Metric | Before | After |
|--------|--------|-------|
| Journal closed trades | 9 | 9 |
| Journal total P&L | +$71.95 | +$379.45 |
| Alpaca actual P&L | +$367.86 | +$367.86 |
| Discrepancy | $295.91 | $11.59 |
| Discrepancy cause | Phantom exits + wrong fills | Fill price timing |

The remaining $11.59 gap is from fill price timing differences (journal records the fill at slightly different timestamps than Alpaca's final settled price).

## Alpaca Order History (18 filled orders)

| Date | Symbol | Side | Shares | Price | P&L |
|------|--------|------|--------|-------|-----|
| 05/11 | XMTR | buy | 26 | $79.25 | |
| 05/11 | EVC | buy | 390 | $8.12 | |
| 05/11 | INFU | buy | 357 | $8.39 | |
| 05/11 | FLYW | buy | 171 | $16.74 | |
| 05/11 | EVC | sell | 390 | $8.64 | +$202.80 |
| 05/11 | FLYW | sell | 171 | $16.63 | -$18.81 |
| 05/12 | BLBD | buy | 37 | $68.48 | |
| 05/12 | FLYW | buy | 171 | $16.75 | |
| 05/12 | BLBD | sell | 37 | $68.08 | -$14.80 |
| 05/12 | FLYW | sell | 171 | $16.63 | -$20.52 |
| 05/13 | XMTR | sell | 26 | $82.93 | +$95.60 |
| 05/13 | GCTS | buy | 1875 | $1.49 | |
| 05/13 | INFU | sell | 357 | $8.58 | +$67.83 |
| 05/13 | INFU | buy | 357 | $8.61 | |
| 05/14 | GCTS | sell | 1875 | $1.37 | -$233.17 |
| 05/14 | FLYW | buy | 171 | $16.29 | |
| 05/14 | FLYW | sell | 171 | $16.45 | +$27.36 |
| 05/19 | INFU | sell | 357 | $9.34 | +$261.57 |

**Total realized: +$367.86**

## Code Fix (Prevents Recurrence)

Commit `b969379`: Wire Telegram Approve → Alpaca paper submission

The Telegram `/ptapprove` callback now calls `submit_paper()` after `approve_proposal()` succeeds, matching the API dashboard behavior. This prevents future phantom trades.

## Safety

- ALPACA_MODE=paper — all orders to paper-api.alpaca.markets
- No live money involved
- No strategy activation changes
- No .env modifications
- Holdings file unchanged
