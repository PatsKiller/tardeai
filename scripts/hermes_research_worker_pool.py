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
every lane; validated fail-closed).

Fail closed on zero output (2026-10-15). From 2026-07-05 to 2026-10-15 three
enabled lanes (tax_retirement, system_ops, custom_domain) reported
"skipped: no_runner" every hour and the pool exited 0. Now every selected lane
gets a lane_outcome checked against its declared expected_output_hours; an
enabled lane with no runner, a runner error, or no payload for longer than its
window is a FAILURE:

  exit 0   every selected lane healthy (produced / not_due / within window /
           disabled with a reason / do-no-harm pause)
  exit 1   pool-level error (lane or schedule config, unknown lane)
  exit 3   one or more lane failures (report["failures"]); receipt status failed

The lane receipt (data/runtime/hermes-research-worker-pool_last.json) is ok —
and ok_at advances — only on exit 0. A run where every lane is merely not due
is ok because each enabled lane's durable output clock (last_output_at in the
worker state file, advanced only by a run that returned payloads) was checked
inside its window; it no longer reads as "entirely skipped".

--dry-run is an offline plan: it imports the lane config and runner modules
(pure imports, no DB), reads the worker state file read-only, prints the plan
with each lane's runner registration and expectation status, writes nothing,
and exits 3 when the plan already shows a failure (an enabled lane without a
runner, or an output clock past its window) — so a dry-run-only n8n shadow
catches zero output too.

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
EXIT_LANE_FAILURES = 3
worker_pool = None

# The lane-runner modules (worker_pool.RUNNER_MODULES) register their runners
# at import time. Tolerant on purpose: one broken lane module never takes down
# the whole pool — its lanes stay unregistered, and run_pool now reports them
# as a no_runner FAILURE (exit 3), never a silent skip.
RUNNER_IMPORT_ERRORS: dict[str, str] = {}


def _load_dependencies():
    global worker_pool
    pool = importlib.import_module("lib.hermes_discovery.worker_pool")
    worker_pool = pool
    RUNNER_IMPORT_ERRORS.update(pool.load_runner_modules())


def _dry_run_plan(lane_ids) -> int:
    """Offline plan: lane config + runner registration + expectation status
    from the worker state file (read-only). No DB, no writes, no model call."""
    pool = importlib.import_module("lib.hermes_discovery.worker_pool")
    import_errors = pool.load_runner_modules()
    try:
        lanes = pool.load_lanes()
    except pool.LaneConfigError as exc:
        print(f"DRY-RUN {LANE_ID}: would refuse to run — lane config invalid: {exc}")
        return 1
    selected = [str(x).strip().lower() for x in (lane_ids or list(lanes))]
    unknown = [x for x in selected if x not in lanes]
    if unknown:
        print(f"DRY-RUN {LANE_ID}: would refuse to run — unknown lane(s) {unknown}")
        return 1
    runners = set(pool.registered_lanes())
    results = {}
    for lane_id in selected:
        cfg = lanes[lane_id]
        if not cfg["enabled"]:
            results[lane_id] = {"lane": lane_id, "skipped": "disabled", "dry_run": True}
        elif lane_id not in runners:
            results[lane_id] = {"lane": lane_id, "skipped": "no_runner", "dry_run": True}
        else:  # the plan does not run the runner; judge the durable clock only
            results[lane_id] = {"lane": lane_id, "skipped": "planned", "dry_run": True}
    outcomes, failures = pool.evaluate_outcomes(lanes, results, dry_run=True)
    plan = {o["lane"]: {"enabled": lanes[o["lane"]]["enabled"],
                        "runner_registered": o["lane"] in runners,
                        "expected_output_hours": lanes[o["lane"]]["expected_output_hours"],
                        "last_output_at": o.get("last_output_at"),
                        "status": o["outcome"], **({"reason": o["reason"]} if o.get("reason") else {})}
            for o in outcomes}
    print(f"DRY-RUN {LANE_ID}: would run the bounded advisory discovery worker pool "
          f"({len(selected)} lane(s); candidates only, no promotion; no DB, no writes "
          f"and no model call in this preview)")
    print(json.dumps({"dry_run": True, "lane_id": LANE_ID, "plan": plan,
                      "failures": failures, "runner_import_errors": import_errors},
                     indent=2, sort_keys=True, default=str))
    # last line, compact: what the n8n executor's 800-char stdout_tail keeps
    print("DRY-RUN-SUMMARY " + json.dumps({
        "ok": not failures,
        "failures": [{"lane": f["lane"], "outcome": f["outcome"]} for f in failures],
        "status": {k: v["status"] for k, v in sorted(plan.items())}}))
    return EXIT_LANE_FAILURES if failures else 0


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
    for lane_id, o in (report.get("lane_outcomes") or {}).items():
        flag = "" if o.get("ok") else "FAIL "
        print(f"  outcome {flag}{lane_id}: {o.get('outcome')}"
              + (f" — {o['reason']}" if o.get("reason") else ""))
    if report.get("failures"):
        print(f"FAILED lanes: {[f['lane'] for f in report['failures']]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run the selected lanes")
    ap.add_argument("--lane", action="append", default=None, metavar="X",
                    help="lane id to run (repeatable; default: all lanes)")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline plan: lane config + runner registration + "
                         "expectation status; no DB, no writes, no model call")
    ap.add_argument("--force", action="store_true",
                    help="ignore per-lane cadence state")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--list-lanes", action="store_true",
                    help="show lane configs + registered runners")
    args = ap.parse_args(argv)
    if args.dry_run:
        return _dry_run_plan(args.lane)
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
    lane_failures = list(report.get("failures") or [])
    if report.get("error"):
        rc = 1
    elif lane_failures or report.get("ok") is not True:
        rc = EXIT_LANE_FAILURES  # fail closed: no ok verdict → not healthy
    else:
        rc = 0
    lanes = list((report.get("lanes") or {}).values())
    errors = sum(bool(r.get("error")) for r in lanes)
    skips = sum(bool(r.get("skipped")) for r in lanes)
    completed = len(lanes) - errors - skips
    outcomes = report.get("lane_outcomes") or {}
    summary = {"completed_lanes": completed, "failed_lanes": len(lane_failures),
               "skipped_lanes": skips,
               "scanned": sum(int(r.get("scanned") or 0) for r in lanes),
               "upserted": sum(int(r.get("upserted") or 0) for r in lanes),
               "lane_outcomes": {k: v.get("outcome") for k, v in outcomes.items()},
               "failures": [{"lane": f.get("lane"), "outcome": f.get("outcome")}
                            for f in lane_failures]}
    healthy = rc == 0
    error = None
    if not healthy:
        error = "pool_error" if rc == 1 else "lane_failures"
    write_lane_receipt(LANE_ID, ok=healthy, exit_code=rc, started_at=started,
                       script="hermes_research_worker_pool.py", summary=summary,
                       error=error)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
