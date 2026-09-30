"""Read-only CIO Desk observability projection.

This module composes existing CIO projections into one explainable payload for
the v3 CIO page. It never writes state, sends notifications, accesses a broker,
or creates recommendations. Missing evidence fails closed to BLOCKED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SCHEMA = "CIODeskObservability@v1"
AUTHORITY = "READ_ONLY_ADVISORY"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _status(*, available: bool, stale: bool = False, failures: int = 0,
            blocked: bool = False) -> str:
    if blocked or not available:
        return "BLOCKED"
    if stale or failures > 0:
        return "DEGRADED"
    return "WORKING"


def _domain(name: str, status: str, *, value: Any = None, source: str,
            last_success: str | None = None, cadence: str | None = None,
            blocker: str | None = None, owner: str | None = None,
            impact: str | None = None, metrics: dict[str, Any] | None = None,
            drill: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "status": status,
        "value": value,
        "source": source,
        "last_success": last_success,
        "cadence": cadence,
        "blocker": blocker,
        "owner": owner,
        "downstream_impact": impact,
        "metrics": metrics or {},
        "drill_through": drill or [],
    }


def _finding(issue_id: str, severity: str, title: str, root_cause: str,
             status: str, component: str, *, fix: str | None = None,
             evidence: list[str] | None = None, residual_risk: str | None = None,
             external_dependency: str | None = None) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "title": title,
        "root_cause": root_cause,
        "status": status,
        "component": component,
        "fix": fix,
        "validation_evidence": evidence or [],
        "residual_risk": residual_risk,
        "external_dependency": external_dependency,
    }


def build_observability(*, home: dict[str, Any] | None,
                        brain: dict[str, Any] | None,
                        research_ops: dict[str, Any] | None,
                        data_health: dict[str, Any] | None,
                        now: str | None = None) -> dict[str, Any]:
    """Build the CIO-only executive operations payload from existing projections."""
    home = home if isinstance(home, dict) else {}
    brain = brain if isinstance(brain, dict) else {}
    research_ops = research_ops if isinstance(research_ops, dict) else {}
    data_health = data_health if isinstance(data_health, dict) else {}
    as_of = now or _now()
    cio_now = home.get("cio_now") or {}
    policy = brain.get("operator_policy") or {}
    learning = brain.get("learning") or {}
    cockpit = brain.get("learning_cockpit") or {}
    memory = brain.get("memory") or {}
    queue = research_ops.get("queue") or {}
    by_status = queue.get("by_status") or {}
    evidence = home.get("evidence") or {}

    policy_missing = _count(policy.get("required_field_count")) - _count(policy.get("confirmed_field_count"))
    policy_blocked = str(policy.get("status") or "").upper() in {"POLICY_REQUIRED", "BLOCKED"}
    policy_blocker = ", ".join(str(x) for x in (policy.get("missing_fields") or [])[:4]) or None
    research_available = bool(research_ops) and bool(research_ops.get("ok")) and "error" not in queue
    research_failures = _count(queue.get("failed_today"))
    research_stale = _count(queue.get("stale_or_superseded")) > 0
    decisions_available = bool(home) and bool(home.get("ok", True)) and isinstance(cio_now, dict)
    learning_available = bool(brain) and bool(brain.get("ok", True)) and isinstance(cockpit, dict)
    evidence_available = bool(evidence) or (bool(home) and bool(home.get("ok")))
    serving = brain.get("_serving") or {}

    scorecards = [
        _domain(
            "Desk / Telegram",
            _status(available=bool(home) and bool(home.get("ok", True)), stale=False),
            value="CIO projection available" if home and home.get("ok", True) else None,
            source="/api/v3/cio/home",
            last_success=home.get("as_of"), cadence="on request / scheduled projection",
            blocker=None if home and home.get("ok", True) else "CIO home payload unavailable",
            owner="CIO communications",
            impact="Executive status and notification visibility",
            metrics={"notification_gate": (brain.get("proactive_cio") or {}).get("suppression_reason") or "CLEAR"},
            drill=["/v3/cio?tab=notification-gate", "/v3/cio?tab=telegram-receipts"],
        ),
        _domain(
            "Hermes / Research",
            _status(available=research_available, stale=research_stale, failures=research_failures),
            value=queue.get("completed_today"), source="/api/v3/cio/agent-research-ops",
            last_success=research_ops.get("as_of"), cadence="worker queue",
            blocker=(research_ops.get("error") or research_ops.get("dominant_failure_class")),
            owner="Hermes / research queue", impact="Research-backed thesis and decision latency",
            metrics={"queued": _count(queue.get("queued")), "running": _count(by_status.get("running")),
                     "completed": _count(queue.get("completed_today")), "failed": research_failures,
                     "stale_or_superseded": _count(queue.get("stale_or_superseded"))},
            drill=["/v3/cio?tab=universe-theses"],
        ),
        _domain(
            "Shared Spine",
            _status(available=bool(data_health) and bool(data_health.get("ok", True)), failures=_count(len(data_health.get("graph_flags") or []))),
            value="Store graph projected", source="/api/v3/cio/brain/data-health",
            last_success=brain.get("as_of"), cadence="projection request",
            blocker=None if data_health and data_health.get("ok", True) else "Data health projection unavailable",
            owner="Persistence / identity spine", impact="Context retrieval and lineage",
            metrics={"graph_flags": _count(len(data_health.get("graph_flags") or [])),
                     "inventory_available": bool(data_health.get("inventory"))},
            drill=["/v3/cio?tab=evidence"],
        ),
        _domain(
            "Decisions",
            _status(available=decisions_available, stale=_count(cio_now.get("open_plans_count")) > 0),
            value=_count(cio_now.get("decision_count")), source="/api/v3/cio/home",
            last_success=home.get("as_of"), cadence="CIO projection",
            blocker=None if decisions_available else "Decision projection unavailable",
            owner="CIO decision lifecycle", impact="Decision debt and operator action queue",
            metrics={"decisions": _count(cio_now.get("decision_count")),
                     "workflow_actions": _count(cio_now.get("open_actions_count")),
                     "open_plans": _count(cio_now.get("open_plans_count")),
                     "material_today": _count(cio_now.get("material_today_count"))},
            drill=["/v3/cio?tab=cio-now"],
        ),
        _domain(
            "Outcomes / Learning",
            _status(available=learning_available, blocked=not learning_available),
            value=_count(cockpit.get("outcomes_due")), source="/api/v3/cio/brain/learning-cockpit",
            last_success=brain.get("as_of"), cadence="learning projection",
            blocker=None if learning_available else "Learning cockpit unavailable",
            owner="Outcome and learning governance", impact="Feedback, lesson, and memory effectiveness",
            metrics={"outcomes_due": _count(cockpit.get("outcomes_due")),
                     "matured": _count((learning.get("outcomes") or {}).get("matured")),
                     "lessons": _count(cockpit.get("lessons_n")),
                     "memory_influence": brain.get("memory_behavior_influence", 0),
                     "retrieval_receipts": _count(memory.get("retrieval_receipts"))},
            drill=["/v3/cio?tab=cio-brain"],
        ),
        _domain(
            "Platform / Pin",
            _status(available=bool(serving), blocked=bool(serving) and serving.get("pin_match") is False),
            value="PIN MATCH" if serving.get("pin_match") else "PIN UNVERIFIED",
            source="/api/v3/cio/brain", last_success=serving.get("process_started_at"),
            cadence="served process", blocker="served pin mismatch" if serving.get("pin_match") is False else None,
            owner="Release/runtime platform", impact="Trust in the served CIO projection",
            metrics={"loaded_pin_sha": serving.get("loaded_pin_sha"), "current_pin_sha": serving.get("current_pin_sha")},
            drill=["/v3/cio?tab=evidence"],
        ),
    ]

    findings: list[dict[str, Any]] = []
    if policy_blocked:
        findings.append(_finding("CIO-POLICY-001", "HIGH", "Required policy fields unresolved",
                                 "Operator policy projection reports POLICY_REQUIRED",
                                 "ACCEPTED_LIMITATION", "operator policy",
                                 fix="Ratify missing policy fields through the governed policy workflow",
                                 evidence=["/api/v3/cio/brain/policy"],
                                 residual_risk="Capital recommendations remain gated",
                                 external_dependency="Primary operator ratification"))
    if _count(cockpit.get("outcomes_due")) > 0 and _count((learning.get("outcomes") or {}).get("matured")) == 0:
        findings.append(_finding("CIO-LEARNING-001", "HIGH", "Outcomes due but none matured",
                                 "Due outcomes have not reached the maturation stage in the current projection",
                                 "ACCEPTED_LIMITATION", "outcome lifecycle",
                                 fix="Run governed outcome harvesting and maturation; do not promote lessons automatically",
                                 evidence=["/api/v3/cio/brain/learning-cockpit", "/api/v3/cio/brain/learning-review"],
                                 residual_risk="Memory cannot influence decisions until ratified evidence exists"))
    if brain.get("memory_behavior_influence", 0) == 0:
        findings.append(_finding("CIO-MEMORY-001", "MEDIUM", "Memory influence is zero",
                                 "Memory projection is non-authoritative or has no promoted decision influence",
                                 "ACCEPTED_LIMITATION", "memory projection",
                                 fix="Complete evidence-backed lesson ratification and governed promotion",
                                 evidence=["/api/v3/cio/brain"],
                                 residual_risk="Historical context is visible but does not alter CIO decisions"))

    workflows = [
        {"id": "data", "label": "Data Broker", "status": scorecards[2]["status"], "throughput": None},
        {"id": "spine", "label": "Shared Spine", "status": scorecards[2]["status"], "throughput": None},
        {"id": "research", "label": "Research / Hermes", "status": scorecards[1]["status"], "throughput": _count(queue.get("completed_today"))},
        {"id": "decisions", "label": "Decisions", "status": scorecards[3]["status"], "throughput": _count(cio_now.get("decision_count"))},
        {"id": "policy", "label": "Policy Review", "status": "BLOCKED" if policy_blocked else "WORKING", "throughput": _count(policy.get("confirmed_field_count"))},
        {"id": "capital", "label": "Capital Plan", "status": "BLOCKED" if policy_blocked else "WORKING", "throughput": None},
        {"id": "communications", "label": "Communications", "status": scorecards[0]["status"], "throughput": None},
        {"id": "outcomes", "label": "Outcomes", "status": scorecards[4]["status"], "throughput": _count((learning.get("outcomes") or {}).get("matured"))},
        {"id": "memory", "label": "Memory / Learning", "status": scorecards[4]["status"], "throughput": _count(cockpit.get("lessons_n"))},
    ]
    funnel = [
        {"id": "created", "label": "Research Created", "count": _count(queue.get("created_today"))},
        {"id": "completed", "label": "Research Completed", "count": _count(queue.get("completed_today"))},
        {"id": "decisions", "label": "Decision Generated", "count": _count(cio_now.get("decision_count"))},
        {"id": "outcomes", "label": "Outcomes Due", "count": _count(cockpit.get("outcomes_due"))},
        {"id": "matured", "label": "Outcomes Matured", "count": _count((learning.get("outcomes") or {}).get("matured"))},
        {"id": "influence", "label": "Memory Influence", "count": brain.get("memory_behavior_influence", 0)},
    ]
    blocked = sum(1 for row in scorecards if row["status"] == "BLOCKED")
    degraded = sum(1 for row in scorecards if row["status"] == "DEGRADED")
    overall = "BLOCKED" if blocked else ("DEGRADED" if degraded else "WORKING")
    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "as_of": as_of,
        "overall": {"status": overall, "working": len(scorecards) - blocked - degraded,
                     "degraded": degraded, "blocked": blocked,
                     "finding_count": len(findings)},
        "scorecards": scorecards,
        "workflows": workflows,
        "recommendation_funnel": funnel,
        "findings": findings,
        "policy": {"status": policy.get("status"), "missing_fields": policy.get("missing_fields") or [],
                   "missing_count": max(policy_missing, 0), "blocked": policy_blocked},
        "sources": ["/api/v3/cio/home", "/api/v3/cio/brain", "/api/v3/cio/agent-research-ops", "/api/v3/cio/brain/data-health"],
    }
