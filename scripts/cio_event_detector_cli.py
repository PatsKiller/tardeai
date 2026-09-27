#!/usr/bin/env python3
"""CLI for one CIO event-detector cycle (replaces three `python3 -c "…"` cron one-liners).

R-10 (2026-09-26): crontab lines 897–899 ran the detector through an inline
`python3 -c "... print(f'Wakes: {r.get("wakes_created",0)}')"`. The inner double
quotes ended the shell string, so every run finished with
`NameError: name 'wakes_created' is not defined`, exited non-zero and flooded
`cio_detector_*.log` with tracebacks. The detector itself ran; the reporting
did not. Cron should call this file instead:

  $PY scripts/cio_event_detector_cli.py --period daily|weekly|monthly
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NO_CONSUMER_REASON = "cron entry point; stdout/log is the consumer (three crontab lines)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--period", choices=("daily", "weekly", "monthly"), default="daily",
                    help="label only — the detector decides what is due; recorded in the summary line")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from scripts.lib.cio_event_detector import run_cio_event_detector_once
    r = run_cio_event_detector_once() or {}
    if args.json:
        print(json.dumps({"period": args.period, **(r if isinstance(r, dict) else {"result": str(r)})}, default=str))
    else:
        print(f"[{args.period}] Wakes: {r.get('wakes_created', 0) if isinstance(r, dict) else r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
