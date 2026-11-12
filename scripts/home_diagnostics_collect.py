#!/usr/bin/env python3
"""Home diagnostics collector: probe the 13 Home widgets' sources read-only and write the snapshot the endpoint serves.

n8n writer lane ``home-diagnostics`` (LQ-20261107-2149/2150). The lane writes; GET /api/v2/home/diagnostics only reads.
Without ``--apply`` it prints the snapshot and writes nothing (a dry run is the same binary, write-free).

Exit: 0 = snapshot written (rows may be UNKNOWN: that is a truthful snapshot); 1 = the database could not be opened,
a truthful all-UNKNOWN snapshot was still written under --apply and the lane receipt says error; 2 = registry invalid
(nothing written; a registry that does not validate must not produce a shorter, greener drawer).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import home_diagnostics as hd  # noqa: E402

LANE_ID = "home-diagnostics"
SCRIPT_REL = "scripts/home_diagnostics_collect.py"
STATE_DIR = Path(os.environ.get("TRADEAI_STATE_DIR") or Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state")


def _db_query_factory(timeout_s: float):
    """A read-only query callable; a statement over the timeout raises TimeoutError."""
    from lib.cio_market_context_state import connect_trade_ai_readonly  # noqa: PLC0415

    conn = connect_trade_ai_readonly()
    cur = conn.cursor()
    cur.execute("SET statement_timeout = %s", [int(timeout_s * 1000)])

    def query(sql: str):
        try:
            cur.execute(sql)
            return cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "QueryCanceled":
                raise TimeoutError(f"statement over {timeout_s:g} s") from exc
            raise

    return query, conn


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, default=str)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None, *, query=None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the snapshot (default: print only)")
    ap.add_argument("--state-dir", type=Path, default=STATE_DIR)
    ap.add_argument("--registry", type=Path, default=None)
    a = ap.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    try:
        reg = hd.load_registry(a.registry)
    except (hd.RegistryError, OSError, ValueError) as exc:
        print(f"home diagnostics registry invalid: {exc}", file=sys.stderr)
        return 2
    when = now or datetime.now(timezone.utc)
    conn, db_error = None, None
    if query is None:
        try:
            query, conn = _db_query_factory(float(reg["probe_timeout_s"]))
        except Exception as exc:  # noqa: BLE001 -- recorded; every probe then reports the same named failure
            db_error = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:160] if str(exc).strip() else ''}"

            def query(sql: str, _e=db_error):  # noqa: ANN001
                raise ConnectionError(f"database unavailable: {_e}")
    out_path = a.state_dir / hd.SNAPSHOT_NAME
    previous = None
    try:
        previous = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    try:
        snap = hd.build_snapshot(reg, query, when, previous)
    finally:
        if conn is not None:
            conn.close()
    c = snap["counts"]
    print(f"home diagnostics: {len(snap['rows'])} widgets, session {snap['session']}, "
          + ", ".join(f"{k} {v}" for k, v in c.items() if v))
    if not a.apply:
        print("DRY RUN: nothing written")
        print(json.dumps(snap, indent=1, default=str))
        return 1 if db_error else 0
    _atomic_write(out_path, snap)
    try:
        from lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415

        write_lane_receipt(LANE_ID, ok=not db_error, exit_code=1 if db_error else 0, started_at=started, script=SCRIPT_REL,
                           summary={"counts": c, "session": snap["session"], "path": str(out_path)},
                           error=db_error, produced_count=len(snap["rows"]))
    except Exception as exc:  # noqa: BLE001 -- the snapshot is the durable artifact; say so
        print(f"lane receipt not written: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if db_error else 0


if __name__ == "__main__":
    sys.exit(main())
