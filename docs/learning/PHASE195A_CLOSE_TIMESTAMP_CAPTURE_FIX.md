# PHASE 195A — Close-Timestamp Capture Fix

Status:      HISTORICAL
as_of:       2026-06-02T13:07:10-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · data-quality fix · no execution / no stop / no order / no GO-WAIT changes**

---

## Root cause
Bar-based MFE needs both `entry_time` and `exit_time`. The dominant close paths set `closed_at=NOW()`
but **never `exit_time`**:
| Path | set closed_at? | set exit_time? |
|---|---|---|
| `open_trade_monitor.py:296` (target/stop hit) | ✅ | ❌ |
| `open_trade_monitor.py:646` (critical news) | ✅ | ❌ |
| `paper_trade_monitor.py:300` (target hit) | ✅ | ❌ |
| `paper_trade_monitor.py:173`/`:451` (phantom/integrity) | ✅ | ❌ |
| `alpaca_paper_adapter.py:239` (broker sell fill) | ✅ | ✅ (the only one) |

Result: only **5 of 24** closed trades had `exit_time`, so only 5 were analyzable → MFE/give-back
unmeasurable for most of the book.

## Fix
1. **Close paths (forward):** added `exit_time=COALESCE(exit_time, NOW())` and
   `entry_time=COALESCE(entry_time, filled_at, created_at)` to the 4 monitor close paths.
2. **Analyzer (robust):** `trade_execution_analyzer.py` now derives its bar-date range from
   `COALESCE(entry_time, filled_at, broker_filled_at, submitted_at, created_at)` and
   `COALESCE(exit_time, broker_closed_at, closed_at)` — so a trade is analyzable even if a close
   path forgot to set the column.
3. **Backfill:** populated `entry_time`/`exit_time` on all 24 closed trades from best-available
   broker/lifecycle timestamps → **24/24 now have both** (was 19/5).

## Result
| Metric | Before (Phase 194) | After (Phase 195) |
|---|---|---|
| Closed trades with entry+exit time | 5 / 24 | **24 / 24** |
| Bar-measurable MFE | 3 | **13** |
| Of measurable, gave back profit | 3/3 | **9 / 13 (69.2%)** |
| **Total profit left on table** | $414.68 | **$1,176.40** |

A robust learning signal now: across 13 measurable closed trades, **69% gave back profit**, leaving
~$1,176 on the table collectively — the quantified case for profit protection, on real bar data.

## Remaining gap (Phase 196 candidate)
**11 trades remain unmeasurable** — they are **same-day** trades (entry date == exit date), and the
analyzer fetches **daily** bars over a zero-width range (`yfinance` returns empty). Intraday MFE for
same-day scalps needs **intraday (minute/hour) bars**. That is an analyzer data-source limitation,
not a timestamp bug — deferred to Phase 196.

## Guardrail
Read-only on broker (bar fetch = market data). DB writes limited to timestamp + MFE columns. No
execution, no stop/order changes, no GO/WAIT/strategy mutation, Level 7 prohibited.
