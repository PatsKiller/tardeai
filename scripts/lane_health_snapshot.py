#!/usr/bin/env python3
"""lane_health_snapshot.py — the n8n writer lane ``lane-health-snapshot`` (LQ-20261107-2148, Home v010 Schedulers).

Per ACTIVE scheduled lane: expected slots (registry) vs dispatcher runs (n8n coordination ledger) → expected / done /
late / missed / failed counts over the last 24 h, the last expected slot, the last RUN_DONE, the output-signal age
and one state (OK / LATE / STALE / FAILING / UNKNOWN / NOT_MEASURED) with its cause, plus the Home Schedulers
rollup (OK / WARN / UNKNOWN). The compute is ``scripts/lib/lane_health.py``; read it for the honesty rules.

    python3 scripts/lane_health_snapshot.py               # dry run: compute + print, writes NOTHING
    python3 scripts/lane_health_snapshot.py --apply       # one scheduled cycle (dispatcher only: needs TRADEAI_RUN_ID)

``--apply`` writes, in order:
1. ``lane_health_current`` (Postgres, the system of record): every row UPSERTed on ``lane_id`` in one transaction.
   The table is created only by ``migrations/2026_11_12_lane_health_current.sql`` (hand-applied); this lane never
   runs DDL, and a missing table fails the run (exit 1) instead of creating it.
2. ``data/runtime/lane_health_current.json`` — a JSON mirror (fallback only), written after the DB commit, carrying
   ``db_written`` so a reader can tell a mirror of a committed run from a mirror of a failed one.
3. ``data/runtime/lane-health-snapshot_last.json`` — the LaneRunReceipt (``ok_at`` advances on success only),
   written by ``lane_receipt_main.run_main``; never on a dry run.

AUTHORITY: READ_ONLY_ADVISORY over every store it reads. MBI_BEHAVIOR = 0: no broker, no order, no live flag.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_health as LH  # noqa: E402
from scripts.lib import lane_output  # noqa: E402

RUN_ID_ENV = "TRADEAI_RUN_ID"
MIRROR = "data/runtime/lane_health_current.json"


def _state_root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    from scripts.lib.lane_registry import state_root
    return state_root()


def _conn():
    try:
        import session13_db  # type: ignore
    except ImportError:
        from scripts import session13_db  # type: ignore
    return session13_db.get_conn()


def _db_query(conn):
    """A read callable for ``observe_signal`` db_max signals; a failed read is None (UNVERIFIABLE), never a raise."""
    def query(sql: str):
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            conn.rollback()
            return rows
        except Exception:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None
    return query


def summary(snap: dict) -> dict:
    sch = snap["schedulers"]
    return {"run_id": snap["run_id"], "measured_at": snap["measured_at"], "schedulers": sch["status"],
            "cause": sch["cause"], "counts": sch["counts"], "missed_total_24h": sch["missed_total_24h"],
            "late_total_24h": sch["late_total_24h"], "failed_total_24h": sch["failed_total_24h"],
            "lanes": len(snap["lanes"]), "inputs": snap["inputs"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write lane_health_current + mirror (dispatcher only)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print; write nothing (the default)")
    ap.add_argument("--state-root", default=None)
    ap.add_argument("--json", action="store_true", help="print the full snapshot, not the summary")
    a = ap.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    mode = "apply" if a.apply and not a.dry_run else "dry_run"
    root = _state_root(a.state_root)
    run_id = os.environ.get(RUN_ID_ENV) or ""
    if mode == "apply" and not run_id:
        # a hand-fired --apply has no slot identity; the table is keyed to dispatcher runs (spec 1.4: manual refused)
        print(json.dumps({"ok": False, "error": "no_run_id",
                          "detail": f"--apply needs {RUN_ID_ENV} from the n8n run executor; run without --apply"}))
        return 2
    conn = None
    if mode == "apply":
        conn = _conn()
        if not LH.table_exists(conn):
            print(json.dumps({"ok": False, "error": "table_missing",
                              "detail": f"{LH.TABLE} does not exist; apply migrations/2026_11_12_lane_health_current.sql "
                                        "(operator/lead). This lane never runs DDL."}))
            return 1
    snap = LH.compute(state_root=root, run_id=run_id or "preview",
                      db_query=_db_query(conn) if conn is not None else None)
    rows = len(snap["lanes"])
    if mode == "dry_run":
        print(json.dumps(snap if a.json else summary(snap), indent=1, default=str))
        lane_output.emit(LH.LANE_ID, mode, lane_output.output_block(
            produced=0, attempted=rows, empty_reason="dry run writes nothing", unit="lane rows"), started_at=started)
        return 0
    db_ok, error = False, None
    try:
        written = LH.write(conn, snap)
        db_ok = written == rows
    except Exception as exc:  # noqa: BLE001 -- recorded in the mirror and the receipt; the run fails below
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    from scripts.lib.atomic_json_store import atomic_write_json
    atomic_write_json(root / MIRROR, {**snap, "db_written": db_ok, "db_error": error})
    print(json.dumps({**summary(snap), "db_written": db_ok, "db_error": error}, indent=1, default=str))
    lane_output.emit(LH.LANE_ID, mode, lane_output.output_block(
        produced=rows if db_ok else 0, attempted=rows,
        empty_reason=None if db_ok or rows else "no ACTIVE scheduled lane", unit="lane rows"), started_at=started)
    if not db_ok:
        return 1
    if rows == 0:
        return 1  # nothing measured is not success (LaneOutput contract)
    return 0


if __name__ == "__main__":
    from scripts.lib.lane_receipt_main import run_main
    sys.exit(run_main(LH.LANE_ID, main, script="scripts/lane_health_snapshot.py"))
