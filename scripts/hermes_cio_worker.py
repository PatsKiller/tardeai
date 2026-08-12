#!/usr/bin/env python3
"""CIO Hermes research worker CLI.

  PYTHONPATH=scripts python3 -m scripts.hermes_cio_worker --once
  PYTHONPATH=scripts python3 -m scripts.hermes_cio_worker --research-id res_...
  PYTHONPATH=scripts python3 -m scripts.hermes_cio_worker --drain --max 5

Claim → backend.run → validate → persist → on_hermes_completed (attach + resynth).
READ_ONLY_ADVISORY. No Telegram imports in worker package (hook injects CIO side-effects).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m scripts.hermes_cio_worker` from repo root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CIO Hermes research worker")
    p.add_argument("--once", action="store_true", help="Process up to 1 job and exit")
    p.add_argument("--drain", action="store_true", help="Process up to --max jobs")
    p.add_argument("--max", type=int, default=5, help="Max jobs for --drain (default 5)")
    p.add_argument("--research-id", type=str, default="", help="Process explicit research_id")
    p.add_argument("--worker-id", type=str, default="hermes-cio-worker-1")
    p.add_argument(
        "--backend",
        choices=("stub", "catalyst", "bridge", "live"),
        default=None,
        help="Research backend (default: HERMES_BACKEND env or stub)",
    )
    p.add_argument("--no-callback", action="store_true", help="Skip CIO attach/resynth hook")
    p.add_argument("--json", action="store_true", help="Print JSON summary")
    args = p.parse_args(argv)

    try:
        from lib import cio_hermes_research as store
        from lib.hermes_worker import HermesWorker
        from lib.hermes_research_backend import build_hermes_backend
        from lib.hermes_research_loop import on_hermes_completed, on_hermes_failed
    except Exception:
        from scripts.lib import cio_hermes_research as store  # type: ignore
        from scripts.lib.hermes_worker import HermesWorker  # type: ignore
        from scripts.lib.hermes_research_backend import build_hermes_backend  # type: ignore
        from scripts.lib.hermes_research_loop import on_hermes_completed, on_hermes_failed  # type: ignore

    backend = build_hermes_backend(args.backend)
    worker = HermesWorker(
        store=store,
        backend=backend,
        worker_id=args.worker_id,
        on_completed=None if args.no_callback else on_hermes_completed,
        on_failed=None if args.no_callback else on_hermes_failed,
    )

    if args.research_id:
        out = worker.run_research_id(args.research_id)
    elif args.drain:
        out = worker.run_once(limit=max(1, args.max))
    else:
        # default --once
        out = worker.run_once(limit=1)

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(json.dumps(out, sort_keys=True, default=str))
    return 0 if (out.get("ok") is not False and not out.get("errors")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
