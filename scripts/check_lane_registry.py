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
  4. (AGENTS.md 3.0.0 §23.10 P17) An ACTIVE n8n workflow whose id is neither a
     kind-n8n row's scheduler.expression nor a generated workflow id
     (docs/implementation/n8n-parallel/workflows/generated/INDEX.json) fails as
     UNDECLARED_N8N_WORKFLOW. CI reads the committed snapshot
     (docs/implementation/n8n-parallel/workflows/active_workflows_snapshot.json);
     the host passes --n8n-live (one read-only SELECT through docker exec).
  5. (n8n maturity B5 follow-up) A row with a `dispatch` block whose class its
     retry_policy does not permit (or an unknown policy/class) fails; while the
     row is on cron, `dispatch.cron` must equal the live crontab line's schedule
     (skipped when no crontab is readable, e.g. CI).

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
    ap.add_argument("--n8n-live", action="store_true",
                    help="read ACTIVE n8n workflows live (docker exec m8m-n8n-db psql, SELECT only); "
                         "a failed read is CANNOT RUN (exit 2), never clean")
    ap.add_argument("--n8n-snapshot", default=None,
                    help="read ACTIVE n8n workflows from this snapshot file (default: the committed "
                         "active_workflows_snapshot.json) when --n8n-live is not given")
    ap.add_argument("--no-n8n", action="store_true", help="skip the n8n source entirely")
    ap.add_argument("--n8n-index", default=None,
                    help="generated INDEX.json whose live/shadow ids are the known-id allowlist")
    ap.add_argument("--n8n-snapshot-out", default=None,
                    help="with --n8n-live: also write the active list as a snapshot file (repo file "
                         "refresh; never a host write)")
    args = ap.parse_args()

    try:
        from scripts.lib.lane_registry import (
            STATE_ACTIVE, discover_all, discover_n8n_live, discover_n8n_snapshot,
            find_inactive_n8n_rows, find_undeclared, load_registry, n8n_known_workflow_ids, validate_registry,
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
        found = discover_all(include_n8n=False)
    n8n_source = "off"
    if args.no_n8n:
        found.pop("n8n", None)
    elif "n8n" in found:
        n8n_source = "discovery-json"
    else:
        try:
            if args.n8n_live:
                found["n8n"] = discover_n8n_live()
                n8n_source = "live"
                if args.n8n_snapshot_out:
                    from datetime import datetime, timezone
                    from scripts.lib.n8n_live_inventory import snapshot_doc
                    doc = snapshot_doc([{"id": r["expression"], "name": r.get("name")} for r in found["n8n"]],
                                       captured_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                                       source="docker exec m8m-n8n-db psql -U n8n -d n8n -tAc (SELECT, active only)")
                    Path(args.n8n_snapshot_out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            else:
                found["n8n"] = discover_n8n_snapshot(Path(args.n8n_snapshot) if args.n8n_snapshot else None)
                n8n_source = "snapshot"
        except Exception as e:                              # cannot run != pass
            print(f"lane-registry gate CANNOT RUN: n8n source unreadable: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return EXIT_CANNOT_RUN
    try:
        n8n_known = (n8n_known_workflow_ids(Path(args.n8n_index) if args.n8n_index else None)
                     if found.get("n8n") else {})
    except Exception as e:
        print(f"lane-registry gate CANNOT RUN: generated INDEX unreadable: {e}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    undeclared = find_undeclared(reg, found, n8n_known_ids=n8n_known)
    # Rule 5 (n8n maturity B5 follow-up, 2026-10-09): dispatch blocks. Class must be permitted by its
    # retry_policy (the class_verdict rails), and dispatch.cron must equal the live crontab line while the
    # row is still on cron. No crontab (CI) -> the cron comparison is skipped.
    try:
        from scripts.lib.n8n_dispatch_registry_checks import (
            class_policy_findings, cron_mismatch_findings, dispatch_rows,
        )
        dispatch_findings: list = []
        if dispatch_rows(rows):
            from scripts.lib.n8n_retry_policy import load_policies
            dispatch_findings = class_policy_findings(rows, load_policies())
            dispatch_findings += cron_mismatch_findings(
                rows, [c.get("expression") for c in found.get("cron") or []])
    except Exception as e:                                  # cannot run != pass
        print(f"lane-registry gate CANNOT RUN: dispatch checks: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    # An ACTIVE kind-n8n row needs its workflow active. Judged against the live n8n list, a discovery file
    # that carries n8n, or the committed snapshot when it describes the committed registry (a fixture
    # registry or a discovery file without n8n is not compared with the real host's snapshot).
    compare_inactive = n8n_source in ("live", "discovery-json") or (
        n8n_source == "snapshot" and not args.registry and not args.discovery_json)
    inactive_n8n = find_inactive_n8n_rows(reg, found) if compare_inactive else []

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
                          "n8n_source": n8n_source,
                          "n8n_active": len(found.get("n8n") or []),
                          "inactive_n8n_rows": inactive_n8n,
                          "dispatch_findings": dispatch_findings,
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
        print(f"n8n active workflows    : {len(found.get('n8n') or [])}  (source {n8n_source})")
        print(f"undeclared (NEW)        : {len(undeclared)}")
        for u in undeclared:
            label = f"{u['code']} {u['expression']} {u.get('name') or ''}" if u.get("code") else u["expression"]
            print(f"    ✗ {u['kind']}: {label[:110]}")
        if args.state_drift:
            nm = sum(1 for r in drift_rows if r["code"] == "NOT_MEASURED")
            print(f"state drift conflicts   : {len(drift_conflicts)}  ({nm} NOT_MEASURED)")
            for r in drift_conflicts:
                print(f"    ✗ {r['lane_id']}: declared {r['declared_state']} but {r['code']} {r['evidence']}")
        print(f"inactive n8n rows       : {len(inactive_n8n)}")
        for r in inactive_n8n:
            print(f"    ✗ {r['lane_id']}: declared ACTIVE kind n8n but workflow {r['expression']} is not active")
        print(f"dispatch findings       : {len(dispatch_findings)}")
        for f in dispatch_findings:
            print(f"    ✗ {f['code']} {f['lane_id']}: {f['detail'][:110]}")
        if not errors and not undeclared and not drift_conflicts and not inactive_n8n and not dispatch_findings:
            print("lane registry: clean")

    if args.fail_on_new and drift_conflicts:
        print("\nA lane's declared state must match the host: a RETIRED or NEVER_SCHEDULED row\n"
              "whose timer is enabled or whose cron line is present is a false registry. Flip the\n"
              "row (with state_since and evidence) or retire the job — never leave both.", file=sys.stderr)
        return EXIT_VIOLATION
    if args.fail_on_new and inactive_n8n:
        print("\nAn ACTIVE kind-n8n lane whose workflow is inactive is a false registry: nothing schedules it.\n"
              "Reactivate the workflow, or flip the row to RETIRED/PAUSED with state_since and evidence.",
              file=sys.stderr)
        return EXIT_VIOLATION
    if args.fail_on_new and dispatch_findings:
        print("\nA dispatch block must name a retry_policy that permits its class (config/n8n_retry_policies.json\n"
              "permitted_classes), and while the row is on cron its dispatch.cron must equal the live crontab\n"
              "schedule. Fix the row or the policy; never widen a policy to fit a lane without review.",
              file=sys.stderr)
        return EXIT_VIOLATION
    if args.fail_on_new and (errors or undeclared):
        print("\nA scheduled job must be declared in config/lane_registry.json.\n"
              "Add a row with an output_signal naming the durable artifact that\n"
              "proves it ran — not its exit code, not its log file existing.\n"
              "If it is deliberately off, declare RETIRED or PAUSED with a\n"
              "state_reason and state_since. 'Off' must be a reported state.\n"
              "An UNDECLARED_N8N_WORKFLOW is an active n8n workflow nobody declared: add the\n"
              "lane row (kind n8n, expression = workflow id) or generate it, or deactivate it.",
              file=sys.stderr)
        return EXIT_VIOLATION
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
