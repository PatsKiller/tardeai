#!/usr/bin/env python3
"""Watch Desk v2 (D1): pullback trigger outcome reconciliation.

For each unevaluated pullback_trigger_history row ≥5 trading days old, walk the
daily bars since trigger_date and record which side resolved first:
  TARGET1_FIRST · STOP_FIRST · UNRESOLVED (after 21 trading days) · NOT_EVALUABLE
Same +N-day evaluation pattern as the Phase-193/exit reconcilers. Weekly cron.
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

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def main() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2
    from holdings_gain_guardian import _bars_with_volume

    rows = ex("""SELECT id, symbol, trigger_date, entry, stop, target1
                 FROM pullback_trigger_history
                 WHERE outcome IS NULL AND trigger_date <= CURRENT_DATE - 7
                 ORDER BY trigger_date ASC LIMIT 100""", fetch="all") or []
    if not rows:
        print("[pullback-outcomes] no unevaluated triggers due — clean run")
        return 0
    done = 0
    for r in rows:
        stop, tgt = float(r.get("stop") or 0), float(r.get("target1") or 0)
        outcome, days = "NOT_EVALUABLE", None
        if stop > 0 and tgt > 0:
            bars = _bars_with_volume(r["symbol"], days=60)
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
                    continue  # not enough bars yet — evaluate next week
        ex("""UPDATE pullback_trigger_history
              SET outcome=%s, days_to_resolve=%s, evaluated_at=NOW() WHERE id=%s""",
           (outcome, days, r["id"]), fetch=None)
        done += 1
    print(f"[pullback-outcomes] evaluated {done}/{len(rows)} due triggers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
