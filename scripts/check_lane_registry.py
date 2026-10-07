#!/usr/bin/env python3
"""check_lane_registry.py — a scheduled job with no declaration fails the build.

Same shape as `check_dark_contracts.py`, which is the working precedent here:
declare intent, seed a baseline of inherited debt so the gate is green on day
one, and let the gate catch drift from then on. The baseline can only shrink.

Rules, in the order they are reported:

  1. A registry row that is structurally invalid fails. In particular a row
     with no `output_signal` fails — a lane is verified by a durable artifact,
     never by an exit code, and exit code 0 has been wrong about this system
     three times.
  2. A non-ACTIVE row with no `state_reason` or no `state_since` fails.
     RETIRED and PAUSED are declared states, not absences.
  3. A NEW scheduled job (cron or systemd) that is neither declared nor in the
     inherited-debt baseline fails.

Exit codes are distinct on purpose, because a gate returning 2 for a missing
file reads identically to a pass and that has happened in this repository:

    0  clean
    1  a rule above was violated
    2  the gate could not run (registry unreadable, discovery unavailable)

Usage:
    python3 scripts/check_lane_registry.py            # report
    python3 scripts/check_lane_registry.py --fail-on-new
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_CANNOT_RUN = 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-on-new", action="store_true",
                    help="exit 1 on any violation (CI mode)")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--discovery-json", default=None,
                    help="read the scheduler inventory from this file instead of "
                         "the live host. The mutation test needs it: CI has no "
                         "crontab and no systemd, so live discovery returns empty "
                         "there and a gate that can only pass would look correct.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--state-drift", action="store_true",
                    help="also classify each lane's declared state against the host (timer enabled? cron line "
                         "present?). 2026-10-07: two NEVER_SCHEDULED rows were running and this gate said clean.")
    ap.add_argument("--host-state-json", default=None,
                    help="captured {\"timers\": {unit: {unit_file_state, sub_state, next_elapse, recurring}}} for "
                         "CI and tests; without it and without systemd, systemd lanes are NOT_MEASURED")
    args = ap.parse_args()

    try:
        from scripts.lib.lane_registry import (
            STATE_ACTIVE, discover_all, find_undeclared, load_registry,
            validate_registry,
        )
    except Exception as e:                                  # cannot run != pass
        print(f"lane-registry gate CANNOT RUN: {type(e).__name__}: {e}",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    path = Path(args.registry) if args.registry else None
    try:
        reg = load_registry(path)
    except Exception as e:
        print(f"lane-registry gate CANNOT RUN: registry unreadable: {e}",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    rows = reg.get("lanes") or []
    if not rows:
        print("lane-registry gate CANNOT RUN: registry declares no lanes",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    errors = validate_registry(reg)
    if args.discovery_json:
        try:
            found = json.loads(Path(args.discovery_json).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"lane-registry gate CANNOT RUN: discovery unreadable: {e}",
                  file=sys.stderr)
            return EXIT_CANNOT_RUN
    else:
        found = discover_all()
    undeclared = find_undeclared(reg, found)

    active = sum(1 for r in rows if r.get("state") == STATE_ACTIVE)
    # Count the FIELD, not the prose. This grepped state_reason for the literal
    # word "UNKNOWN" and so reported 2 the moment the reasons were rewritten,
    # while 8 lanes still carried reason_confidence=UNKNOWN.
    unknown = [r["lane_id"] for r in rows
               if r.get("state") != STATE_ACTIVE
               and str(r.get("reason_confidence") or "UNKNOWN") == "UNKNOWN"]
    correlated = [r["lane_id"] for r in rows
                  if str(r.get("reason_confidence") or "") == "CORRELATED"]

    drift_rows: list = []
    drift_conflicts: list = []
    if args.state_drift:
        from scripts.lib.lane_state_drift import classify_lanes, conflicts, timer_state
        host_state = None
        if args.host_state_json:
            host_state = json.loads(Path(args.host_state_json).read_text(encoding="utf-8"))
        drift_rows = classify_lanes(rows, cron_rows=found.get("cron") or [],
                                    timer_state_fn=None if args.host_state_json else timer_state,
                                    host_state=host_state)
        drift_conflicts = conflicts(drift_rows)

    if args.json:
        print(json.dumps({"declared": len(rows), "active": active,
                          "state_drift": drift_rows if args.state_drift else None,
                          "state_drift_conflicts": [r["lane_id"] for r in drift_conflicts],
                          "errors": errors, "undeclared": undeclared,
                          "unknown_reason_lanes": unknown,
                          "correlated_reason_lanes": correlated}, indent=2))
    else:
        print(f"declared lanes          : {len(rows)}  ({active} ACTIVE)")
        print(f"inherited-debt baseline : {len(reg.get('undeclared_baseline') or [])}")
        for _t in reg.get("inherited_tranches") or []:
            print(f"inherited tranche {_t.get('added')}: {len(_t.get('lines') or [])} lines — {str(_t.get('reason'))[:90]}…")
        print(f"reason ESTABLISHED     : "
              f"{sum(1 for r in rows if r.get('reason_confidence') == 'ESTABLISHED')}")
        print(f"reason CORRELATED      : {len(correlated)}"
              " (successor runs; equivalence NOT verified)")
        print(f"reason UNKNOWN         : {len(unknown)}"
              + (f"  {unknown}" if unknown else ""))
        print(f"structural errors       : {len(errors)}")
        for e in errors:
            print(f"    ✗ {e}")
        print(f"undeclared (NEW)        : {len(undeclared)}")
        for u in undeclared:
            print(f"    ✗ {u['kind']}: {u['expression'][:110]}")
        if args.state_drift:
            nm = sum(1 for r in drift_rows if r["code"] == "NOT_MEASURED")
            print(f"state drift conflicts   : {len(drift_conflicts)}  ({nm} NOT_MEASURED)")
            for r in drift_conflicts:
                print(f"    ✗ {r['lane_id']}: declared {r['declared_state']} but {r['code']} {r['evidence']}")
        if not errors and not undeclared and not drift_conflicts:
            print("lane registry: clean")

    if args.fail_on_new and drift_conflicts:
        print("\nA lane's declared state must match the host: a RETIRED or NEVER_SCHEDULED row\n"
              "whose timer is enabled or whose cron line is present is a false registry. Flip the\n"
              "row (with state_since and evidence) or retire the job — never leave both.", file=sys.stderr)
        return EXIT_VIOLATION
    if args.fail_on_new and (errors or undeclared):
        print("\nA scheduled job must be declared in config/lane_registry.json.\n"
              "Add a row with an output_signal naming the durable artifact that\n"
              "proves it ran — not its exit code, not its log file existing.\n"
              "If it is deliberately off, declare RETIRED or PAUSED with a\n"
              "state_reason and state_since. 'Off' must be a reported state.",
              file=sys.stderr)
        return EXIT_VIOLATION
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
