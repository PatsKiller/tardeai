"""Durable receipt for legacy CLI jobs without changing their action or exit code.

Only a receipt path is added to the CLI. The wrapped job still owns its argument
parser and return value. Receipt summaries never contain stdout, exception text,
credentials, or a claim that an accepted notification was delivered.

``ok_at`` (added 2026-10-10, n8n refactor wave 1) is the registry ``json_key`` freshness key: it
advances to ``as_of`` only when the job exited 0 and is carried forward from the previous receipt
otherwise, so a failing job keeps writing receipts without ever looking fresh. ``summary_from``
lets a job add its own small, non-secret result fields (e.g. a health status) to the summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from .atomic_json_store import atomic_write_json
from .lane_registry import state_root

T = TypeVar("T")
SCHEMA = "ScheduledJobReceipt@v1"


def default_receipt(script: str, root: Path) -> Path:
    state = os.environ.get("TRADEAI_STATE_ROOT")
    runtime = (Path(state) if state else state_root()) / "data/runtime"
    return runtime / f"{script}_last.json"


def _previous_ok_at(path: Path) -> Any:
    try:
        return (json.loads(Path(path).read_text(encoding="utf-8")) or {}).get("ok_at")
    except Exception:  # noqa: BLE001 — no previous receipt
        return None


def run_with_receipt(
    action: Callable[[], T],
    *,
    script: str,
    root: Path,
    summary_from: Callable[[], Mapping[str, Any]] | None = None,
) -> T:
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
            if summary_from is not None:
                try:
                    extra = summary_from() or {}
                    summary.update({k: v for k, v in extra.items() if k not in ("state", "exception_type")})
                except Exception:  # noqa: BLE001 — extra fields never mask the job's own result
                    pass
            as_of = datetime.now(timezone.utc).isoformat()
            atomic_write_json(
                args.receipt,
                {
                    "schema": SCHEMA,
                    "as_of": as_of,
                    "exit": code,
                    "ok_at": as_of if code == 0 else _previous_ok_at(args.receipt),
                    "summary": summary,
                },
            )
