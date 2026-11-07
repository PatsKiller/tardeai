#!/usr/bin/env python3
"""Watch Desk v2 (D1): pullback trigger outcome reconciliation.

For each unevaluated pullback_trigger_history row ≥5 trading days old, walk the
daily bars since trigger_date and record which side resolved first:
  TARGET1_FIRST · STOP_FIRST · UNRESOLVED (after 21 trading days) · NOT_EVALUABLE
Same +N-day evaluation pattern as the Phase-193/exit reconcilers. Weekly cron.

n8n onboarding (LQ-20261107-26, class learn). Two evidence facts this lane owes the dispatcher:

* ``--dry-run`` is an OFFLINE plan: it returns below, before the .env load, any DB/network/sender import and any
  file write (proven hermetically by tests/test_onboard_dryrun_b1_20261015.py).
* a REAL run writes the lane receipt ``<state_root>/data/runtime/reconcile-pullback-outcomes_last.json``
  (LaneRunReceipt@v2, ``ok_at`` only on success). Before this, the row's only signal was the cron ``>>
  logs/pullback_outcomes.log`` redirect's mtime, which proves cron opened a file and nothing about the run
  (AGENTS.md §9.3, rail 8). A run that could not read a symbol's bars no longer aborts the whole batch: the row is
  counted under ``skipped_reasons`` and the rest still resolve.
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

    _dr_lane = "reconcile-pullback-outcomes"
    _dr_would = (
        "walk daily bars for up to 100 unevaluated pullback_trigger_history rows at least 7 days old and "
        "UPDATE each outcome (TARGET1_FIRST / STOP_FIRST / UNRESOLVED / NOT_EVALUABLE)"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="pullback_trigger"))
    raise SystemExit(0)

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LANE_ID = "reconcile-pullback-outcomes"
SCRIPT = "reconcile_pullback_outcomes.py"
#: The SELECT cap. A run that fills it may have left due triggers behind; the receipt says so.
DUE_LIMIT = 100
#: Set by main(); the __main__ failure handler stamps the run's real start on a failed-receipt write.
_STARTED: str | None = None

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.reconcile_pullback_outcomes
        from scripts.lib import lane_last_receipt as lr
    return lr


def _receipt(**kw) -> None:
    """Write the lane receipt. A receipt failure never changes this run's result (the lib never raises either)."""
    try:
        _receipt_lib().write_lane_receipt(LANE_ID, script=SCRIPT, **kw)
    except Exception as exc:  # noqa: BLE001 -- evidence must not fail the run
        print(f"[pullback-outcomes] receipt not written: {type(exc).__name__}", file=sys.stderr)


def main() -> int:
    global _STARTED
    started = _STARTED = dt.datetime.now(dt.timezone.utc).isoformat()
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        _receipt(ok=False, exit_code=2, started_at=started, error="DBUnavailable: DB adapter not configured")
        return 2
    from holdings_gain_guardian import _bars_with_volume

    skipped: dict[str, int] = {}
    rows = ex("""SELECT id, symbol, trigger_date, entry, stop, target1
                 FROM pullback_trigger_history
                 WHERE outcome IS NULL AND trigger_date <= CURRENT_DATE - 7
                 ORDER BY trigger_date ASC LIMIT %s""", (DUE_LIMIT,), fetch="all") or []
    if not rows:
        print("[pullback-outcomes] no unevaluated triggers due — clean run")
        _receipt(ok=True, exit_code=0, started_at=started,
                 summary={"due": 0, "evaluated": 0},
                 produced_count=0, attempted_count=0, empty_reason="no_due_rows")
        return 0
    done = 0
    by_outcome: dict[str, int] = {}
    for r in rows:
        stop, tgt = float(r.get("stop") or 0), float(r.get("target1") or 0)
        outcome, days = "NOT_EVALUABLE", None
        if stop > 0 and tgt > 0:
            try:
                bars = _bars_with_volume(r["symbol"], days=60)
            except Exception:  # noqa: BLE001 -- one unreadable symbol must not cost the batch
                skipped["bars_unavailable"] = skipped.get("bars_unavailable", 0) + 1
                continue
            seq = []
            for b in bars:
                ts = b.get("datetime") or b.get("t") or b.get("date") or ""
                try:
                    when = (dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
                            if isinstance(ts, (int, float))
                            else dt.date.fromisoformat(str(ts)[:10]))
                except Exception:
                    continue
                if when > r["trigger_date"]:
                    seq.append((when, float(b.get("high") or 0), float(b.get("low") or 0)))
            for i, (when, hi, lo) in enumerate(seq[:21], start=1):
                hit_t, hit_s = hi >= tgt, (lo <= stop if lo > 0 else False)
                if hit_t and not hit_s:
                    outcome, days = "TARGET1_FIRST", i
                    break
                if hit_s and not hit_t:
                    outcome, days = "STOP_FIRST", i
                    break
                if hit_t and hit_s:
                    outcome, days = "STOP_FIRST", i  # same-bar ambiguity resolves conservatively
                    break
            else:
                if len(seq) >= 21:
                    outcome = "UNRESOLVED"
                elif seq:
                    skipped["not_enough_bars_yet"] = skipped.get("not_enough_bars_yet", 0) + 1
                    continue  # not enough bars yet — evaluate next week
        ex("""UPDATE pullback_trigger_history
              SET outcome=%s, days_to_resolve=%s, evaluated_at=NOW() WHERE id=%s""",
           (outcome, days, r["id"]), fetch=None)
        done += 1
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
    print(f"[pullback-outcomes] evaluated {done}/{len(rows)} due triggers")
    _receipt(ok=True, exit_code=0, started_at=started,
             summary={"due": len(rows), "evaluated": done, "by_outcome": by_outcome,
                      "due_cap_hit": len(rows) >= DUE_LIMIT},
             produced_count=done, attempted_count=len(rows), skipped_reasons=skipped,
             empty_reason="no_outcomes_written" if done == 0 else None)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # a live run that dies still writes a failed receipt (ok_at carried forward)
        _receipt(ok=False, exit_code=1, started_at=_STARTED or dt.datetime.now(dt.timezone.utc).isoformat(),
                 error=f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)

