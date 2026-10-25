"""SHADOW admission for the exact §27.1 read commands; no broker runtime imports.

The allowlist retains the audited command, with no synthetic --dry-run flag. The executor
replaces it with an offline plan. Live execution is unavailable in this implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from datetime import datetime, timezone
from typing import Any

try:
    from lib import n8n_broker_read_carveout as carve
except ImportError:
    from scripts.lib import n8n_broker_read_carveout as carve

MARKER = "broker_read_step"
WRAPPER = "scripts/n8n_broker_read_shadow.py"
EMPTY_REASON = "dry_run_requires_broker_read"


def lane_id(step_id: str) -> str:
    return "f09-read-" + step_id.replace("_", "-")


def receipt_path(step_id: str) -> str:
    return "data/runtime/n8n_read_shadow/" + lane_id(step_id) + "_last.json"


def step_for(entry: Mapping[str, Any]):
    return next((s for s in carve.READ_LANES if s.id == entry.get(MARKER)), None)


def handles(entry: Mapping[str, Any]) -> bool:
    """Removing the marker must never fall back to executing the underlying read."""
    scripts = {s.script for s in carve.READ_LANES}
    return MARKER in entry or any(
        isinstance(t, str) and any(t == s or t.endswith("/" + s) for s in scripts) for t in entry.get("command") or []
    )


def entry_problem(entry: Mapping[str, Any]) -> str | None:
    step = step_for(entry)
    if step is None:
        return "unknown_read_step"
    if entry.get("lane_id") != lane_id(step.id):
        return "read_lane_identity"
    # Exact interpreter and canonical apply argv; no shell, wrapper or added dry-run flag.
    if entry.get("command") != ["$PY", step.script, *step.apply_argv]:
        return "read_command_not_exact"
    if entry.get("dry_run_arg") != [] or entry.get("live_arg") is not None:
        return "read_shadow_only"
    if entry.get("env_names") != [] or entry.get("env_allowlist_mode") != "enforce":
        return "read_environment_not_empty"
    if entry.get("market_gate") is not False or entry.get("lock_kind") != "flock":
        return "read_wrapper_shape"
    if entry.get("retry") is not None or entry.get("offpeak_gate") is not None:
        return "read_extra_wrapper"
    if entry.get("output_receipt") is not None:
        return "read_plan_has_no_durable_receipt"
    if entry.get("output_signal") != receipt_path(step.id):
        return "read_control_receipt_path"
    refusals = carve.static_refusals(entry["command"])
    if refusals:
        return "read_admission:" + ",".join(refusals)
    return None


def row_problem(row: Mapping[str, Any], entry: Mapping[str, Any] | None) -> str | None:
    if entry is None:
        return "read_not_allowlisted"
    problem = entry_problem(entry)
    if problem:
        return problem
    if row.get(MARKER) != entry.get(MARKER) or row.get("lane_id") != entry.get("lane_id"):
        return "read_row_identity"
    sched, dispatch = row.get("scheduler"), row.get("dispatch")
    if not isinstance(sched, Mapping) or not isinstance(dispatch, Mapping):
        return "read_missing_schedule"
    if (sched.get("kind"), sched.get("expression"), sched.get("stage")) != ("n8n", "dispatcher", "shadow"):
        return "read_stage_not_shadow"
    if set(sched) - {"kind", "expression", "stage", "cadence", "match", "wave"}:
        return "read_extra_schedule_field"
    if sched.get("match") != f"{WRAPPER} --step {entry[MARKER]} --plan" or sched.get("wave") != "W5":
        return "read_schedule_identity"
    if (
        dispatch.get("mode") != "dry_run"
        or dispatch.get("class") != "pipeline"
        or dispatch.get("retry_policy") != "none"
    ):
        return "read_dispatch_not_shadow"
    if (
        set(dispatch) - {"mode", "cron", "tz", "wave", "class", "priority", "retry_policy"}
        or dispatch.get("wave") != "W5"
        or dispatch.get("tz") != "America/New_York"
        or not isinstance(dispatch.get("cron"), list)
        or not dispatch["cron"]
        or sched.get("cadence") != dispatch["cron"][0]
    ):
        return "read_extra_dispatch_field"
    if row.get("state") != "ACTIVE":
        return "read_state_not_active"
    if row.get("output_signal") != {"kind": "json_key", "path": receipt_path(entry[MARKER]), "key": "finished_at"}:
        return "read_signal_not_control_receipt"
    if any(row.get(k) for k in ("command", "script", "exec_start", "service", "stay_on_cron", "watch")):
        return "read_extra_execution_field"
    return None


def plan_argv(entry: Mapping[str, Any], mode: str) -> list[str] | None:
    if mode != "dry_run" or entry_problem(entry):
        return None
    return ["$PY", WRAPPER, "--step", entry[MARKER], "--plan"]


def receipt_problem(receipt: Mapping[str, Any]) -> str | None:
    """A successful offline plan needs captured output, not just exit zero."""
    step = step_for(receipt)
    if (
        step is None
        or receipt.get("lane_id") != lane_id(step.id)
        or receipt.get("mode") != "dry_run"
        or receipt.get("state") != "RUN_DONE"
    ):
        return "read_plan_receipt_identity"
    if type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0:
        return "read_plan_receipt_exit"
    if not isinstance(receipt.get("run_id"), str) or not receipt["run_id"]:
        return "read_plan_receipt_run_id"
    try:
        lines = str(receipt.get("stdout_tail") or "").splitlines()
        plan = json.loads(lines[1]) if len(lines) == 2 else {}
        outputs = [
            json.loads(s.removeprefix("LANE_OUTPUT "))
            for s in str(receipt.get("stderr_tail") or "").splitlines()
            if s.startswith("LANE_OUTPUT ")
        ]
    except (ValueError, TypeError):
        return "read_plan_evidence_unreadable"
    if not isinstance(plan, dict) or (
        plan.get("schema"),
        plan.get("lane_id"),
        plan.get("step_id"),
        plan.get("stage"),
        plan.get("execution_available"),
    ) != ("N8nBrokerReadShadowPlan@v1", lane_id(step.id), step.id, "shadow", False):
        return "read_plan_evidence_missing"
    if plan.get("command") != ["$PY", step.script, *step.apply_argv]:
        return "read_plan_evidence_command"
    if plan.get("execution_available") is not False:
        return "read_plan_execution_available"
    binding = {
        "run_id": receipt["run_id"],
        "attempt": str(receipt.get("attempt", 1)),
        "code_sha": str(receipt.get("code_sha") or ""),
    }
    if any(plan.get(k) != v for k, v in binding.items()):
        return "read_plan_run_binding"
    if len(outputs) != 1 or not isinstance(outputs[0], dict):
        return "read_plan_output_missing"
    output = outputs[0]
    if any(output.get(k) != v for k, v in binding.items()):
        return "read_plan_output_run_binding"
    if any(
        output.get(k) != v
        for k, v in {
            "schema": "LaneOutput@v1",
            "lane_id": lane_id(step.id),
            "mode": "dry_run",
            "empty_reason": EMPTY_REASON,
            "unit": "read_steps",
            "skipped_reasons": {},
        }.items()
    ):
        return "read_plan_output_mismatch"
    if any(type(output.get(k)) is not int or output[k] != 0 for k in ("produced_count", "attempted_count")):
        return "read_plan_output_counts"
    return None


def final_receipt_problem(receipt: Mapping[str, Any], *, now: datetime | None = None) -> str | None:
    """Only finalized, aware, ordered success clocks may advance control freshness."""
    problem = receipt_problem(receipt)
    if problem:
        return problem
    try:
        started = datetime.fromisoformat(receipt["started_at"])
        finished = datetime.fromisoformat(receipt["finished_at"])
    except (KeyError, TypeError, ValueError):
        return "read_plan_clock_missing"
    if started.utcoffset() is None or finished.utcoffset() is None:
        return "read_plan_clock_naive"
    if started > finished or finished > (now or datetime.now(timezone.utc)):
        return "read_plan_clock_order"
    return None
