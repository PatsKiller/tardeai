"""Run a script's ``main()`` and write its lane receipt (LQ-20261107-1058).

Several lanes used to share one cron log as their output signal, so a run of any one turned all of them green.
Each real run now writes ``data/runtime/<lane>_last.json`` (LaneRunReceipt@v1, ``ok_at`` advances only on
success), and the registry points the lane at that receipt instead of the shared log.

Only a real run (``--apply`` on the command line) writes: a preview run leaves no receipt, so a preview cannot
make a lane look fresh. A failure, an exception or a SystemExit is recorded and then propagated unchanged.
The receipt write itself never raises (``write_lane_receipt`` swallows its own errors).
"""
from __future__ import annotations

import sys
from typing import Callable, Optional, Sequence

try:
    from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
except ImportError:  # scripts/ on sys.path, repo root not
    from lib.lane_last_receipt import now_iso, write_lane_receipt  # type: ignore[no-redef]


def _code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    return exc.code if isinstance(exc.code, int) else 1


def run_main(lane: str, main: Callable[[], Optional[int]], *, script: str,
             argv: Optional[Sequence[str]] = None) -> int:
    """``main()``'s exit code; on a real run, also the lane receipt for this attempt."""
    real = "--apply" in (sys.argv[1:] if argv is None else list(argv))
    started = now_iso()

    def _write(rc: int, error: Optional[str] = None) -> None:
        if real:
            write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script=script, error=error,
                               summary={"completed": rc == 0})

    try:
        rc = main()
    except SystemExit as exc:
        _write(_code(exc))
        raise
    except BaseException as exc:
        _write(1, type(exc).__name__)
        raise
    rc = int(rc or 0)
    _write(rc)
    return rc
