#!/usr/bin/env python3
"""Warm (or refresh) the Hermes trend indexes after a deploy.

The outcome-bus and governed-universe trends are served from ``scripts/lib/hermes_trend_index.py``. The index is
built lazily and incrementally, but the first call after a deploy would still pay for the backlog (134 outcome
snapshots of up to 22 MB, 1,100 universe snapshots). Run this once after promoting so the first user request is fast.

Read-only against the snapshot stores; writes only the compact index files next to them
(``<history parent>/trend_index/*.json``). Exit 0 on success, 1 if either index could not be built.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30, help="window to warm (1-90; default 30)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = {}
    rc = 0
    for name, loader in (
        ("outcome_bus", "lib.hermes_outcome_bus.bus", "load_outcome_bus_trend"),
        ("universe", "lib.hermes_scope_governor.universe", "load_universe_trend"),
    ):
        t0 = time.monotonic()
        try:
            mod = __import__(loader[0], fromlist=[loader[1]])
            fn = getattr(mod, loader[1])
            out = fn(days=args.days)
            results[name] = {"ok": True, "seconds": round(time.monotonic() - t0, 2), "days": out.get("days")}
        except Exception as exc:  # noqa: BLE001 — report, do not fail the deploy
            rc = 1
            results[name] = {"ok": False, "seconds": round(time.monotonic() - t0, 2), "error": f"{type(exc).__name__}: {exc}"}

    if args.json:
        import json

        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for name, r in results.items():
            print(f"trend index {name}: {'ok' if r['ok'] else 'FAILED'} in {r['seconds']}s"
                  + ("" if r["ok"] else f" — {r['error']}"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
