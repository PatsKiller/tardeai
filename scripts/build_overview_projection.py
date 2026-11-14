#!/usr/bin/env python3
"""Build the /api/v2/overview projection out of process (lane overview-projection, LQ-20261107-1612).

Runs ``api_v2._overview_with_today_move()`` once, in this process, with a read-only DB session, and writes
OverviewProjection@v1 (scripts/lib/overview_projection.py) for portfolio-server to serve. What the server does when
it cannot serve the document - serve a last-known body, or compute inline - is defined by
``api_v2._overview_served`` and gated at activation by ``scripts/check_overview_cutover.py``; this producer makes no
claim about it, and a lane that stops firing breaks a stored-only reader that no receipt ever asked about (INC-OVW,
2026-11-14).

PROCESS   n8n lane overview-projection (the ONE owner; registry row config/lane_registry.json#overview-projection):
          America/New_York, so DST moves with the exchange calendar. Three expressions on one row:
          ``*/1 4-20 * * 1-5`` (60 s in the weekday market window), ``*/5 0-3,21-23 * * 1-5`` (5 min around it) and
          ``*/5 * * * 0,6`` (5 min all weekend) - 24x7 with no hour of any week unfired. Single flight: an
          overlapping tick is refused (empty_reason build_in_flight) and is not a failure.
CONTRACT  DERIVED, never hand-picked: ``scripts/lib/overview_lane_contract.py`` measures this schedule over five
          weeks with the dispatcher's own calendar (worst gap 3900 s, the fall-back fold night), adds the retry span
          (3 x 300 s + 30 + 120 = 1050 s) and the allowed dispatch delay (90 s) for a floor of 5040 s; the reader's
          last-good window is 5400 s, i.e. one whole cycle of headroom. OK: body age <= 5040 s at ANY hour/day.
          DEGRADED: 5040-5400 s. BROKEN: > 5400 s (the header answers unknown), 3 consecutive failures, or a run
          that ends RUN_FAILED/RUN_TIMEOUT/RUN_REFUSED. tests/test_overview_projection_247.py pins each number.
SELF-HEAL The next tick is the first retry; the dispatcher's transient-2 policy adds a second and third attempt
          (30 s and 120 s backoff) inside that window. It never restarts the server, touches any input store,
          writes the DB or changes what the API serves.
MEMORY    RLIMIT_AS caps this process at 2048 MB (override TRADEAI_OVERVIEW_BUILD_MAX_MB): a runaway build dies as a
          receipted failure instead of competing with portfolio-server for host RAM. Measured peak is ~330 MB.

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


#: address-space cap for this process (MB). Measured peak RSS is ~330 MB; the cap is a fence against a runaway
#: import/build competing with portfolio-server for host RAM, not a tuned budget. Override for a one-off measurement.
DEFAULT_MAX_MB = 2048


def _cap_memory() -> str:
    """Lower this process's RLIMIT_AS to the cap. Returns a one-line description, never raises.

    A cap that cannot be set (no RLIMIT_AS on the platform, a permission refusal) is reported and the build proceeds:
    a monitor that cannot install its fence must not become the outage. An ALREADY lower limit is never raised.
    """
    try:
        cap_mb = int(os.environ.get("TRADEAI_OVERVIEW_BUILD_MAX_MB") or DEFAULT_MAX_MB)
    except ValueError:
        cap_mb = DEFAULT_MAX_MB
    if cap_mb <= 0:
        return "memory cap: not applied (TRADEAI_OVERVIEW_BUILD_MAX_MB <= 0)"
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        want = cap_mb * 1024 * 1024
        if soft != resource.RLIM_INFINITY and soft <= want:
            return f"memory cap: kept the existing limit ({soft // (1024 * 1024)} MB)"
        new_hard = hard if hard != resource.RLIM_INFINITY and hard < want else want
        resource.setrlimit(resource.RLIMIT_AS, (min(want, new_hard), hard))
        return f"memory cap: RLIMIT_AS {min(want, new_hard) // (1024 * 1024)} MB"
    except (ValueError, OSError, AttributeError) as exc:  # pragma: no cover - platform dependent
        return f"memory cap: not applied ({type(exc).__name__})"


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
    cap_note = _cap_memory()
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
    print(json.dumps({**summary, "memory_cap": cap_note}, indent=1, sort_keys=True, default=str))
    return 1 if summary.get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
