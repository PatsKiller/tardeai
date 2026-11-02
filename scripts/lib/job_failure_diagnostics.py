"""Safe read-only failure detail from evidence already retained in a run.

No scheduler, process, log or credential is consulted. Missing evidence stays
missing. Symbolic host roles are exposed, never private worker or host IDs.
AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from scripts.lib.error_line_redaction import redact_error_line
from scripts.lib.n8n_dlq_disposition import cause
from scripts.lib.scheduler_operations import redact_command

SCHEMA = "JobFailureDiagnostics@v1"
_ROLES = frozenset({"host_cron", "n8n_executor", "systemd_service", "event_handler", "scheduled_executor"})
_EXCEPTION = re.compile(r"(?m)^([A-Za-z_][\w.]*(?:Error|Exception|Violation|Interrupt|Exit))(?::|$)")
_FAILURES = frozenset({"RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED", "failed", "missed"})


def _safe(value: Any, limit: int = 600) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    # Redact before truncating: cutting a token first can hide its recognisable shape.
    return redact_error_line(redact_command(value.strip()))[:limit]


def _time(value: Any) -> str | None:
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if at.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _duration(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) and value >= 0 else None
    except (OverflowError, ValueError):
        return None


def _receipt(run: Mapping[str, Any]) -> tuple[dict, str | None]:
    raw = run.get("receipt")
    if not isinstance(raw, Mapping):
        raw = run.get("receipt_json")
        if isinstance(raw, str):
            if len(raw) > 128 * 1024:
                return {}, "receipt_payload_exceeds_bound"
            try:
                raw = json.loads(raw)
            except ValueError:
                return {}, "receipt_invalid_json"
    if not isinstance(raw, Mapping):
        raw = run if str(run.get("schema") or "").startswith(("RunReceipt@", "LaneRunReceipt@", "ScheduledJobReceipt@")) else {}
    doc = dict(raw)
    for key in ("run_id", "lane_id"):
        if run.get(key) and doc.get(key) and run[key] != doc[key]:
            return {}, "receipt_identity_mismatch"
    return doc, None if doc else "receipt_not_retained"


def _recommend(kind: str, why: str | None) -> tuple[str, str]:
    if kind == "output_contract":
        if why == "attempt_receipt_missing":
            return "receipt_attempt_missing", "Restore the per-attempt receipt writer and prove run/attempt identity; an older last-success file is insufficient."
        if why == "rule_missing":
            return "output_contract_rule_missing", "Review and register the missing output contract; do not turn enforcement off."
        if why == "counts_inconsistent":
            return "output_contract_count_units", "Align attempted and produced counts to the same unit and validate the real output contract."
        return "output_contract_evidence", "Inspect the recorded contract subreason and repair its producer evidence before a governed rerun."
    messages = {
        "executor_lost": ("executor_ownership_lost", "Inspect recorded executor ownership, heartbeat and child-liveness evidence; unknown outcome is not permission to rerun."),
        "lock_contention": ("execution_lock_contention", "Compare recorded lock ownership and duration with the schedule; never remove an active lock to make monitoring green."),
        "timeout": ("execution_timeout", "Inspect retained timeout diagnostics and expected runtime before changing a timeout or retrying."),
        "process_exception": ("producer_exception", "Review the retained exception and traceback, then validate a narrow repair with synthetic input."),
        "refused": ("execution_admission_refused", "Resolve the recorded admission condition through its owner; do not route around the refusal."),
    }
    return messages.get(kind, ("failure_diagnostic_capture", "Repair capture at the original runner or producer; never invent exception text or an exit status."))


def diagnostics_for_run(
    run: Mapping[str, Any] | None, *, last_success=None, host_role=None, remediation_key=None,
) -> dict[str, Any]:
    """Additive deterministic projection, with no I/O or outcome-changing action.

    Accept a run with receipt/receipt_json, or a standalone receipt. A conflicting
    embedded identity is discarded. host_role accepts only known symbolic roles.
    """
    run = run if isinstance(run, Mapping) else {}
    receipt, gap = _receipt(run)
    gaps = [gap] if gap else []
    state = str(run.get("state") or receipt.get("state") or "")
    reason = str(receipt.get("reason") or run.get("reason") or "")
    synthetic = reason == "executor_lost"
    code = receipt.get("exit_code", receipt.get("exit", run.get("exit_code")))
    code = code if type(code) is int and not synthetic else None
    started = _time(receipt.get("started_at") or run.get("started_at"))
    finished = _time(receipt.get("finished_at") or run.get("finished_at"))
    duration = _duration(receipt.get("duration_s", run.get("duration_s")))
    duration_source = "recorded" if duration is not None else None
    if duration is None and started and finished:
        seconds = (datetime.fromisoformat(finished.replace("Z", "+00:00")) -
                   datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
        if seconds >= 0:
            duration, duration_source = seconds, "execution_timestamps"
    stderr = receipt.get("stderr_tail") if isinstance(receipt.get("stderr_tail"), str) else ""
    stdout = receipt.get("stdout_tail") if isinstance(receipt.get("stdout_tail"), str) else ""
    text, text_source = stderr, "stderr"
    if not text and "Traceback (most recent call last)" in stdout and _EXCEPTION.search(stdout):
        text, text_source = stdout, "stdout_python_traceback"
    matches = list(_EXCEPTION.finditer(text))
    exception = matches[-1].group(1) if matches and not synthetic else None
    at = text.rfind("Traceback (most recent call last)")
    trace = _safe(text[at:], 8192) if at >= 0 and not synthetic else None
    if not stderr:
        gaps.append("stderr_not_retained")
    if not trace:
        gaps.append("traceback_not_retained")
    if code is None:
        gaps.append("exit_code_not_observed" if synthetic else "exit_code_not_retained")
    if duration is None:
        gaps.append("duration_not_retained")
    success = _time(last_success)
    if success is None:
        gaps.append("last_success_not_measured")
    role = host_role if isinstance(host_role, str) and host_role in _ROLES else "unknown"
    if role == "unknown":
        gaps.append("host_role_not_measured")
    host_recorded = bool(run.get("worker_id") or receipt.get("worker_id") or receipt.get("execution_host"))
    if not host_recorded:
        gaps.append("host_identity_not_retained")
    output = receipt.get("output_verdict")
    output = output if isinstance(output, Mapping) else {}
    why = output.get("why") if isinstance(output.get("why"), str) else None
    verdict = output.get("verdict") if isinstance(output.get("verdict"), str) else None
    if synthetic:
        kind = "executor_lost"
    elif receipt.get("lock_skipped") or reason in {"flock_held", "safe_flock_pid_running"}:
        kind = "lock_contention"
    elif reason in {"output_unverifiable", "empty_output"}:
        kind = "output_contract"
    elif state == "RUN_REFUSED":
        kind = "refused"
    elif receipt.get("timed_out") or state == "RUN_TIMEOUT":
        kind = "timeout"
    elif exception:
        kind = "process_exception"
    elif state in _FAILURES or code not in (None, 0):
        kind = "process_exit"
    else:
        kind = "unmeasured"
    key, suggestion = _recommend(kind, why)
    safe_reason = cause(receipt, run.get("reason"))
    if text_source == "stdout_python_traceback" and safe_reason == "Failure recorded; stderr diagnostic was not retained":
        safe_reason = _safe(text, 600)
    lost = receipt.get("lost") if isinstance(receipt.get("lost"), Mapping) else {}
    return {
        "schema": SCHEMA, "failure_kind": kind, "failure_reason": safe_reason, "exception_type": exception,
        "traceback": {"available": bool(trace), "text": trace,
                      "reason": None if trace else "executor_reaper_did_not_observe_child_output" if synthetic else "not_retained",
                      "source": text_source if trace else None},
        "execution": {"exit_code": code, "duration_s": duration, "duration_source": duration_source,
                      "started_at": started, "finished_at": finished, "host_role": role,
                      "host_identity_status": "recorded_privately" if host_recorded else "not_retained"},
        "last_success_at": success,
        "output_contract": {"verdict": _safe(verdict), "reason": _safe(why)},
        "evidence": {"source": "executor_reaper" if synthetic else "run_receipt" if receipt else "run_metadata",
                     "run_id": _safe(str(run.get("run_id") or receipt.get("run_id") or "")),
                     "as_of": finished or _time(run.get("requested_at")), "synthetic": synthetic},
        "executor_loss": {"heartbeat_at": _time(lost.get("heartbeat_at")), "overdue": lost.get("overdue") is True,
                          "pid_recorded": lost.get("pid") is not None} if synthetic else None,
        "remediation": {"key": _safe(remediation_key) or key, "suggestion": suggestion},
        "gaps": sorted(set(gaps)), "authority": "READ_ONLY_ADVISORY",
    }
