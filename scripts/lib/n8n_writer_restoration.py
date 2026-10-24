"""Read-only writer ownership and success evidence for the W8 restoration.

No producer imports, subprocesses, database, scheduler, sender, or activation.
Inputs are source documents and captured receipts. Pipeline retirement retires
the old schedule; it does not establish that the absorbed writer stopped.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from scripts.lib.cron_outage_watchdog import instant, iso, schedules
from scripts.lib.cron_schedule import parse

SCHEMA = "N8nWriterRestorationReport@v1"


def validate_catalog(catalog: dict) -> list[str]:
    errors = []
    if catalog.get("schema") != "N8nWriterRestoration@v1":
        errors.append("invalid_schema")
    if catalog.get("activation") != "OPERATOR_ONLY":
        errors.append("activation_must_be_operator_only")
    seen = set()
    for row in catalog.get("writers", []):
        key = row.get("key")
        if not key or key in seen:
            errors.append(f"duplicate_or_missing_key:{key}")
        seen.add(key)
        for name in ("lane_id", "source", "artifact", "label"):
            if not isinstance(row.get(name), str) or not row[name].strip():
                errors.append(f"{key}:missing_{name}")
        for name in ("source", "receipt"):
            value = row.get(name)
            if value and (value.startswith("/") or ".." in value.split("/") or "\\" in value):
                errors.append(f"{key}:unsafe_{name}")
        for expr in row.get("requested_cron", []):
            try:
                parse(expr)
            except (ValueError, TypeError):
                errors.append(f"{key}:invalid_requested_cron")
        if row.get("execution_boundary") and not row.get("blocked_by"):
            errors.append(f"{key}:execution_boundary_requires_handoff")
    if not seen:
        errors.append("no_writers")
    return errors


def health_proposals(catalog: dict) -> dict:
    """Nonoperative owner-review drafts, never inserted in operative contracts.

    Runtime/output limits need measured producer evidence. No old reviewer,
    guessed duration, or inherited REVIEWED status is copied to this scope.
    """
    errors = validate_catalog(catalog)
    if errors:
        raise ValueError("; ".join(errors))
    result = []
    for writer in catalog["writers"]:
        result.append({"schema": "N8nHealthContract@v1", "kind": "lane", "id": writer["lane_id"],
            "workflow_id": "tradeai-dispatcher", "status": "DRAFT", "operative": False,
            "owner": "PENDING_OWNER_REVIEW", "reviewer": None, "reviewed_at": None,
            "purpose": {"text": f"Monitor the {writer['label']} writer and its actual schedule owner; source restoration only.",
                        "source": writer["source"]},
            "connects_to": [{"name": writer["source"], "direction": "calls"},
                            {"name": writer["artifact"], "direction": "write"},
                            {"name": "missed-run watchdog (W4 integration pending)", "direction": "read"}],
            "healthy": [{"check": "receipt_identity_and_output", "text":
                "Exact writer identity, real execution, successful exit, bound timestamp, expected business output and consumer readback. Parent success alone is insufficient."}],
            "degraded": [{"check": "coverage_or_late", "text":
                "Missing success/output evidence is NOT_MEASURED; one elapsed scheduled opportunity without success is visible."}],
            "failed": [{"check": "run_or_output_failed", "text":
                "Run refusal, failure, missing expected output, or two elapsed opportunities without successful-run evidence. Never use log mtime as success."}],
            "baseline": {"basis": "CLASS_DEFAULT_PROVISIONAL", "timeout_s": "NOT_MEASURED",
                "freshness_degraded_after_h": "NOT_MEASURED", "freshness_failed_after_h": "NOT_MEASURED",
                "source": "Pending actual writer measurements and owner SLO review; no numerical runtime limits proposed."},
            "review_by": "2026-11-24", "alerting": {
                "degraded": {"notifier_priority": "P3"}, "failed": {"notifier_priority": "P2"},
                "enforced": False, "routing": "Pending W4 monitor and independent delivery proof; this draft sends nothing."},
            "remediation": {"catalogue_entry": False, "diagnosis_excluded": True,
                "note": "No retries or execution until actual closure, health, allowlist and authority reviews complete."},
            "evidence": {"receipt": writer.get("receipt"), "verify": [
                "Use a captured exact-run receipt and same-attempt output/consumer evidence; skipped/dry/future receipts never prove success."],
                "blockers": writer.get("blocked_by", [])}})
    return {"scope": "W8", "operative": False, "activation_allowed": False,
            "destination_after_normal_claim_handoff": "config/n8n_health_contracts.json pending_changes only",
            "contracts": result}


def pipeline_schedule(parent: dict, step: dict) -> tuple[list[str], str, str | None]:
    """The stage starts the writer, not its historical standalone cron time.

    The manifest runner filters each step by ISO weekday. Restricted DOM/DOW
    combinations need a richer intersection; refuse instead of changing cron OR
    semantics. The current premarket parent has DOM=*, so this is exact.
    """
    expressions, tz, issue = schedules(parent)
    if issue:
        return [], tz, issue
    dow = step.get("dow")
    if dow is None:
        return expressions, tz, None
    if (not isinstance(dow, list) or not dow
            or any(type(day) is not int or day not in range(1, 8) for day in dow)):
        return [], tz, "pipeline_weekday_filter_not_measured"
    result = []
    for expression in expressions:
        fields = expression.split()
        if fields[2] != "*":
            return [], tz, "pipeline_calendar_intersection_not_measured"
        try:
            days = {x % 7 for x in parse(expression)[4]} & {x % 7 for x in dow}
        except (ValueError, TypeError):
            return [], tz, "pipeline_schedule_not_measured"
        if days:
            fields[4] = ",".join(map(str, sorted(days)))
            result.append(" ".join(fields))
    return result, tz, None if result else "pipeline_has_no_matching_weekday"


def receipt_success(receipt: dict, *, lane_id: str, now: datetime) -> dict:
    """An old ok_at survives a failed run; it is history, never current health.

    A matching receipt requires explicit exit zero for a successful attempt.
    Legacy receipts without an exit remain NOT_MEASURED. v2 output acceptance
    is reported separately from execution evidence.
    """
    result = {"last_success_at": None, "attempt_status": "NOT_MEASURED",
              "output_acceptance": "NOT_MEASURED", "reason": "receipt_unavailable"}
    if not receipt:
        return result
    if receipt.get("lane_id") != lane_id:
        return {**result, "reason": "receipt_identity_mismatch"}
    if receipt.get("schema") not in {"LaneRunReceipt@v1", "LaneRunReceipt@v2"}:
        return {**result, "reason": "receipt_schema_not_admitted"}
    if receipt.get("mode") != "live" or receipt.get("dry_run") is True:
        return {**result, "reason": "dry_or_unmeasured_mode_is_not_success"}
    ok_at, finished = instant(receipt.get("ok_at")), instant(receipt.get("finished_at"))
    if finished is None or finished > now:
        return {**result, "reason": "invalid_or_future_finished_at"}
    code = receipt.get("exit_code", receipt.get("exit"))
    if type(code) is not int:
        return {**result, "reason": "exit_code_not_measured"}
    if receipt.get("status") != "ok" or code != 0:
        # A preserved historical ok_at is explicit evidence of an earlier run.
        if ok_at and ok_at <= finished:
            result["last_success_at"] = iso(ok_at)
        return {**result, "attempt_status": "FAILED", "reason": "latest_attempt_failed"}
    if ok_at is None or ok_at != finished:
        return {**result, "reason": "success_timestamp_not_bound_to_attempt"}
    result.update(last_success_at=iso(ok_at), attempt_status="SUCCEEDED", reason=None)
    if receipt.get("schema") == "LaneRunReceipt@v2":
        result["output_summary"] = {key: receipt.get(key) for key in
            ("produced_count", "attempted_count", "empty_reason", "output_evidence")}
    return result


def pipeline_step_success(receipt: dict, binding: dict, *, manifest_sha: str,
                          now: datetime) -> dict:
    """Require the exact captured manifest, complete real run, and exact step.

    Aggregate overall_status=ok does not make a failed/skipped leaf successful.
    Step rc=0 proves execution only, not the content of its business output.
    """
    result = {"last_success_at": None, "attempt_status": "NOT_MEASURED",
              "output_acceptance": "NOT_MEASURED", "reason": "pipeline_receipt_unavailable"}
    if not receipt:
        return result
    if (receipt.get("schema") != "PipelineRun@v1"
            or receipt.get("pipeline") != binding["manifest"].split("/")[-1].removesuffix(".json")
            or receipt.get("stage") != binding["stage"]
            or receipt.get("manifest_sha256") != manifest_sha):
        return {**result, "reason": "pipeline_receipt_binding_mismatch"}
    if (receipt.get("dry_run") is not False or receipt.get("apply_requested") is not True
            or receipt.get("executed_any") is not True or receipt.get("receipt_complete") is not True):
        return {**result, "reason": "pipeline_run_not_complete_business_execution"}
    steps = receipt.get("steps")
    if (not isinstance(steps, list) or type(receipt.get("step_count")) is not int
            or receipt["step_count"] != len(steps)
            or receipt.get("expected_step_count") != len(steps)):
        return {**result, "reason": "pipeline_step_count_mismatch"}
    matches = [x for x in steps if x.get("id") == binding["step_id"]]
    if len(matches) != 1:
        return {**result, "reason": "pipeline_step_missing_or_ambiguous"}
    step = matches[0]
    at, started = instant(step.get("ts")), instant(receipt.get("started_at"))
    if at is None or started is None or not started <= at <= now:
        return {**result, "reason": "pipeline_step_clock_invalid"}
    if (step.get("schema") != "PipelineStepReceipt@v1"
            or step.get("pipeline") != receipt["pipeline"] or step.get("stage") != binding["stage"]
            or step.get("dry_run") is not False):
        return {**result, "reason": "pipeline_step_binding_mismatch"}
    if step.get("status") == "ok" and type(step.get("rc")) is int and step["rc"] == 0:
        return {**result, "last_success_at": iso(at), "attempt_status": "SUCCEEDED", "reason": None}
    return {**result, "attempt_status": "SKIPPED" if str(step.get("status", "")).startswith("skipped") else "FAILED",
            "reason": "pipeline_step_did_not_succeed"}


def audit(catalog: dict, registry: dict, allowlist: dict, contracts: dict,
          manifests: dict, *, now: datetime, receipts: dict | None = None) -> dict:
    """Return writer truth and proposed watchdog inputs; mutate no source input.

    manifests maps a relative path to {document, sha256}; receipts maps an exact
    declared relative receipt path to a captured document. No path is opened here.
    """
    if now.tzinfo is None:
        raise ValueError("an aware observation clock is required")
    now = now.astimezone(timezone.utc)
    errors = validate_catalog(catalog)
    if errors:
        raise ValueError("; ".join(errors))
    lanes = {row["lane_id"]: row for row in registry.get("lanes", [])}
    admitted = {row["lane_id"]: row for row in allowlist.get("lanes", [])}
    reviewed = {row["id"]: row for row in contracts.get("contracts", [])}
    receipts = receipts or {}
    rows, watchdog_lanes, successes = [], [], {}
    for writer in catalog["writers"]:
        lane_id = writer["lane_id"]
        lane = lanes.get(lane_id)
        scheduler_lane = lane
        binding = writer.get("pipeline")
        step, manifest = None, None
        issues = list(writer.get("blocked_by", []))
        execution = receipt_success(receipts.get(writer.get("receipt"), {}),
                                    lane_id=writer.get("receipt_lane_id", lane_id), now=now)
        pipeline_execution = None
        if binding:
            manifest = manifests.get(binding["manifest"], {})
            stage = manifest.get("document", {}).get("stages", {}).get(binding["stage"], {})
            matches = [x for x in stage.get("steps", []) if x.get("id") == binding["step_id"]]
            parent = lanes.get(binding["lane_id"])
            declared = (lane or {}).get("writer_binding")
            declared_matches = not declared or all(declared.get(key) == binding[key]
                for key in ("manifest", "stage", "step_id", "lane_id"))
            if (len(matches) == 1 and parent and lane and declared_matches
                    and lane.get("superseded_by") == parent["lane_id"]):
                step, scheduler_lane = matches[0], parent
                pipeline_receipt = (parent.get("output_signal") or {}).get("path")
                pipeline_execution = pipeline_step_success(receipts.get(pipeline_receipt, {}), binding,
                                                           manifest_sha=manifest.get("sha256", ""), now=now)
            else:
                scheduler_lane = None
                issues.append("pipeline_ownership_binding_not_measured")
        state = lane.get("state") if lane else "NONE"
        effective_state = scheduler_lane.get("state") if scheduler_lane else "NONE"
        expressions, tz, schedule_issue = (pipeline_schedule(scheduler_lane, step) if step
            else schedules(scheduler_lane) if scheduler_lane else ([], "America/New_York", "no_scheduler_lane"))
        contract = reviewed.get(lane_id, {})
        entry = admitted.get(lane_id)
        if not entry:
            issues.append("executor_not_admitted")
        if contract.get("status") != "REVIEWED":
            issues.append("health_contract_not_reviewed")
        if state in {"PAUSED", "NEVER_SCHEDULED", "NONE"}:
            issues.append("operator_activation_required")
        if schedule_issue:
            issues.append(schedule_issue)
        source_drift = state == "RETIRED" and bool(step) and effective_state == "ACTIVE"
        evidence = [item for item in (execution, pipeline_execution) if item and item["last_success_at"]]
        last_success = max((item["last_success_at"] for item in evidence), key=instant, default=None)
        row = {"key": writer["key"], "lane_id": lane_id, "label": writer["label"],
               "source": writer["source"], "artifact": writer["artifact"], "registry_state": state,
               "effective_writer_state": effective_state,
               "schedule_owner": scheduler_lane.get("lane_id") if scheduler_lane else None,
               "registry_writer_binding_status": ("DECLARED" if lane and lane.get("writer_binding") else
                   "INFERRED_SOURCE_ONLY") if binding else "NOT_APPLICABLE",
               "retired_schedule_with_continuing_writer": source_drift,
               "current_cron": expressions, "timezone": tz,
               "requested_cron": writer.get("requested_cron", []),
               "execution": execution, "pipeline_execution": pipeline_execution,
               "last_success_at": last_success,
               "admission_blockers": sorted(set(issues)), "activation_allowed": False,
               "watchdog_status": "OBSERVATION_INPUT_READY" if effective_state == "ACTIVE" and expressions else
                   "INACTIVE" if effective_state in {"RETIRED", "PAUSED", "NEVER_SCHEDULED"} else "NOT_MEASURED"}
        rows.append(row)
        if row["watchdog_status"] == "OBSERVATION_INPUT_READY":
            # Synthetic observation input only. Never write this over the registry
            # or hand it to a dispatcher/executor: it cannot authorize a run.
            monitor = copy.deepcopy(lane)
            monitor.update(state="ACTIVE", scheduler={"kind": "cron", "expression": " + ".join(expressions),
                           "timezone": tz}, writer_observation_only=True)
            monitor.pop("dispatch", None)
            monitor["expected_cadence_hours"] = scheduler_lane.get("expected_cadence_hours") or 24
            watchdog_lanes.append(monitor)
            if last_success:
                successes[lane_id] = [{"at": last_success, "validated_success": True,
                                      "source": "validated_writer_or_bound_pipeline_step_receipt"}]
    return {"schema": SCHEMA, "observed_at": iso(now), "rows": rows,
            "source_drift_lane_ids": [r["lane_id"] for r in rows if r["retired_schedule_with_continuing_writer"]],
            "watchdog_registry": {"lanes": watchdog_lanes, "observation_only": True},
            "watchdog_successes": successes,
            "activation_allowed": False, "status": "SOURCE_ONLY_PENDING_HANDOFF_AND_REVIEW"}
