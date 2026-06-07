# Profit-Capture — Evidence-Floor Ceiling Determination (2026-06-06)

**Status:** Determination complete. The reliable-evidence floor (n ≥ 20) is **NOT reachable** with
current data. Maximum honest reliable_n = **11**. `DO_NOT_GRAFT` upheld. No gaming, no fabrication.

## Question

Can the measurable winner set be expanded to reach the rule-backtest evidence floor (reliable n ≥ 20)?

## Answer

**No — not with genuine, independent data.** Reaching 20 would require double-counting duplicate
imports or fabricating stops, both of which defeat the purpose of the floor and are prohibited. The
account simply has not produced 20 independent recent winning trades with intraday paths and stops.

## Definition of a "reliable" winner

A winner counts toward `reliable_sample_size` only if it has **all** of:
closed + winner + a real **intrabar path** (premature-exit cost measurable, ~60-day bar window) +
a **planned stop** (R denominator) + non-outlier MFE + ≥10 bars.

## The pool, exhaustively

| source | winners | usable for reliable | why not |
|--------|---------|---------------------|---------|
| alpaca_paper | 13 | **9 → 11** (after clean repair) | 4 lacked a planned stop |
| schwab_import (recent, ≤60d) | 17 | **0 net new** | 13 are **duplicates** of the paper winners (same symbol+date+shares — same economic trade imported twice); counting = double-counting |
| schwab_import (independent recent) | 4 | **0** | PFE/V are 8-month holds (no intraday path exists); DFSC/FATN have **no stop** |
| schwab_import (older) | 113 | **0** | older than the ~60-day intraday-bar window (back to 2023-09) — daily bars can't price intraday premature exits |

**True ceiling = 9** unique recent winners with both an intraday path and a stop — already the
current reliable_n before any change.

## The one legitimate expansion that was applied

Four paper winners had a NULL `planned_stop`. Their stop could in principle be recovered from the
**same trade's** Schwab-import twin (`trades.stop_loss`). But the twin stops are **conflicting** for
2 of them (ANY: 3.07 *and* 3.89; SNOW: 228.01 *and* 254.38) — ambiguous, so **not** repaired. Only the
2 INFU trades had an **unambiguous** single-valued stop (7.97), so only those were repaired:

```sql
UPDATE paper_trades pt SET planned_stop = sub.stop_loss, updated_at=now()
FROM (
  SELECT pt2.id, max(sw.stop_loss) stop_loss
  FROM paper_trades pt2
  JOIN trades sw ON sw.symbol=pt2.symbol AND sw.entry_date::date=pt2.entry_time::date
                AND sw.shares=pt2.shares AND sw.stop_loss>0
  WHERE pt2.status='closed' AND pt2.pnl>0 AND pt2.planned_stop IS NULL
  GROUP BY pt2.id HAVING count(DISTINCT sw.stop_loss)=1   -- unambiguous only
) sub WHERE pt.id = sub.id;
```

Result: reliable_n **9 → 11**. `planned_stop` is an analytics attribute (used by `open_trade_monitor`
only `WHERE status='open'`, never for closed trades) — no execution effect. Still below the floor.

## Shortcuts deliberately NOT taken

- ❌ Counting the 13 duplicate Schwab winners (double-counting the same trades).
- ❌ Guessing a `planned_stop` for ANY/SNOW from conflicting twin values.
- ❌ Using daily-bar "MFE" for old trades as if it were a measurable intrabar path.
- ❌ Lowering `--min-bars-analyzed`, `--max-mfe-r`, or the reliable floor to inflate n.

## What would actually close the gap

Only **forward accumulation of more independent recent winning paper trades** (each with a planned
stop and within the ~60-day intraday-bar window) raises reliable_n honestly. At the current rate this
takes time; it is not a code change. Re-run `ingest_trade_intrabar_bars.py --fine --apply --all-closed`
then `backtest_profit_protection_rules.py --apply --quality-gated --winners-only ...` periodically and
watch `reliable_sample_size` climb. A future **operator-approved, clearly-labelled low-confidence
pilot** is the only adoption path short of the floor — never an automatic graft.

## Current state

reliable_n = **11** (max) · every rule and family **DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE** · core rules
net-negative on path-measured cost · validation **PASS 14/14**.

## Safety proof

`ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`. The only data write was the 2-row unambiguous
`planned_stop` repair above (analytics; no execution path). No broker/order/stop/GO-WAIT/strategy/
threshold/live/Phase-205 changes; Hermes drain untouched.
