"""Feedback linkage, PreferenceCandidate@v1, and CIOWeeklyLearningReview@v1.

Feedback is episodic evidence first. Repeated reason classes can create an
operator-confirmation candidate, but never silently alter policy or behavior.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTHORITY = "READ_ONLY_ADVISORY"
PREFERENCE_SCHEMA = "PreferenceCandidate@v1"
REVIEW_SCHEMA = "CIOWeeklyLearningReview@v1"
FEEDBACK_SCHEMA = "OperatorFeedback@v2"
VALID_INTENTS = frozenset({"AGREE", "DISAGREE", "DEFER", "NEED_DATA", "NO_LONGER_RELEVANT"})
VALID_REASON_CLASSES = frozenset({"VALUATION", "EVIDENCE", "TIMING", "RISK", "TAX", "INCOME", "LIQUIDITY", "OTHER"})
PREFERENCE_INTENTS = frozenset({"DISAGREE", "DEFER"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def read_jsonl(path: str | Path, *, schema: str | None = None) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows = []
    for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and (schema is None or row.get("schema") == schema):
            rows.append(row)
    return rows


def append_linked_feedback(payload: dict[str, Any], *, store_path: str | Path) -> dict[str, Any]:
    intent = str(payload.get("intent") or "").strip().upper()
    reason_class = str(payload.get("reason_class") or "OTHER").strip().upper()
    identity = str(payload.get("operator_identity_class") or "").strip().upper()
    if intent not in VALID_INTENTS:
        raise ValueError("invalid feedback intent")
    if reason_class not in VALID_REASON_CLASSES:
        raise ValueError("invalid reason class")
    if identity not in {"OPERATOR", "OWNER", "PRIMARY_OPERATOR"}:
        raise PermissionError("operator identity required")
    refs = {
        "decision_id": str(payload.get("decision_id") or "").strip() or None,
        "symbol_thesis_id": str(payload.get("symbol_thesis_id") or payload.get("thesis_id") or "").strip() or None,
        "symbol_thesis_version": str(payload.get("symbol_thesis_version") or payload.get("thesis_version") or "").strip() or None,
        "portfolio_thesis_id": str(payload.get("portfolio_thesis_id") or "").strip() or None,
        "portfolio_thesis_version": str(payload.get("portfolio_thesis_version") or "").strip() or None,
        "capital_plan_id": str(payload.get("capital_plan_id") or "").strip() or None,
        "capital_plan_version": str(payload.get("capital_plan_version") or "").strip() or None,
    }
    if not any(refs.values()):
        raise ValueError("at least one decision/thesis/capital-plan reference is required")
    row = {
        "schema": FEEDBACK_SCHEMA,
        "authority": AUTHORITY,
        "feedback_id": str(payload.get("feedback_id") or f"ofb_{uuid.uuid4().hex[:20]}"),
        "timestamp": str(payload.get("timestamp") or _now()),
        "intent": intent,
        "reason_class": reason_class,
        "reason": str(payload.get("reason") or "").strip()[:500] or None,
        "symbol": str(payload.get("symbol") or "").strip().upper() or None,
        **refs,
        "operator_identity_class": identity,
        "source_surface": str(payload.get("source_surface") or "cio_brain").strip().lower()[:64],
        "status": "ACTIVE",
        "behavior_authority": False,
        "policy_update": None,
        "memory_behavior_influence": 0,
        "financial_action": False,
    }
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if any(existing.get("feedback_id") == row["feedback_id"] for existing in read_jsonl(path, schema=FEEDBACK_SCHEMA)):
            raise ValueError("duplicate feedback_id")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return row


def build_preference_candidates(feedback_rows: list[dict[str, Any]], *, minimum_distinct_decisions: int = 3) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in feedback_rows:
        if row.get("status") != "ACTIVE" or str(row.get("intent") or "").upper() not in PREFERENCE_INTENTS:
            continue
        reason = str(row.get("reason_class") or "OTHER").upper()
        if reason not in VALID_REASON_CLASSES or reason == "OTHER":
            continue
        if not row.get("feedback_id") or not row.get("decision_id"):
            continue
        grouped[reason].append(row)
    candidates = []
    for reason, rows in sorted(grouped.items()):
        decision_ids = sorted({str(row["decision_id"]) for row in rows})
        if len(decision_ids) < int(minimum_distinct_decisions):
            continue
        feedback_ids = sorted({str(row["feedback_id"]) for row in rows})
        identity = {"reason_class": reason, "feedback_ids": feedback_ids, "decision_ids": decision_ids}
        candidates.append({
            "schema": PREFERENCE_SCHEMA,
            "authority": AUTHORITY,
            "candidate_id": "pref_" + _hash(identity)[:20],
            "status": "CANDIDATE",
            "reason_class": reason,
            "summary": f"Operator feedback repeatedly cites {reason.lower()} across {len(decision_ids)} distinct decisions.",
            "evidence_feedback_ids": feedback_ids,
            "evidence_decision_ids": decision_ids,
            "evidence_count": len(feedback_ids),
            "distinct_decision_count": len(decision_ids),
            "requires_operator_confirmation": True,
            "confirmed": False,
            "policy_update": None,
            "behavior_influence": 0,
            "financial_action": False,
        })
    return candidates


def build_weekly_learning_review(
    *,
    week_ending: str,
    decision_rows: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
    thesis_deltas: list[dict[str, Any]] | None = None,
    research_receipts: list[dict[str, Any]] | None = None,
    lesson_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    deltas = list(thesis_deltas or [])
    research = list(research_receipts or [])
    lessons = list(lesson_candidates or [])
    evaluated = [row for row in outcome_rows if row.get("status") == "OUTCOME_EVALUATED"]
    supported = [row for row in evaluated if row.get("thesis_result") in {"SUPPORTED", "CATALYST_CONFIRMED"}]
    failed = [row for row in evaluated if row.get("thesis_result") in {"NOT_SUPPORTED", "INVALIDATED"}]
    invalidated = [row for row in evaluated if row.get("thesis_result") == "INVALIDATED"]
    preference_candidates = build_preference_candidates(feedback_rows)
    intent_counts = Counter(str(row.get("intent") or "UNKNOWN").upper() for row in feedback_rows)
    useful_research = [row for row in research if row.get("usefulness") == "HELPED"]
    redundant_research = [row for row in research if row.get("usefulness") in {"REDUNDANT", "NO_NEW_INFO"}]
    research_questions = sorted({
        str(row.get("free_text") or row.get("reason") or "Additional evidence requested")
        for row in feedback_rows if str(row.get("intent") or "").upper() == "NEED_DATA"
    })
    observation_state = "MEASURED" if len(evaluated) >= 5 else "UNMEASURED_OBSERVATION_WINDOW"
    payload = {
        "schema": REVIEW_SCHEMA,
        "authority": AUTHORITY,
        "week_ending": week_ending,
        "generated_at": _now(),
        "observation_window_state": observation_state,
        "what_i_recommended": {
            "decision_count": len(decision_rows),
            "decision_ids": sorted({str(row.get("decision_id")) for row in decision_rows if row.get("decision_id")}),
        },
        "what_changed": {
            "material_delta_count": sum(1 for row in deltas if row.get("classification") not in {None, "NO_NEW_INFO"}),
            "no_new_info_count": sum(1 for row in deltas if row.get("classification") == "NO_NEW_INFO"),
        },
        "what_worked": [{"record_id": row.get("record_id"), "thesis_result": row.get("thesis_result")} for row in supported],
        "what_failed": [{"record_id": row.get("record_id"), "thesis_result": row.get("thesis_result")} for row in failed],
        "theses_invalidated": [row.get("thesis_version") for row in invalidated if row.get("thesis_version")],
        "research_helped": [row.get("research_id") for row in useful_research if row.get("research_id")],
        "research_redundant": [row.get("research_id") for row in redundant_research if row.get("research_id")],
        "operator_feedback_patterns": {
            "intent_counts": dict(sorted(intent_counts.items())),
            "preference_candidates": preference_candidates,
        },
        "matured_outcomes": {
            "count": len(evaluated),
            "benchmarked_count": sum(1 for row in evaluated if row.get("benchmark_relative_return_pct") is not None),
        },
        "lesson_candidates": [row.get("event_id") or row.get("candidate_id") for row in lessons],
        "new_research_questions": research_questions,
        "no_chain_of_thought": True,
        "automatic_policy_promotion": False,
        "memory_behavior_influence": 0,
        "financial_action": False,
    }
    semantic = {key: value for key, value in payload.items() if key != "generated_at"}
    payload["content_hash"] = _hash(semantic)
    payload["version"] = "weekly_learning_" + payload["content_hash"][:16]
    return payload


def load_latest_weekly_review(store_path: str | Path) -> dict[str, Any] | None:
    rows = read_jsonl(store_path)
    for row in reversed(rows):
        if row.get("record_type") == "WEEKLY_LEARNING_REVIEW" and isinstance(row.get("review"), dict):
            return row["review"]
    return None


def reconcile_weekly_learning_review(review: dict[str, Any], *, store_path: str | Path) -> dict[str, Any]:
    if review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("CIOWeeklyLearningReview@v1 required")
    semantic = {key: value for key, value in review.items() if key not in {"generated_at", "content_hash", "version", "published_at"}}
    if review.get("content_hash") != _hash(semantic):
        raise ValueError("weekly review content_hash mismatch")
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        prior = load_latest_weekly_review(path)
        if prior and prior.get("content_hash") == review.get("content_hash"):
            return {"published": False, "reason": "NO_NEW_INFO", "review": prior}
        record = {
            "record_type": "WEEKLY_LEARNING_REVIEW",
            "recorded_at": _now(),
            "review": dict(review, published_at=_now()),
            "authority": AUTHORITY,
        }
        record["record_hash"] = _hash(record)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"published": True, "reason": "NEW_WEEK_OR_MATERIAL_INPUT", "review": record["review"]}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
