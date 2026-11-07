#!/usr/bin/env python3
"""Watch Desk v3 (WS-A2): candidate-source outcome reconciler.

Every anchored watch_candidate_events row ≥21 trading-ish days old gets +21d
(and +63d when available) symbol return vs SPY and a verdict:
OUTPERFORM (α>+3%) / MARKET (−3..+3) / UNDERPERFORM (α<−3%) / NOT_EVALUABLE.
Unanchored events stay NOT_EVALUABLE — attribution is never guessed.
Weekly cron (Sunday); per-run cap keeps bar fetches bounded.

2026-11-07 (LQ-20261107-104): the lane printed "no anchored events due — clean run" every week and wrote no
receipt, so it graded FAILING (evaluated_at max 2026-09-27) with nothing to show whether the week was quiet or
the input had died. It had died: ``watch_candidate_events`` has had **no producer** since 2026-07-16 (declared in
``scripts/lib/data_broker/watch_discovery.py``, class ``dead_feed``). Every run now writes a LaneRunReceipt and
attributes a zero: ``nothing_due`` while the feed is live, ``dependency_unavailable`` (exit 1) once no candidate
event has been emitted for ``INPUT_DEAD_DAYS``.
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "reconcile-watch-outcomes"
    _dr_would = (
        "settle unanchored past-due watch_candidate_events as NOT_EVALUABLE and score up to 400 anchored ones"
        " (+21d/+63d return vs SPY), UPDATE-ing their verdicts"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="watch_candidate_event"))
    raise SystemExit(0)

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

CAP_EVENTS = 400
LANE_ID = "reconcile-watch-outcomes"
# The reconciler's own horizon is 30 days and it runs weekly, so a feed with no new candidate event for 45 days
# is not a quiet week — it has no producer. Measured 2026-11-07: newest emitted_on 2026-07-16, 114 days.
INPUT_DEAD_DAYS = 45


def _input_state(ex) -> dict:
    """The feed's own last word: newest candidate event date and how many days ago that was."""
    row = ex("""SELECT max(emitted_on)::text AS last_on, (CURRENT_DATE - max(emitted_on)) AS age_days
                FROM watch_candidate_events""", fetch="one") or {}
    return {"last_on": row.get("last_on"), "age_days": row.get("age_days")}


def _receipt(*, ok: bool, produced: int, empty_reason=None, skipped=None, error=None) -> None:
    """LaneRunReceipt (data/runtime/reconcile-watch-outcomes_last.json). Never raises: the run's result first."""
    try:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
        write_lane_receipt(LANE_ID, ok=ok, started_at=now_iso(), script="reconcile_watch_outcomes.py",
                           produced_count=max(0, int(produced)), skipped_reasons=skipped or {},
                           empty_reason=empty_reason, error=error)
    except Exception as exc:  # noqa: BLE001 -- a receipt problem must not change the run's verdict
        print(f"[watch-outcomes] receipt not written: {exc}", file=sys.stderr)


def _closes(symbol: str, bars_cache: dict) -> list[tuple[dt.date, float]]:
    if symbol in bars_cache:
        return bars_cache[symbol]
    from holdings_gain_guardian import _bars_with_volume
    seq = []
    for b in _bars_with_volume(symbol, days=160):
        ts = b.get("datetime") or b.get("t") or b.get("date") or ""
        try:
            when = (dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
                    if isinstance(ts, (int, float)) else dt.date.fromisoformat(str(ts)[:10]))
        except Exception:
            continue
        c = float(b.get("close") or 0)
        if c > 0:
            seq.append((when, c))
    bars_cache[symbol] = seq
    return seq


def _ret_after(seq, start: dt.date, anchor: float, tdays: int):
    after = [c for (d, c) in seq if d > start]
    if len(after) <= tdays or anchor <= 0:
        return None
    return round(100.0 * (after[tdays] / anchor - 1), 2)


def main() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2
    rows = ex("""SELECT id, symbol, emitted_on, anchor_price FROM watch_candidate_events
                 WHERE verdict IS NULL AND anchor_price IS NOT NULL
                   AND emitted_on <= CURRENT_DATE - 30
                 ORDER BY emitted_on ASC LIMIT %s""", (CAP_EVENTS,), fetch="all") or []
    # unanchored past-due events settle as NOT_EVALUABLE immediately (honest, cheap)
    ex("""UPDATE watch_candidate_events SET verdict='NOT_EVALUABLE', evaluated_at=NOW()
          WHERE verdict IS NULL AND anchor_price IS NULL AND emitted_on <= CURRENT_DATE - 30""", fetch=None)
    if not rows:
        state = _input_state(ex)
        age = state["age_days"]
        dead = age is None or age > INPUT_DEAD_DAYS
        if dead:
            # The zero is the input's, not the week's: watch_candidate_events has had no producer since
            # 2026-07-16 (data_broker class dead_feed). Saying "clean run" here hid that for months.
            msg = (f"no producer: newest watch_candidate_events.emitted_on is {state['last_on'] or 'none'}"
                   f" ({age if age is not None else 'no'} days old, limit {INPUT_DEAD_DAYS}) — nothing can be"
                   " reconciled until a candidate-event producer runs again")
            print(f"[watch-outcomes] dependency_unavailable — {msg}", file=sys.stderr)
            _receipt(ok=False, produced=0, empty_reason="dependency_unavailable",
                     skipped={"dependency_unavailable": 1}, error=msg)
            return 1
        print("[watch-outcomes] no anchored events due — clean run (feed live)")
        _receipt(ok=True, produced=0, empty_reason="nothing_due")
        return 0
    cache: dict = {}
    spy = _closes("SPY", cache)
    done = 0
    for r in rows:
        seq = _closes(r["symbol"], cache)
        a = float(r["anchor_price"])
        ret21 = _ret_after(seq, r["emitted_on"], a, 21)
        spy_anchor = next((c for (d, c) in spy if d >= r["emitted_on"]), None)
        spy21 = _ret_after(spy, r["emitted_on"], spy_anchor, 21) if spy_anchor else None
        ret63 = _ret_after(seq, r["emitted_on"], a, 63)
        spy63 = _ret_after(spy, r["emitted_on"], spy_anchor, 63) if spy_anchor else None
        if ret21 is None or spy21 is None:
            verdict, a21 = "NOT_EVALUABLE", None
        else:
            a21 = round(ret21 - spy21, 2)
            verdict = "OUTPERFORM" if a21 > 3 else "UNDERPERFORM" if a21 < -3 else "MARKET"
        a63 = round(ret63 - spy63, 2) if (ret63 is not None and spy63 is not None) else None
        ex("""UPDATE watch_candidate_events
              SET ret_21d=%s, spy_21d=%s, alpha_21d=%s, ret_63d=%s, spy_63d=%s, alpha_63d=%s,
                  verdict=%s, evaluated_at=NOW() WHERE id=%s""",
           (ret21, spy21, a21, ret63, spy63, a63, verdict, r["id"]), fetch=None)
        done += 1
    lg = ex("""SELECT source_type, count(*) FILTER (WHERE verdict NOT IN ('NOT_EVALUABLE')) AS n,
                      round(percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)::numeric, 2) AS median_a21
               FROM watch_candidate_events WHERE alpha_21d IS NOT NULL GROUP BY 1 ORDER BY 1""", fetch="all") or []
    print(f"[watch-outcomes] evaluated {done} events · league:",
          " / ".join(f"{r['source_type']} α{r['median_a21']:+} (n={r['n']})" for r in lg))
    _receipt(ok=True, produced=done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
