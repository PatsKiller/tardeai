#!/usr/bin/env python3
"""Lane ``market-event-lifecycle`` (LQ-20261107-1656 design, LQ-20261107-1674 build).

WP3's state machine stops at ENTERED: once a name is bought nothing advises about the position that exists. This lane
is the step that keeps going — it reads the held positions (``positions_current``), the resting stops
(``stop_lifecycle``), the guardian's newest run (``holding_exit_metrics``), the name gate's own bars and the MRE tier,
runs ``market_event_plan.evaluate_position`` on every held row, and persists each stage transition.

Advisory only. ``MBI_BEHAVIOR = 0``: nothing here sizes against a broker, orders, stops, weights or sends anything.
Every number on a row is an advisory proposal per account LABEL; no account number is ever stored.

  --dry-run    (default) read-only: evaluates every row and prints what would be written; writes nothing, no receipt
  --apply      writes the transitions and the lane receipt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import market_event_lifecycle as life  # noqa: E402

LANE = life.LANE


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        env = Path(os.environ.get("TRADEAI_ENV_FILE", ""))
    if env and env.is_file():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def connect(read_only: bool):
    from scripts.lib import lane_last_receipt, ops_lanes  # noqa: PLC0415

    _load_env()
    env_file = Path(os.environ.get("TRADEAI_ENV_FILE") or ROOT / ".env")
    conn = ops_lanes.pg_connect(ops_lanes.db_params(env_file=env_file), read_only=read_only)
    if read_only:
        lane_last_receipt.enforce_readonly(conn)
    return conn


def db_query(conn):
    def query(sql: str, params=None):
        cur = conn.cursor()
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return query


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="read-only; evaluate every row and print what would be written (default)")
    mode.add_argument("--apply", action="store_true", help="write the transitions and the lane receipt")
    ap.add_argument("--trigger", default="tick",
                    help="what fired this run: tick | calendar:<KIND> | tier:<from>-><to> | stop:<SYM> | qty:<SYM>")
    ap.add_argument("--calendar", help="MacroCalendar@v1 file (default: the state root's macro_calendar.json)")
    ap.add_argument("--now", help="ISO time to evaluate at (replay)")
    a = ap.parse_args(argv)
    from scripts.lib import lane_last_receipt as lr  # noqa: PLC0415

    started = lr.now_iso()
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    apply = bool(a.apply)
    conn = connect(read_only=not apply)
    try:
        summary = life.run_lane(conn=conn, db_query=db_query(conn), now=now, apply=apply,
                                trigger=a.trigger, calendar_path=a.calendar)
        out = {"mode": "apply" if apply else "dry_run", **summary}
        if summary["error"]:
            print(json.dumps(out, default=str))
            print(f"market-event-lifecycle did not run: {summary['error']}", file=sys.stderr)
            if apply:
                conn.commit()
                lr.write_lane_receipt(LANE, ok=False, exit_code=1, started_at=started,
                                      script="scripts/market_event_lifecycle.py", summary=out,
                                      error=summary["error"])
            return 1
        if apply:
            conn.commit()
            lr.write_lane_receipt(
                LANE, ok=True, exit_code=0, started_at=started, script="scripts/market_event_lifecycle.py",
                summary=out, produced_count=summary["rows_evaluated"],
                attempted_count=summary["rows_evaluated"],
                empty_reason=summary["empty_reason"])
        print(json.dumps(out, default=str))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
