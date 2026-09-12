#!/usr/bin/env python3
"""FREE_FIRST_ONLY classifier. Never calls a paid provider.

  PYTHONPATH=. python scripts/free_first_refresh.py --root .
  PYTHONPATH=. python scripts/free_first_refresh.py --root . --json
  PYTHONPATH=. python scripts/free_first_refresh.py --root . --circulate --json --max-searx 1

--circulate is the production path (Hermes → RAG → structured → residual SearXNG).
--max-searx 1 enables residual SearXNG only; circulate_symbol still skips resolved symbols.
This module never calls dispatch_paid_provider.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.baseline_curation import project_baseline_universe  # noqa: E402
from scripts.lib.free_first_circulation import circulate_universe  # noqa: E402
from scripts.lib.free_first_refresh import run_free_first  # noqa: E402

AUTHORITY = "READ_ONLY_ADVISORY"
LOCK_PATH = "/tmp/tradeai_free_first_circulation.lock"
OVERLAP_EXIT = 75
RECEIPT = "data/cio/free_first_last_run.json"
BASELINE_RECEIPT = "data/cio/baseline_curation_last_run.json"
#: Deliberately a SEPARATE file. Overwriting RECEIPT on failure would destroy
#: the last known-good run, which is the record freshness is measured against.
FAILURE_RECEIPT = "data/cio/free_first_last_failure.json"
PAID_PROVIDER_DISPATCH_ALLOWED = False


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _source_sha(root: Path) -> str:
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "GIT_SHA"):
        p = root / name
        if p.is_file():
            return p.read_text(encoding="utf-8").strip().split()[0]
    return ""


def _stamp(report: dict, *, root: Path, started: str) -> dict:
    out = dict(report)
    out["source_sha"] = _source_sha(root)
    out["run_id"] = os.getenv("FREE_FIRST_RUN_ID") or str(uuid.uuid4())
    out["started_at"] = started
    out["finished_at"] = _now()
    out["paid_provider_dispatch_allowed"] = PAID_PROVIDER_DISPATCH_ALLOWED
    out["mode"] = out.get("mode") or "FREE_FIRST_ONLY"
    out["authority"] = AUTHORITY
    return out


def _write_receipt(root: Path, report: dict, *, path: str = RECEIPT) -> None:
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


def acquire_lock(path: str = LOCK_PATH):
    """Non-blocking exclusive lock. Returns (fd, None) or (None, overlap_report)."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None, {
            "schema": "FreeFirstOverlap@v1",
            "ok": False,
            "overlap": True,
            "lock": path,
            "authority": AUTHORITY,
            "paid_dispatch_entered": 0,
            "as_of": _now(),
        }
    return fd, None


def release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-searx", type=int, default=0, help="0 = do not hit SearXNG; 1+ = residual only")
    ap.add_argument("--circulate", action="store_true", help="real Hermes/RAG/structured path")
    ap.add_argument(
        "--project-baseline",
        action="store_true",
        help="write BASELINE_PROJECTION curation snapshots from existing graph/state; no research, no paid",
    )
    ap.add_argument("--symbols", default="", help="comma-separated canary list")
    ap.add_argument(
        "--deadline-seconds",
        type=float,
        default=None,
        help=(
            "stop circulating after this many seconds and report PARTIAL_DEADLINE. "
            "Set it BELOW the unit's TimeoutStartSec so the run writes a receipt "
            "instead of being SIGTERM'd with nothing durable."
        ),
    )
    ap.add_argument(
        "--cursor-path",
        default="",
        help="resume file so successive bounded runs sweep the universe",
    )
    args = ap.parse_args()
    root = Path(args.root)
    started = _now()
    fd, overlap = acquire_lock()
    if overlap is not None:
        if args.json:
            print(json.dumps(overlap, indent=2, default=str))
        else:
            print("FREE_FIRST_ONLY overlap: lock held; not killing the first worker")
        return OVERLAP_EXIT
    try:
        os.environ["FREE_FIRST_SOURCE_SHA"] = _source_sha(root)
        if args.project_baseline:
            if args.circulate:
                print("refusing --circulate with --project-baseline", file=sys.stderr)
                return 2
            syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
            report = project_baseline_universe(str(root), symbols=syms)
        elif args.circulate:
            syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
            report = circulate_universe(
                str(root),
                symbols=syms,
                allow_searx=int(args.max_searx) > 0,
                deadline_seconds=args.deadline_seconds,
                cursor_path=(args.cursor_path or None),
            )
            report.pop("rows", None)
        else:
            report = run_free_first(str(root), max_searx=int(args.max_searx))
            report.pop("rows", None)
        report = _stamp(report, root=root, started=started)
        _write_receipt(root, report, path=BASELINE_RECEIPT if args.project_baseline else RECEIPT)
        if args.json:
            print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2, default=str) if args.project_baseline else json.dumps(report, indent=2, default=str))
            return 0
        print(f"FREE_FIRST_ONLY authority={AUTHORITY} paid_attempted={report.get('paid_calls_attempted', report.get('paid_dispatch_entered', 0))}")
        print(f"total={report.get('total_symbols')} no_new_info={report.get('no_new_info', report.get('fresh_no_change'))}")
        print(
            f"Hermes_reuse={report.get('existing_Hermes_reuse', report.get('Hermes_resolved'))} "
            f"structured={report.get('structured_resolved')} "
            f"unresolved={report.get('unresolved_after_free')} "
            f"Flash_eligible={report.get('Flash_eligible_count')}"
        )
        print(f"Flash_symbols={list(report.get('Flash_symbols') or [])[:20]}")
        return 0
    except BaseException as exc:  # noqa: BLE001 — includes SystemExit/KeyboardInterrupt
        # The receipt was only ever written on success, so every one of the 93
        # timeout kills between 2026-09-08 and 2026-09-12 left the 2026-09-07
        # receipt in place and the lane looked alive. Record the failure where
        # the health predicate already looks.
        failure = _stamp(
            {
                "schema": "FreeFirstCirculationFailure@v1",
                "authority": AUTHORITY,
                "mode": "FREE_FIRST_ONLY",
                "outcome": "FAILED",
                "completion": "FAILED",
                "error_class": type(exc).__name__,
                "error_message": str(exc)[:500],
                "total_symbols": 0,
                "symbols_circulated": 0,
                "paid_dispatch_entered": 0,
                "financial_action": False,
            },
            root=root,
            started=started,
        )
        try:
            _write_receipt(root, failure, path=FAILURE_RECEIPT)
        except Exception:  # noqa: BLE001 — never mask the original failure
            pass
        raise
    finally:
        release_lock(fd)


if __name__ == "__main__":
    raise SystemExit(main())
