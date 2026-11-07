#!/usr/bin/env python3
"""Lane ``market-event-plan-stamp`` (WP3->WP6, LQ-20261107-369): freeze each candidate's WP3 plan when its state
changes, so WP6 outcomes can score the tranches instead of only the ``first_seen`` basis.

WP3 computes a candidate's plan when it is read (``/api/v2/market-event/active``) and never wrote
``market_event_candidates.plan``; WP6 outcomes reads its tranche stamps from that column. This lane is the writer:
it builds the same plan document the API returns, and persists one snapshot per state change per candidate — the
tranche number, the advisory dollars per account LABEL, the entry zone and the invalidation. No account number is
ever stored.

Idempotent: a run over unchanged state writes nothing (0 rows), and the UPDATE is guarded by
``plan IS DISTINCT FROM`` as a second barrier. Deterministic: the document carries a clock only where something
actually changed.

Advisory only. ``MBI_BEHAVIOR = 0``: nothing here sizes against a broker, orders, stops or sends anything; the
document is the same advisory text the /active page already renders.

  --dry-run   (default) read-only: builds every stamp and prints what would be written; writes no row and no receipt
  --apply     write the stamps and the lane receipt
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

from scripts.lib import market_event_plan_stamp as stamp  # noqa: E402

LANE = "market-event-plan-stamp"


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="read-only; build every stamp and print what would be written (default)")
    mode.add_argument("--apply", action="store_true", help="write the plan stamps and the lane receipt")
    ap.add_argument("--holdings", help="holdings.json (default <state root>/data/portfolios/state/holdings.json)")
    ap.add_argument("--now", help="ISO time to evaluate at (replay)")
    a = ap.parse_args(argv)
    from scripts.lib import lane_last_receipt as lr  # noqa: PLC0415

    started = lr.now_iso()
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    apply = bool(a.apply)
    conn = connect(read_only=not apply)
    try:
        summary = stamp.persist_for_connection(
            conn=conn, db_query=stamp.db_query(conn), snapshot=stamp.load_mre(), holdings_path=a.holdings,
            now=now, apply=apply)
        out = {"lane": LANE, "mode": "apply" if apply else "dry_run", **summary}
        if summary["error"]:
            print(json.dumps(out, default=str))
            print(f"plan stamps not written: {summary['error']}", file=sys.stderr)
            return 1
        if apply:
            conn.commit()
            lr.write_lane_receipt(
                LANE, ok=True, exit_code=0, started_at=started, script="scripts/market_event_plan_stamp.py",
                summary=out, produced_count=summary["changed"], attempted_count=summary["would_change"],
                empty_reason=("no open episode" if not summary["candidates"] else
                              "no candidate changed state" if not summary["would_change"] else None))
        print(json.dumps(out, default=str))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
