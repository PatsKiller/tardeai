#!/usr/bin/env python3
"""warm_caches.py — pre-compute the heavy dashboard caches OUT of the request path.

The portfolio server is single-threaded (shared DB connection). The rotation engine subprocess is ~50s,
so a cold /api/v2/rotation/summary request used to block the whole server long enough for the health-probe
watchdog to kill+restart it — a loop that blanked the dashboard. This runs the heavy compute in its own
process on a cron and writes the disk cache the server serves; the request path never runs the engine.

Run via cron every ~8 min (with .env loaded for DB creds)."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402  (defines _rotation_summary; importing does not start the server)


def main():
    t0 = time.time()
    try:
        api_v2._rotation_summary(force=True)   # computes + writes data/runtime/rotation_summary_cache.json
        print(f"[warm_caches] rotation_summary warmed in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"[warm_caches] rotation_summary FAILED: {str(e)[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
