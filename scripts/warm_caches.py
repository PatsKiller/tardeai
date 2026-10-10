#!/usr/bin/env python3
"""warm_caches.py — pre-compute the heavy dashboard caches OUT of the request path.

The portfolio server is single-threaded (shared DB connection). The rotation engine subprocess is ~50s,
so a cold /api/v2/rotation/summary request used to block the whole server long enough for the health-probe
watchdog to kill+restart it — a loop that blanked the dashboard. This runs the heavy compute in its own
process on a cron and writes the disk cache the server serves; the request path never runs the engine.

Run via cron every ~8 min (with .env loaded for DB creds).

Refactor wave 1 (2026-10-10):
  --dry-run   prints the plan (each step, the cache it would rewrite, that cache's current age) and
              exits 0 without importing api_v2 or rotation_autopilot: nothing is computed, written,
              proposed or sent. The warm steps compute and write in one call (and the rotation step
              also writes rotation_stops_latest.json mid-compute), so no deeper preview can be taken
              without reaching a write.
  real run    unchanged steps, but exits 1 when ANY step failed (trade_ai and the autopilot tick used
              to fail with exit 0), and writes data/runtime/warm-caches_last.json (LaneRunReceipt@v1;
              ok_at only when every step succeeded) with per-step seconds and peak RSS.
"""

import argparse
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LANE_ID = "warm-caches"

# (step, cache written under data/runtime, what the step does)
STEPS = (
    (
        "rotation_summary",
        "rotation_summary_cache.json",
        "api_v2._rotation_summary(force=True): rotation engine subprocess + cache rewrite",
    ),
    ("trade_ai", "trade_ai_cache.json", "api_v2.trade_ai(force=True): scanner compute + cache rewrite"),
    (
        "rotation_autopilot",
        "rotation_autopilot_latest.json",
        "rotation_autopilot.run_autopilot_tick(trigger='warm_caches'): may run the small-cap bridge, "
        "auto_proposal_generator and a Telegram alert",
    ),
)


def _runtime_dir() -> Path:
    from lib.persistent_state_root import resolve_durable_dir

    return Path(resolve_durable_dir("data/runtime", ROOT))


def plan() -> list:
    """Read-only: each step and the current age of the cache it would rewrite (stat only)."""
    rt = _runtime_dir()
    now = time.time()
    out = []
    for step, cache, what in STEPS:
        p = rt / cache
        try:
            age = round(now - p.stat().st_mtime)
        except OSError:
            age = None
        out.append({"step": step, "cache": str(p), "cache_age_s": age, "action": what})
    return out


def _peak_rss_mb() -> dict:
    # ru_maxrss is KiB on Linux. CHILDREN covers the rotation engine subprocess.
    return {
        "self_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "children_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
    }


def _receipt(ok: bool, rc: int, started: datetime, steps: dict, failed: list) -> None:
    from lib.lane_last_receipt import write_lane_receipt

    write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=rc,
        started_at=started,
        summary={"steps_s": steps, "failed": failed, "peak_rss": _peak_rss_mb()},
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="pre-warm the heavy dashboard caches")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; compute/write/send nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        # Returns BEFORE api_v2 / rotation_autopilot are even imported (AGENTS.md §6).
        for row in plan():
            print(
                f"[warm_caches] DRY RUN: would run {row['step']} -> {row['cache']} "
                f"(current age {row['cache_age_s']}s): {row['action']}"
            )
        print("[warm_caches] DRY RUN: nothing computed, written, proposed or sent; no receipt")
        return 0

    started = datetime.now(timezone.utc)
    steps: dict = {}
    failed: list = []
    import api_v2  # noqa: E402  (defines _rotation_summary; importing does not start the server)

    t0 = time.time()
    try:
        api_v2._rotation_summary(force=True)  # computes + writes data/runtime/rotation_summary_cache.json
        steps["rotation_summary"] = round(time.time() - t0, 1)
        print(f"[warm_caches] rotation_summary warmed in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"[warm_caches] rotation_summary FAILED: {str(e)[:200]}")
        _receipt(False, 1, started, steps, ["rotation_summary"])
        return 1

    # Market Opportunities Scanner — heavy (run JSONs + hundreds-row trade_ai_scans). Warm it OUT of
    # the request path so the single-threaded server never blocks on it (the 2026-06-25 outage).
    t_ta = time.time()
    try:
        api_v2.trade_ai(force=True)  # computes + writes data/runtime/trade_ai_cache.json
        steps["trade_ai"] = round(time.time() - t_ta, 1)
        print(f"[warm_caches] trade_ai warmed in {time.time() - t_ta:.1f}s")
    except Exception as e:
        failed.append("trade_ai")
        print(f"[warm_caches] trade_ai FAILED: {str(e)[:200]}")

    # Autonomous trend-switch screening (IWM vs SPY) — lightweight tick every ~8 min
    t1 = time.time()
    try:
        from rotation_autopilot import run_autopilot_tick

        ap_res = run_autopilot_tick(trigger="warm_caches")
        steps["rotation_autopilot"] = round(time.time() - t1, 1)
        if ap_res.get("bridge_ran"):
            print(
                f"[warm_caches] rotation_autopilot bridge ran ({ap_res.get('bridge_reason')}) "
                f"in {time.time() - t1:.1f}s"
            )
        elif ap_res.get("rotation", {}).get("signal") == "small_cap_outperform":
            print(f"[warm_caches] rotation active, bridge throttled ({ap_res.get('bridge_reason')})")
    except Exception as e:
        failed.append("rotation_autopilot")
        print(f"[warm_caches] rotation_autopilot FAILED: {str(e)[:200]}")

    rc = 1 if failed else 0
    _receipt(not failed, rc, started, steps, failed)
    if failed:
        print(f"[warm_caches] exit 1: failed steps {failed}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
