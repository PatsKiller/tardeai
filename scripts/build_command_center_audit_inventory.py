#!/usr/bin/env python3
"""Keep the Command Center job-coverage inventory honest as the lane registry changes.

The audit capture under ``docs/audits/20261102-command-center-operations/inventory/`` is a
frozen snapshot of every registered job, its coverage and its remediation owner. A static
snapshot cannot stay true: the first lane that is added, retired, re-owned or re-scheduled
makes it wrong and it stays wrong, silently, in a public repository.

This tool is the documented refresh path. It never runs a lane, never reads a broker or a
credential and never invents runtime evidence.

    python3 scripts/build_command_center_audit_inventory.py --check
        Compare the frozen inventory's registry projection with the current
        ``config/lane_registry.json``. Print ``CommandCenterInventoryDrift@v1`` and exit 2
        when a lane was added, removed, re-owned, re-stated or re-scheduled. This makes
        staleness visible instead of silent.

    python3 scripts/build_command_center_audit_inventory.py --write --out <dir>
        Write a refreshed capture into ``<dir>`` (never over the frozen evidence): the
        registry projection is refreshed from the current registry, runtime evidence is
        preserved for lanes that still exist, new lanes are marked unmeasured, lanes absent
        from the registry are marked absent, and a date-stamped ``snapshot`` header names
        the capture time, the registry hash and the command that produced it.

Runtime execution evidence (receipts, attempts, completions) is re-captured by the served
Jobs reader (``scripts/lib/jobs_health.py``); a registry refresh preserves it by design.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "CommandCenterInventoryRefresh@v1"
DRIFT_SCHEMA = "CommandCenterInventoryDrift@v1"
NO_CONSUMER_REASON = (
    "Manually invoked audit-maintenance CLI; its --check report and refreshed capture are "
    "reviewed by the operator. Never scheduled and never imported by the runtime."
)
ROOT = Path(__file__).resolve().parents[1]
FROZEN_DIR = ROOT / "docs/audits/20261102-command-center-operations/inventory"
DEFAULT_REGISTRY = ROOT / "config/lane_registry.json"
REGISTRY_FIELDS = ("owner", "registry_state", "scheduler_kind")
# Cloud at e3c4f7c84: a reschedule (same kind, new cron/cadence/timezone) reported clean because only the kind was
# compared. The schedule fields are compared too; a row that predates them has no measured value and is skipped
# rather than reported as drift it never measured.
SCHEDULE_FIELDS = ("scheduler_expression", "schedule_timezone")
ACTIVE_STATES = {"ACTIVE"}
DISABLED_STATES = {"RETIRED", "NEVER_SCHEDULED", "PAUSED"}
CSV_COLUMNS = (
    "lane_id owner registry_state scheduler_kind schedule_timezone schedule_issue unit "
    "runtime_schedule_presence unit_installed unit_active_state unit_sub_state timer_next_usec "
    "timer_last_usec coverage schedule_applicable schedule_declared_measurable "
    "schedule_observed_timer_clock schedule_evidence_available elapsed_expected_opportunities "
    "execution_attempt_observed durable_completion_observed durable_ledger_completion "
    "durable_wrapper_completion qualifying_success_observed jobs_reader_success_observed "
    "success_signal_discarded_by_jobs_reader output_contract_verdict output_contract_observed "
    "output_contract_satisfied wrapper_component wrapper_component_member_count classification "
    "classification_confidence result due_today next_due_at last_run_at last_success_at "
    "watchdog_status watchdog_as_of receipt_path receipt_signal_kind receipt_signal_key "
    "artifact_exists artifact_inspection latest_run_receipt_schema latest_effective_mode "
    "latest_output_verdict latest_exit_code_present latest_duration_present protected_scope "
    "success_contract root_cause_group remediation_ticket_key existing_pr existing_pr_coverage "
    "reason as_of unit_file_state declared_nonlive_intent live_success_expected "
    "coverage_evidence_mode diagnostic_projection_limit remediation_status"
).split()


def _json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_as_of(inventory: dict) -> str:
    snapshot = inventory.get("snapshot") or {}
    summary = inventory.get("summary") or {}
    return snapshot.get("captured_at") or summary.get("as_of")


def _lane_projection(lane: dict) -> dict:
    scheduler = lane.get("scheduler") or {}
    return {
        "owner": lane.get("owner"),
        "registry_state": lane.get("state"),
        "scheduler_kind": scheduler.get("kind"),
        "scheduler_expression": (scheduler.get("cron") or scheduler.get("cadence")
                                 or scheduler.get("expression") or scheduler.get("schedule")),
        "schedule_timezone": scheduler.get("timezone") or lane.get("timezone"),
    }


def registry_index(registry: dict) -> dict:
    return {lane["lane_id"]: lane for lane in registry.get("lanes") or [] if lane.get("lane_id")}


def drift(inventory: dict, registry: dict, *, registry_path: Path = DEFAULT_REGISTRY) -> dict:
    """Return the registry projection drift between a capture and the live registry."""
    rows = {row["lane_id"]: row for row in inventory.get("rows") or [] if row.get("lane_id")}
    lanes = registry_index(registry)
    added, removed, changed = [], [], []
    for lane_id, lane in lanes.items():
        row = rows.get(lane_id)
        if row is None:
            added.append(
                {"lane_id": lane_id, "registry_state": lane.get("state"), "owner": lane.get("owner")}
            )
            continue
        want = _lane_projection(lane)
        fields = {
            field: [row.get(field), want[field]]
            for field in REGISTRY_FIELDS
            if row.get(field) != want[field]
        }
        for field in SCHEDULE_FIELDS:
            if (field in row and row.get(field) is not None
                    and want.get(field) is not None and row.get(field) != want.get(field)):
                fields[field] = [row.get(field), want.get(field)]
        if fields:
            changed.append({"lane_id": lane_id, "fields": fields})
    for lane_id, row in rows.items():
        if lane_id not in lanes:
            # Cloud at e3c4f7c84: a refreshed capture records the absence in the row itself; re-reporting it every run
            # made a refreshed capture unable to pass --check after any removal.
            if row.get("registry_presence") == "absent":
                continue
            removed.append({"lane_id": lane_id, "registry_state": row.get("registry_state")})
    return {
        "schema": DRIFT_SCHEMA,
        "capture_as_of": _capture_as_of(inventory),
        "checked_at": _now(),
        "registry_sha256": _sha256(registry_path) if registry_path.exists() else None,
        "added": sorted(added, key=lambda item: item["lane_id"]),
        "removed": sorted(removed, key=lambda item: item["lane_id"]),
        "changed": sorted(changed, key=lambda item: item["lane_id"]),
    }


def is_clean(report: dict) -> bool:
    return not (report["added"] or report["removed"] or report["changed"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def _blank_row(lane: dict, *, as_of: str) -> dict:
    projection = _lane_projection(lane)
    state = projection["registry_state"]
    return {
        "lane_id": lane["lane_id"],
        "owner": projection["owner"],
        "registry_state": state,
        "scheduler_kind": projection["scheduler_kind"],
        "schedule_expressions": [],
        "schedule_timezone": (lane.get("scheduler") or {}).get("timezone") or "America/New_York",
        "schedule_issue": None,
        "unit": None,
        "runtime_schedule_presence": None,
        "runtime_cron_expressions": [],
        "unit_installed": None,
        "unit_active_state": None,
        "unit_sub_state": None,
        "timer_next_usec": None,
        "timer_last_usec": None,
        "coverage": "Disabled" if state in DISABLED_STATES else "Unmeasured",
        "schedule_applicable": state in ACTIVE_STATES,
        "schedule_declared_measurable": False,
        "schedule_observed_timer_clock": False,
        "schedule_evidence_available": False,
        "elapsed_expected_opportunities": 0,
        "execution_attempt_observed": False,
        "durable_completion_observed": False,
        "durable_ledger_completion": False,
        "durable_wrapper_completion": False,
        "qualifying_success_observed": False,
        "jobs_reader_success_observed": False,
        "success_signal_discarded_by_jobs_reader": False,
        "output_contract_verdict": None,
        "output_contract_observed": False,
        "output_contract_satisfied": False,
        "diagnostics": {"execution_host_present": None, "remediation_present": None},
        "wrapper_component": None,
        "wrapper_component_member_count": 0,
        "classification": "added after capture; not measured",
        "classification_confidence": "observed",
        "result": "not_measured",
        "due_today": False,
        "next_due_at": None,
        "last_run_at": None,
        "last_success_at": None,
        "watchdog_status": None,
        "watchdog_as_of": None,
        "receipt_path": None,
        "receipt_signal_kind": "none",
        "receipt_signal_key": None,
        "artifact_exists": None,
        "artifact_inspection": "declaration_only",
        "latest_run_receipt_schema": None,
        "latest_effective_mode": None,
        "latest_output_verdict": None,
        "latest_exit_code_present": False,
        "latest_duration_present": False,
        "protected_scope": False,
        "success_contract": None,
        "root_cause_group": None,
        "remediation_ticket_key": None,
        "existing_pr": None,
        "existing_pr_coverage": None,
        "reason": "Lane is in the current registry but was not in the frozen capture",
        "as_of": as_of,
        "unit_file_state": None,
        "declared_nonlive_intent": None,
        "live_success_expected": None,
        "coverage_evidence_mode": "new_since_capture",
        "diagnostic_projection_limit": "not measured; refresh the Jobs reader capture",
        "remediation_status": "unassigned",
        "registry_presence": "present",
    }


def _recount(rows: list[dict], *, as_of: str) -> dict:
    # Codex cloud at 4eb07317f: a retired or removed lane kept its historical coverage and row, so the CURRENT registry
    # statistics contradicted themselves (active_total 492 beside a 493-member coverage_active; 687 lanes in a 686-lane
    # registry). Only rows present in the current registry count towards current figures; a row written by the frozen
    # capture carries no presence field and is present by definition.
    current = [row for row in rows if row.get("registry_presence", "present") == "present"]
    state_counts = Counter(row.get("registry_state") for row in current)
    coverage_all = Counter(row.get("coverage") for row in current)
    active_rows = [row for row in current
                   if row.get("coverage") != "Disabled" and str(row.get("registry_state") or "").upper() == "ACTIVE"]
    coverage_active = Counter(row.get("coverage") for row in active_rows)
    scheduler_all = Counter(row.get("scheduler_kind") for row in rows)
    scheduler_active = Counter(row.get("scheduler_kind") for row in active_rows)
    total = sum(state_counts.values())
    return {
        "as_of": as_of,
        "registry_total": total,
        "registry_state_counts": {key: state_counts.get(key, 0) for key in sorted(state_counts)},
        "active_total": state_counts.get("ACTIVE", 0),
        "coverage_all": {key: coverage_all.get(key, 0) for key in sorted(coverage_all)},
        "coverage_active": {key: coverage_active.get(key, 0) for key in sorted(coverage_active)},
        "coverage_all_percent": {
            key: _percent(coverage_all.get(key, 0), total) for key in sorted(coverage_all)
        },
        "coverage_active_percent": {
            key: _percent(coverage_active.get(key, 0), sum(coverage_active.values()))
            for key in sorted(coverage_active)
        },
        "scheduler_all": {key: scheduler_all.get(key, 0) for key in sorted(scheduler_all)},
        "scheduler_active": {key: scheduler_active.get(key, 0) for key in sorted(scheduler_active)},
    }


def refresh(inventory: dict, registry: dict, *, as_of: str, registry_path: str) -> dict:
    """Return a refreshed capture: current registry projection, preserved runtime evidence."""
    out = copy.deepcopy(inventory)
    rows = {row["lane_id"]: row for row in out.get("rows") or [] if row.get("lane_id")}
    lanes = registry_index(registry)
    for lane_id, lane in lanes.items():
        row = rows.get(lane_id)
        if row is None:
            row = _blank_row(lane, as_of=as_of)
            rows[lane_id] = row
        else:
            row["owner"] = lane.get("owner")
            row["registry_state"] = lane.get("state")
            row["scheduler_kind"] = (lane.get("scheduler") or {}).get("kind")
            upd = _lane_projection(lane)
            row["scheduler_expression"] = upd.get("scheduler_expression")
            row["schedule_timezone"] = upd.get("schedule_timezone")
            row["registry_presence"] = "present"
    for lane_id, row in rows.items():
        if lane_id not in lanes:
            row["registry_presence"] = "absent"
            row["classification"] = "absent from current registry; captured state preserved"
            if row.get("coverage") in (None, ""):
                row["coverage"] = "Unmeasured"
    out["rows"] = [rows[lane_id] for lane_id in sorted(rows)]
    out["summary"] = _recount(out["rows"], as_of=as_of)
    summary = out.setdefault("summary", {})
    for key, value in (inventory.get("summary") or {}).items():
        if key not in summary and key not in {
            "registry_total",
            "registry_state_counts",
            "active_total",
        }:
            summary[key] = value
    out["snapshot"] = {
        "captured_at": as_of,
        "captured_by": Path(__file__).name,
        "refresh_command": f"python3 scripts/{Path(__file__).name} --write --out <dir>",
        "registry_path": registry_path,
        "registry_sha256": hashlib.sha256(
            json.dumps(registry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        # Cloud finding 2: two refreshes relabelled unchanged runtime evidence with the later date. The original
        # stamp is carried forward; this tool never re-measures execution.
        "runtime_evidence_from": ((inventory.get("snapshot") or {}).get("runtime_evidence_from")
                                  or _capture_as_of(inventory)),
        "note": (
            "Registry projection refreshed from the current lane registry. Runtime execution "
            "evidence is preserved from the prior capture; re-measure it with the served Jobs "
            "reader (scripts/lib/jobs_health.py). This tool never runs a lane."
        ),
    }
    return out


def write_capture(inventory: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    target = out_dir / "inventory.json"
    target.write_text(json.dumps(inventory, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(target)
    csv_path = out_dir / "inventory.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in inventory.get("rows") or []:
            writer.writerow({key: _csv_value(row.get(key)) for key in CSV_COLUMNS})
    written.append(csv_path)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(inventory.get("summary") or {}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written.append(summary_path)
    return written


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inventory", type=Path, default=FROZEN_DIR / "inventory.json")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out", type=Path, default=None, help="output directory for --write (never the frozen dir)")
    parser.add_argument("--as-of", default=None, help="capture stamp for --write (default: now, UTC)")
    parser.add_argument("--check", action="store_true", help="report registry drift; exit 2 when stale")
    parser.add_argument("--write", action="store_true", help="write a refreshed capture into --out")
    parser.add_argument("--json", action="store_true", help="print the drift report as JSON")
    args = parser.parse_args(argv)
    if not args.check and not args.write:
        parser.error("choose --check or --write")
    if args.write and args.out is None:
        parser.error("--write requires --out; the frozen evidence directory is never overwritten")
    if args.out is not None and args.out.resolve() == FROZEN_DIR.resolve():
        parser.error("refusing to overwrite the frozen evidence directory; choose a new --out")
    inventory = _json(args.inventory)
    registry = _json(args.registry)
    if args.check:
        report = drift(inventory, registry, registry_path=args.registry)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(
                f"{report['schema']}: capture {report['capture_as_of']} vs registry {args.registry} — "
                f"{len(report['added'])} added, {len(report['removed'])} removed, "
                f"{len(report['changed'])} changed"
            )
            for item in report["added"]:
                print(f"  ADDED   {item['lane_id']} ({item['registry_state']})")
            for item in report["removed"]:
                print(f"  REMOVED {item['lane_id']} ({item['registry_state']})")
            for item in report["changed"]:
                fields = ", ".join(f"{key}: {old!r} -> {new!r}" for key, (old, new) in item["fields"].items())
                print(f"  CHANGED {item['lane_id']} ({fields})")
        return 0 if is_clean(report) else 2
    as_of = args.as_of or _now()
    refreshed = refresh(inventory, registry, as_of=as_of, registry_path=str(args.registry))
    written = write_capture(refreshed, args.out)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
