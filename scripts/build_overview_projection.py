#!/usr/bin/env python3
"""Build the /api/v2/overview projection out of process (lane overview-projection, LQ-20261107-1612).

Runs ``api_v2._overview_with_today_move()`` once, in this process, with a read-only DB session, and writes
OverviewProjection@v1 (scripts/lib/overview_projection.py) for portfolio-server to serve in front of its
inline compute. The API falls back inline whenever the projection is aged, from another release,
pre-dates an operator write, or is unreadable, so this lane failing costs latency, never the overview.

PROCESS   n8n lane overview-projection (scheduler of record): every 60 s, 04:00-20:00 ET on weekdays; every
          5 min otherwise. Single flight: an overlapping tick is refused (empty_reason build_in_flight).
CONTRACT  OK: projection age <= 90 s in hours (<= 330 s off hours), status ok, code_identity == serving
          release. DEGRADED: age 90-300 s, or the release moved and the next build has not landed.
          BROKEN: age > 300 s in hours, or 3 consecutive failed builds. UNVERIFIABLE: no receipt, no file.
SELF-HEAL The next tick is the retry (max_attempts 1). It never restarts the server, touches any input
          store, writes the DB or disables the inline fallback.

Without ``--apply`` nothing under the state root is written: ``--out PATH`` writes the projection there
(a dry run to scratch), and no receipt is written.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    from lib import overview_projection as op
except ImportError:  # pragma: no cover - imported as scripts.<module>
    from scripts.lib import overview_projection as op

LANE_ID = "overview-projection"
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
    """Import api_v2 (timed) and compute the overview the route computes inline. Returns (body, info)."""
    t0 = time.monotonic()
    import api_v2  # noqa: PLC0415 -- 70k lines; imported only by the lane, after chdir + read-only DB

    _MEASURE["import_s"] = round(time.monotonic() - t0, 2)
    t1 = time.monotonic()
    body = api_v2._overview_with_today_move()
    _MEASURE["compute_s"] = round(time.monotonic() - t1, 2)
    return body, {"identity": op.code_identity(api_v2.PROJECT_ROOT), "state_dir": api_v2.STATE_DIR}


def _write_receipt(summary: dict) -> None:
    try:
        from lib.lane_last_receipt import write_lane_receipt
    except ImportError:  # pragma: no cover
        from scripts.lib.lane_last_receipt import write_lane_receipt
    status = summary.get("status")
    write_lane_receipt(
        LANE_ID, ok=status in ("ok", "refused"), exit_code=0 if status in ("ok", "refused") else 1,
        started_at=summary.get("started_at"), script=__file__,
        summary={k: summary.get(k) for k in ("status", "reason", "built_at", "build_ms", "bytes",
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

    # Full precision (LQ-20261107-1795): the executor binds the receipt start to its attempt window, and a start
    # truncated to the second reads as before the attempt that launched it (receipt_outside_attempt_window).
    started = datetime.now(timezone.utc).isoformat()
    try:
        out = op.build(compute, path=path, identity=lambda: info.get("identity") or "unknown",
                       state_dir=lambda: info.get("state_dir"))
    except Exception as exc:  # noqa: BLE001 -- e.g. the lock directory is unwritable: typed, receipted
        out = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
    out.setdefault("started_at", started)
    out.update(_MEASURE)
    out["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="write the live projection and the lane receipt")
    ap.add_argument("--root", help="state root (default: the production state root)")
    ap.add_argument("--out", help="dry run: write the projection here instead (no receipt)")
    a = ap.parse_args(argv)
    if a.apply and a.out:
        ap.error("--out is a dry-run target; --apply writes the live projection")
    root = Path(a.root) if a.root else state_root()
    _force_read_only_db()
    # Importing api_v2 pulls in data_broker, which writes cio projections into cwd: keep them in the state
    # root, never in a release tree or a worktree.
    if root.is_dir():
        os.chdir(root)
    if a.apply:
        summary = run(path=op.projection_path(root))
        _write_receipt(summary)
    elif a.out:
        summary = run(path=Path(a.out))
    else:
        summary = {"status": "dry_run", "would_write": str(op.projection_path(root)),
                   "note": "pass --out PATH to build into scratch, or --apply"}
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    return 1 if summary.get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
