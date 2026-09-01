# PHASE 196A — Intraday MFE for Same-Day Scalps

Status:      HISTORICAL
as_of:       2026-06-02T13:15:12-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · data-quality fix · no execution / no stop / no order / no GO-WAIT changes**

---

## Root cause (two bugs)
After Phase 195, 11 closed trades were still unmeasurable — all **same-day** holds:
1. **Daily bars can't capture intraday excursion.** `fetch_bars` used daily (`1d`) bars; for a
   same-day scalp the date range is one day, and `yfinance`'s `end` is exclusive → empty result;
   even when daily returns a bar, its high/low covers the whole session, not the actual hold window.
2. **The analyzer never loaded `.env`.** Run directly (pipeline/cron), `ALPACA_API_KEY` was absent,
   so every Alpaca bar call (including the new intraday fetch) silently returned `[]` — only
   keyless `yfinance` daily worked. This masked the intraday path entirely.

## Fix
1. **`fetch_intraday_bars(symbol, start_iso, end_iso, "5Min")`** — paginated Alpaca data-API
   fetch over a precise RFC3339 window (read-only market data).
2. **Same-day detection** in `run_mfe_analysis`: when `entry_date == exit_date`, fetch **5-min
   intraday bars over [entry_time, exit_time]** and compute MFE/MAE from them; multi-day holds use
   daily (now with `end + 1 day` to fix the exclusive-end bug). Logs the granularity used.
3. **`_load_env()`** at `main()` start so Alpaca keys are present when run directly.

## Result — full coverage
| Metric | P193 | P194 | P195 | **P196** |
|---|---|---|---|---|
| Bar-measurable MFE | (corrupt) | 3 | 13 | **24 / 24** |
| Unmeasurable | — | 21 | 11 | **0** |
| Gave back profit | — | 3/3 | 9/13 | **20 / 24 (83%)** |
| Profit left on table | — | $415 | $1,176 | **$2,646.64** |

Intraday is also **more accurate** than the daily fallback (counts only the held window): e.g. ANY
intraday left **$532** vs the inflated daily estimate of **$681**.

## Headline learning signal (final, complete, honest)
**20 of 24 closed paper trades (83%) gave back profit, leaving ~$2,646 on the table** — every value
from bar data (intraday for same-day, daily for multi-day), none fabricated. This is the full
quantified case for the profit-protection workstream (Phases 188–196).

## Note
One trade (TMHC) has an ~1-second hold window (entry/exit timestamps essentially equal) → 0
intraday bars → daily fallback, ~$0 excursion. Correct: a 1-second hold has no excursion to measure.

## Guardrail
Read-only on broker (bar fetch = market data). DB writes limited to MFE columns + outcomes table.
No execution, no stop/order changes, no GO/WAIT/strategy mutation, Level 7 prohibited.
