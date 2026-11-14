#!/usr/bin/env python3
"""Build the /api/v2/home/do-now snapshot out of process (lane home-do-now-snapshot, S2 item 2, 2026-11-14).

Runs ``api_v2._home_do_now_build()`` once, in this process, with a read-only DB session, and writes
HomeDoNowSnapshot@v1 (scripts/lib/home_do_now_snapshot.py) for portfolio-server to read. The route has no inline
fallback at all: an absent, unreadable or expired snapshot is a NAMED UNKNOWN on the wire, never a build on the
request thread (operator 2026-11-14: a GET never triggers heavy compute, not on cold start, a cache miss or a
producer outage).

Process   n8n lane home-do-now-snapshot (scheduler of record): every 60 s in the market window, 04:00-20:00 ET
          weekdays; every 5 min otherwise. Single flight: an overlapping tick is refused (build_in_flight).
Reads     the same eight read-only probes the route used to run on the request thread. No broker read, no write,
          no LLM call (MBI_BEHAVIOR = 0).
Contract  OK: snapshot age <= 120 s, status ok, code_identity == the serving release. DEGRADED: age 120-1800 s,
          or the release moved and the next build has not landed. BROKEN: no snapshot, or age > 1800 s (the route
          then answers the named UNKNOWN). UNVERIFIABLE: no receipt and no file.
Self-heal The next tick is the retry (max_attempts 1). It never restarts the server, never writes an input store,
          and never calls back into the request path.

Without ``--apply`` nothing under the state root is written: ``--out PATH`` writes the snapshot there (a dry run to
scratch), and no receipt is written.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import time

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    from lib import home_do_now_snapshot as hdn
except ImportError:  # pragma: no cover - imported as scripts.<module>
    from scripts.lib import home_do_now_snapshot as hdn

LANE_ID = "home-do-now-snapshot"
READ_ONLY_OPT = "-c default_transaction_read_only=on"


def state_root() -> Path:
    try:
        from lib.canonical_store_registry import production_state_root
    except ImportError:  # pragma: no cover
        from scripts.lib.canonical_store_registry import production_state_root
    return production_state_root()


def _force_read_only_db() -> None:
    """Every DB session this process opens is read-only: the build never writes the DB."""
    cur = os.environ.get("PGOPTIONS", "").strip()
    if "default_transaction_read_only=on" not in cur:
        os.environ["PGOPTIONS"] = (cur + " " + READ_ONLY_OPT).strip()


_MEASURE: dict[str, Any] = {}


def _compute() -> tuple[dict, dict]:
    """Import api_v2 (timed) and run the build the route used to run: the SAME function, in this process."""
    t0 = time.monotonic()
    import api_v2  # noqa: PLC0415 -- 70k lines; imported only by the lane, after chdir + read-only DB

    _MEASURE["import_s"] = round(time.monotonic() - t0, 2)
    t1 = time.monotonic()
    body = api_v2._home_do_now_build()
    _MEASURE["compute_s"] = round(time.monotonic() - t1, 2)
    probes = (body.get("sources") or {}) if isinstance(body, dict) else {}
    _MEASURE["sources"] = {k: (v.get("status"), v.get("ms")) for k, v in probes.items() if isinstance(v, dict)}
    return body, {"identity": hdn.code_identity(api_v2.PROJECT_ROOT), "state_dir": api_v2.STATE_DIR}


def _write_receipt(summary: dict) -> None:
    try:
        from lib.lane_last_receipt import write_lane_receipt
    except ImportError:  # pragma: no cover
        from scripts.lib.lane_last_receipt import write_lane_receipt
    status = summary.get("status")
    write_lane_receipt(
        LANE_ID, ok=status in ("ok", "refused"), exit_code=0 if status in ("ok", "refused") else 1,
        started_at=summary.get("started_at"), script=__file__,
        summary={k: summary.get(k) for k in ("status", "reason", "built_at", "as_of", "build_ms", "bytes",
                                              "code_identity", "import_s", "compute_s", "max_rss_mb")},
        error=summary.get("error"),
        produced_count=1 if status == "ok" else 0, attempted_count=0 if status == "refused" else 1,
        empty_reason="build_in_flight" if status == "refused" else None,
        output={"path": summary.get("path"), "built_at": summary.get("built_at")} if status == "ok" else None,
    )


def run(*, path: Path) -> dict:
    info: dict = {}

    def compute() -> dict:
        body, meta = _compute()
        info.update(meta)
        return body

    # Full precision: the executor binds the receipt start to its attempt window, and a start truncated to the
    # second reads as before the attempt that launched it (receipt_outside_attempt_window).
    started = datetime.now(timezone.utc).isoformat()
    try:
        out = hdn.build(compute, path=path, identity=lambda: info.get("identity") or "unknown",
                        state_dir=lambda: info.get("state_dir"))
    except Exception as exc:  # noqa: BLE001 -- e.g. the lock directory is unwritable: typed, receipted
        out = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
    out.setdefault("started_at", started)
    out.update(_MEASURE)
    out["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="write the live snapshot and the lane receipt")
    ap.add_argument("--root", help="state root (default: the production state root)")
    ap.add_argument("--out", help="dry run: write the snapshot here instead (no receipt)")
    a = ap.parse_args(argv)
    if a.apply and a.out:
        ap.error("--out is a dry-run target; --apply writes the live snapshot")
    root = Path(a.root) if a.root else state_root()
    _force_read_only_db()
    # Importing api_v2 pulls in data_broker, which writes CIO projections into cwd: keep them in the state root,
    # never in a release tree or a worktree.
    if root.is_dir():
        os.chdir(root)
    if a.apply:
        summary = run(path=hdn.projection_path(root))
        _write_receipt(summary)
    elif a.out:
        summary = run(path=Path(a.out))
    else:
        summary = {"status": "dry_run", "would_write": str(hdn.projection_path(root)),
                   "note": "pass --out PATH to build into scratch, or --apply"}
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    return 1 if summary.get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
