# Open Trades False-Positive Root Cause & Fix (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T15:32:17-04:00
Measured at: efcc51365 / not measured

## Symptom
v3 Open Trades showed ~152 "positions" incl sold-out **AXTI**, 149 zero-share rows, numeric CUSIPs,
duplicate lots, entry 0.00 — for accounts the operator no longer holds.

## Root cause
`open_trades_intelligence.build_intelligence()` based positions on `trades WHERE lower(status)='open'`.
That ledger contains stale/unreconciled lots: AXTI had **5 `status='open'` rows, all `shares=0`**
(real position closed). `trades.status='open'` is NOT a current-position source.
- BEFORE: total 152 · zero_shares 149 · numeric CUSIPs 2 · AXTI 5 rows · dup(acct,sym) 29.

## Source of truth (proof AXTI not held)
- `data/portfolios/state/holdings.json` (canonical, repriced; used by `/api/v2/portfolio/holdings`) —
  current holdings only. **AXTI is NOT in holdings.json.** Schwab/fidelity = 44 real holdings.
- Alpaca paper = `paper_trades WHERE status='open'` (canonical paper ledger; NWG/AGNC/TMHC).

## Fix (read-only)
Base universe rebuilt:
- real accounts ← `holdings.json` `holdings` (skip is_cash, shares<=0, market_value<=0, numeric CUSIP;
  paper accounts skipped here — sourced from paper_trades to stay consistent).
- alpaca paper ← `paper_trades` open, aggregated by symbol.
- `trades`/`paper_trades` used ONLY for enrichment (lot_count, entry dates, stop/target, strategy).
- Stale `trades.status='open'` rows whose (account,symbol) is NOT in current holdings → `excluded_items`
  (reason `not_in_current_holdings`), e.g. AXTI — never shown as a position.
- New summary fields: `source_of_truth`, `excluded_stale_trade_rows`, `excluded_zero_share_rows`,
  `excluded_non_ticker_rows`, `excluded_cash_rows`. Frontend shows a diagnostics expander.

## After
- total **47** (44 holdings + 3 paper) · zero-share 0 · numeric CUSIP 0 · dup 0 · AXTI excluded ·
  stale rows excluded **80** · strict JSON (no bare NaN/Inf). uPnL ~$337,923.
- AXTI in excluded_items: `{account: schwab_rollover_ira, symbol: AXTI, reason: not_in_current_holdings, stale_trade_count, source: trades_status_open}`.

## Safety / no-write
Module performs zero writes (grep INSERT/UPDATE/DELETE = 0). Hermes/news/technicals read-only. No
broker/order/stop/GO-WAIT/strategy/live changes. Phase 205 untouched. Regression:
`scripts/validate_open_trades_intelligence.py` (8/8). Screenshot: /tmp/opentrades_fixed.png.
