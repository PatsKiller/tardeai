# PHASE 195 — Close-Timestamp Capture Fix — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T13:07:10-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~13:00–13:20 ET · Alpaca **paper** only · data-quality; no execution

---

## What shipped
- **Close-path fix:** 4 monitor close paths now persist `exit_time` (+ `entry_time` fallback):
  `open_trade_monitor.py:296,646`, `paper_trade_monitor.py:173,300,451`.
- **Analyzer robustness:** `trade_execution_analyzer.py` derives bar dates from COALESCE of
  best-available timestamps — never blocked by a missing `exit_time` again.
- **Backfill:** all 24 closed trades now have entry+exit time; re-ran analyzer → 13 bar-measurable;
  reconciler refreshed.

## Impact
| Metric | Before | After |
|---|---|---|
| Closed trades with entry+exit time | 5/24 | **24/24** |
| Bar-measurable MFE | 3 | **13** |
| Gave back profit (of measurable) | 3/3 | **9/13 (69%)** |
| Profit left on table | $414.68 | **$1,176.40** |

## Closeout fields
- **Phase 195 complete:** ✅ YES
- **Root cause found + fixed:** ✅ YES (close paths set closed_at but not exit_time)
- **Forward fix (close paths):** ✅ 4 paths persist exit_time/entry_time
- **Robust analyzer date derivation:** ✅ YES (COALESCE fallbacks)
- **Backfill:** ✅ 24/24 timestamped; measurable 3→13
- **Reconciler/endpoint refreshed:** ✅ 69% give-back, $1,176 left on table
- **No execution / no stop changes / no orders:** ✅ YES
- **Live trading:** ZERO · **Live endpoint:** blocked · **GO/WAIT mutation:** ZERO ·
  **Strategy mutation:** ZERO · **Level 7:** PROHIBITED
- **Next recommended gate:** **Phase 196 — intraday MFE for same-day trades** (11 remaining
  unmeasurable are same-day scalps; analyzer fetches daily bars over a zero-width range → fetch
  intraday minute/hour bars for same-day holds). Then accumulate advised-trade outcomes for
  threshold tuning and surface outcomes in the v3 Journal/Learning hub.

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no stops moved/cancelled,
no strategy configs changed, no GO/WAIT logic changed, Level 7 not enabled, auto-update not run.
DB writes limited to timestamp + MFE columns and the outcomes table.
