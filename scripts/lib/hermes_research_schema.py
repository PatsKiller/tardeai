"""Hermes research request/result schema helpers (hermes_request@v1 / hermes_result@v1).

READ_ONLY_ADVISORY — lint rejects execution language.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


SCHEMA_REQUEST = "hermes_request@v1"
SCHEMA_RESULT = "hermes_result@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

LOOP_STATES = frozenset({
    "idle", "queued", "running", "started", "completed", "failed", "reused", "superseded", "cancelled",
})
IN_FLIGHT = frozenset({"queued", "running", "started"})
TERMINAL = frozenset({"completed", "failed", "cancelled", "superseded"})

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}

EXEC_LINT = re.compile(
    r"\b(buy now|sell now|place stop|place order|submit order|execute trade|"
    r"force fill|enter long|enter short|market order|limit order)\b",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def lint_execution_language(blob: Any) -> Optional[str]:
    """Return match text if forbidden execution language present, else None."""
    try:
        import json
        text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
    except Exception:
        text = str(blob)
    m = EXEC_LINT.search(text)
    return m.group(0) if m else None


def validate_request(req: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(req, dict):
        return False, "not_a_dict"
    if not str(req.get("plan_id") or "").strip():
        return False, "plan_id_required"
    if not str(req.get("research_id") or "").strip():
        return False, "research_id_required"
    qs = req.get("questions") or []
    if not qs:
        return False, "questions_required"
    auth = str(req.get("authority") or AUTHORITY)
    if auth != AUTHORITY:
        return False, "authority_must_be_read_only_advisory"
    hit = lint_execution_language(req.get("questions"))
    if hit:
        return False, f"execution_language:{hit}"
    return True, "ok"


def validate_result(result: dict[str, Any], request: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, "not_a_dict"
    if not result.get("result_id"):
        return False, "result_id_required"
    if not result.get("research_id"):
        return False, "research_id_required"
    if not (result.get("as_of") or result.get("completed_ts")):
        return False, "as_of_required"
    hit = lint_execution_language(result)
    if hit:
        return False, f"execution_language:{hit}"
    answers = result.get("answers") or []
    findings = result.get("findings") or []
    if not answers and not findings and not result.get("summary"):
        return False, "empty_result"
    # confidence range
    for a in answers:
        if not isinstance(a, dict):
            continue
        c = a.get("confidence")
        if c is not None:
            try:
                cf = float(c)
                if cf <= 0 or cf > 1:
                    return False, "confidence_out_of_range"
            except (TypeError, ValueError):
                return False, "confidence_invalid"
    if request:
        req_ids = {
            str(q.get("question_id") or q.get("id"))
            for q in (request.get("questions") or [])
            if isinstance(q, dict)
        }
        req_ids.discard("None")
        if req_ids:
            for a in answers:
                if not isinstance(a, dict):
                    continue
                qid = str(a.get("question_id") or a.get("id") or "")
                if qid and qid not in req_ids:
                    # soft: allow extra, do not fail
                    pass
    return True, "ok"


def stamp_result(
    request: dict[str, Any],
    body: dict[str, Any],
    *,
    worker_id: str,
    t0_ms: Optional[int] = None,
    result_id: Optional[str] = None,
) -> dict[str, Any]:
    """Stamp identity/status onto backend body → hermes_result@v1."""
    as_of = body.get("as_of") or body.get("completed_ts") or _now()
    result = {
        "schema_version": SCHEMA_RESULT,
        "result_id": result_id or new_id("rr"),
        "research_id": request.get("research_id"),
        "plan_id": request.get("plan_id"),
        "completed_ts": as_of,
        "as_of": as_of,
        "status": "completed",
        "thesis_version_at_request": request.get("thesis_version"),
        "symbol": request.get("symbol") or (request.get("subject") or {}).get("symbol"),
        "fingerprint": request.get("fingerprint"),
        "answers": list(body.get("answers") or [])[:12],
        "findings": list(body.get("findings") or [])[:12],
        "desk_implications": body.get("desk_implications") or {},
        "summary": str(body.get("summary") or "")[:800],
        "limitations": list(body.get("limitations") or [])[:8],
        "authority": AUTHORITY,
        "provenance": {
            **(body.get("provenance") or {}),
            "agent": "hermes",
            "worker_id": worker_id,
            "latency_ms": t0_ms,
            "error": None,
        },
        "catalyst_event_ids": list(request.get("known_catalyst_event_ids") or [])[:40],
    }
    return result


def evidence_domain_from_result(
    result: dict[str, Any],
    *,
    open_research_ids: Optional[list[str]] = None,
    reused: bool = False,
) -> dict[str, Any]:
    """Build hermes_research evidence domain for plan attach."""
    findings = result.get("findings") or []
    # normalize findings to list of strings for summary
    findings_summary: list[str] = []
    for f in findings[:8]:
        if isinstance(f, str):
            findings_summary.append(f[:240])
        elif isinstance(f, dict):
            findings_summary.append(str(f.get("text") or f.get("summary") or f)[:240])
    confs = []
    for a in result.get("answers") or []:
        if isinstance(a, dict) and a.get("confidence") is not None:
            try:
                confs.append(float(a["confidence"]))
            except (TypeError, ValueError):
                pass
    desk = result.get("desk_implications") or {}
    return {
        "domain": "hermes_research",
        "as_of": result.get("as_of") or result.get("completed_ts"),
        "research_id": result.get("research_id"),
        "result_id": result.get("result_id"),
        "status": result.get("status") or "completed",
        "findings_summary": findings_summary,
        "findings": findings[:12],
        "summary": result.get("summary"),
        "answers": result.get("answers") or [],
        "desk_implications": desk,
        "desk_bias": desk.get("suggestion_bias") or desk.get("desk_bias"),
        "confidence_mean": (sum(confs) / len(confs)) if confs else None,
        "open_gaps": list(desk.get("open_gaps") or result.get("limitations") or [])[:6],
        "watch_triggers": list(desk.get("watch_triggers") or [])[:6],
        "reused": bool(reused),
        "quality_state": "OK",
        "fields_used": ["findings_summary", "summary", "answers", "desk_implications"],
        "open_research_ids": list(open_research_ids or []),
        "authority": AUTHORITY,
    }


def evidence_stub_in_flight(
    research_id: str,
    *,
    plan_id: str = "",
    status: str = "queued",
) -> dict[str, Any]:
    return {
        "domain": "hermes_research",
        "as_of": _now()[:19],
        "research_id": research_id,
        "plan_id": plan_id,
        "status": status,
        "quality_state": "PARTIAL",
        "findings_summary": [],
        "open_research_ids": [research_id],
        "gap_reason": f"research_{status}",
        "fields_used": [],
        "authority": AUTHORITY,
    }
