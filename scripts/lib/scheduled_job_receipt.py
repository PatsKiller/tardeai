"""Durable receipt for legacy CLI jobs without changing their action or exit code.

Only a receipt path is added to the CLI. The wrapped job still owns its argument
parser and return value. Receipt summaries never contain stdout, exception text,
credentials, or a claim that an accepted notification was delivered.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from .atomic_json_store import atomic_write_json
from .lane_registry import state_root

T = TypeVar("T")
SCHEMA = "ScheduledJobReceipt@v1"


def default_receipt(script: str, root: Path) -> Path:
    state = os.environ.get("TRADEAI_STATE_ROOT")
    runtime = (Path(state) if state else state_root()) / "data/runtime"
    return runtime / f"{script}_last.json"


def run_with_receipt(action: Callable[[], T], *, script: str, root: Path) -> T:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--receipt", type=Path, default=default_receipt(script, root))
    args, remaining = parser.parse_known_args(sys.argv[1:])
    original = sys.argv[:]
    sys.argv[:] = [original[0], *remaining]
    code = 0
    summary: dict = {"state": "completed"}
    # Help is argument inspection, not evidence that a scheduled job ran.
    help_only = "--help" in remaining or "-h" in remaining
    try:
        result = action()
        if isinstance(result, int):
            code = int(result)
        if isinstance(result, dict):
            summary.update({k: result[k] for k in ("pending", "total", "fail", "ok") if k in result})
        summary["state"] = "completed" if code == 0 else "failed"
        return result
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        summary["state"] = "completed" if code == 0 else "failed"
        raise
    except BaseException as exc:
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
        summary = {"state": "failed", "exception_type": type(exc).__name__}
        raise
    finally:
        sys.argv[:] = original
        if not help_only:
            atomic_write_json(
                args.receipt,
                {
                    "schema": SCHEMA,
                    "as_of": datetime.now(timezone.utc).isoformat(),
                    "exit": code,
                    "summary": summary,
                },
            )
