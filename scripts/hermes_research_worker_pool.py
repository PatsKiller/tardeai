#!/usr/bin/env python3
"""hermes_research_worker_pool.py — White-Space Discovery worker-pool CLI.

Runs the research worker lanes declared in
config/hermes_research_worker_lanes.yaml through
lib/hermes_discovery/worker_pool.py: a bounded pool (max 4 threads) where
every lane gets a flock-style lock, a cadence gate, a wall-clock timeout, a
per-run candidate cap, per-lane domain/citation fences, and the SAME
do-no-harm intake gate (schedule caps + scorecard pause/tighten) the
scheduled ingestors and coverage adapters run under.

Lanes only ever write DISCOVERY CANDIDATES via inbox.upsert_candidate —
promotion is structurally impossible (promotion_allowed must be false in
every lane; validated fail-closed). Lanes without a registered runner yet
(Stages 2-4 register theirs via worker_pool.register_lane_runner) are
reported skipped ("no_runner"). Explicit --dry-run is an offline plan before loading runners.
Real --run writes a durable receipt; failed or entirely skipped pools preserve previous ok_at.

Usage:
  python3 scripts/hermes_research_worker_pool.py --run [--lane X ...]
                                                 [--dry-run] [--force] [--json]
  python3 scripts/hermes_research_worker_pool.py --list-lanes [--json]
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LANE_ID = "hermes-research-worker-pool"
worker_pool = None

# Stage-6 integration fix: the lane-runner modules register their runners at
# import time (worker_pool.register_lane_runner in each module body), so the
# CLI must import them or --list-lanes / --run would report runner=NO for
# lanes that ARE implemented. Tolerant on purpose: one broken lane module
# (missing dep, bad domain pack, ...) must never take down the whole pool —
# that lane simply stays unregistered and the import failure is noted.
_RUNNER_MODULES = ("white_space", "strategy_discovery", "private_proxy",
                   "loft_law")
RUNNER_IMPORT_ERRORS: dict[str, str] = {}
def _load_dependencies():
    global worker_pool
    from lib.hermes_discovery import worker_pool as pool
    worker_pool = pool
    for mod in _RUNNER_MODULES:
        try:
            importlib.import_module(f"lib.hermes_discovery.{mod}")
        except Exception as exc:  # noqa: BLE001 — isolate a failed runner import
            RUNNER_IMPORT_ERRORS[mod] = f"{type(exc).__name__}: {exc}"


def _print_report(report: dict) -> None:
    if report.get("error"):
        print(f"ERROR: {report['error']}")
        return
    print(f"do_no_harm={report['do_no_harm']} "
          f"paused={report['caps_applied'].get('paused')} "
          f"dry_run={report['dry_run']} max_workers={report['max_workers']}")
    for lane_id, res in report["lanes"].items():
        if res.get("error"):
            print(f"[{lane_id}] ERROR: {res['error']}")
            continue
        if res.get("skipped"):
            print(f"[{lane_id}] skipped: {res['skipped']}")
            continue
        print(f"[{lane_id}] scanned={res['scanned']} upserted={res['upserted']} "
              f"skipped_payloads={res['skipped_payloads']} "
              f"duration_ms={res.get('duration_ms')}")
        for c in res.get("candidates") or []:
            extra = f" #{c['id']} {c.get('status')}" if "id" in c else ""
            print(f"    {c.get('candidate_type')} {c.get('label')!r}{extra}")
        if res.get("skipped_reasons"):
            print(f"    skipped_reasons: {res['skipped_reasons']}")
    if report.get("skipped_reasons"):
        print(f"pool skipped_reasons: {report['skipped_reasons']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run the selected lanes")
    ap.add_argument("--lane", action="append", default=None, metavar="X",
                    help="lane id to run (repeatable; default: all lanes)")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline plan; no dependency imports, DB or writes")
    ap.add_argument("--force", action="store_true",
                    help="ignore per-lane cadence state")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--list-lanes", action="store_true",
                    help="show lane configs + registered runners")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN {LANE_ID}: would run the bounded advisory discovery worker pool")
        return 0
    record = args.run and not args.list_lanes
    if record:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
        started = now_iso()
    try:
        _load_dependencies()
    except Exception as exc:
        if record:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                               script="hermes_research_worker_pool.py", error=f"{type(exc).__name__}: {exc}")
        raise

    if args.list_lanes:
        try:
            lanes = worker_pool.load_lanes()
        except worker_pool.LaneConfigError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        runners = set(worker_pool.registered_lanes())
        if args.json:
            out = {lane_id: {**cfg, "runner_registered": lane_id in runners}
                   for lane_id, cfg in lanes.items()}
            if RUNNER_IMPORT_ERRORS:
                out["_runner_import_errors"] = dict(RUNNER_IMPORT_ERRORS)
            print(json.dumps(out, indent=2, default=str))
        else:
            for lane_id, cfg in lanes.items():
                print(f"{lane_id}: enabled={cfg['enabled']} "
                      f"cadence={cfg['cadence_minutes']}m "
                      f"cap={cfg['max_candidates_per_run']} "
                      f"sensitive={cfg['sensitive_domain']} "
                      f"runner={'yes' if lane_id in runners else 'NO'}")
            for mod, err in RUNNER_IMPORT_ERRORS.items():
                print(f"NOTE: lane module lib.hermes_discovery.{mod} failed "
                      f"to import — its runner is unregistered: {err}",
                      file=sys.stderr)
        return 0

    if not args.run:
        ap.print_help()
        return 2

    for mod, err in RUNNER_IMPORT_ERRORS.items():
        print(f"NOTE: lane module lib.hermes_discovery.{mod} failed to "
              f"import — its runner is unregistered: {err}", file=sys.stderr)
    try:
        report = worker_pool.run_pool(args.lane, dry_run=False, force=args.force)
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           script="hermes_research_worker_pool.py", error=f"{type(exc).__name__}: {exc}")
        raise
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)
    rc = 1 if report.get("error") else 0
    lanes = list((report.get("lanes") or {}).values())
    failures = sum(bool(r.get("error")) for r in lanes)
    skips = sum(bool(r.get("skipped")) for r in lanes)
    completed = len(lanes) - failures - skips
    summary = {"completed_lanes": completed, "failed_lanes": failures, "skipped_lanes": skips,
               "scanned": sum(int(r.get("scanned") or 0) for r in lanes),
               "upserted": sum(int(r.get("upserted") or 0) for r in lanes)}
    healthy = rc == 0 and failures == 0 and completed > 0
    write_lane_receipt(LANE_ID, ok=healthy, exit_code=rc, started_at=started,
                       script="hermes_research_worker_pool.py", summary=summary,
                       error=None if healthy else "pool_incomplete")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
