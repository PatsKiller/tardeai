"""SHADOW-ONLY MemoryConsolidator schedule.

MEMORY_BEHAVIOR_INFLUENCE=0. Isolated JSONL only. Never production Postgres.
Never mutates operator policy.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.agent_episode import build_episode
from scripts.lib.memory_consolidator import consolidate, lesson_from_outcomes
from scripts.lib.memory_fact import MemoryFactStore

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "MemoryConsolidatorShadowRun@v1"
EPISODE_PATH = "data/cio/agent_episodes.jsonl"
FEEDBACK_PATH = "data/cio/preference_candidates.jsonl"
NOTIFY_PATH = "data/cio/cio_notification_audit.jsonl"
GAP_PATH = "data/cio/research_gaps.jsonl"
DECISION_PATH = "data/cio/cio_decisions.jsonl"
OUTCOME_PATH = "data/cio/advisory_outcomes_v1.jsonl"
SHADOW_OUT = "data/cio/memory_consolidator_shadow.jsonl"
MEMORY_BEHAVIOR_INFLUENCE = 0


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _as_episode(row: dict[str, Any], *, default_kind: str) -> dict[str, Any]:
    if row.get("schema") == "AgentEpisode@v1":
        return row
    kind = str(row.get("kind") or default_kind)
    try:
        return build_episode(
            kind=kind if kind in {
                "operator_question", "cio_recommendation", "research_request",
                "research_completion", "curation_change", "thesis_change", "feedback",
                "NEED_DATA", "notification", "suppression", "portfolio_reassessment",
                "outcome_maturation", "weekly_learning_review",
            } else "notification",
            subject_guid=str(row.get("subject_guid") or row.get("situation_id") or "office:primary"),
            symbol=row.get("symbol"),
            refs={"source_row": row.get("id") or row.get("notification_id") or row.get("decision_id")},
            summary=str(row.get("summary") or row.get("body") or row.get("reason") or default_kind)[:500],
        )
    except RuntimeError:
        return build_episode(
            kind="notification",
            subject_guid="office:primary",
            summary=str(row)[:200],
        )


def run_shadow_consolidator(
    root: Path | str,
    *,
    store: MemoryFactStore | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    store = store or MemoryFactStore()
    sources = {
        "episodes": _read_jsonl(root_path / EPISODE_PATH),
        "feedback": _read_jsonl(root_path / FEEDBACK_PATH),
        "notifications": _read_jsonl(root_path / NOTIFY_PATH),
        "research_gaps": _read_jsonl(root_path / GAP_PATH),
        "cio_decisions": _read_jsonl(root_path / DECISION_PATH),
        "outcomes": _read_jsonl(root_path / OUTCOME_PATH),
    }
    admitted: list[dict[str, Any]] = []
    quarantined = 0
    preferences = 0
    lessons = 0
    for row in sources["episodes"]:
        result = consolidate(row if row.get("schema") == "AgentEpisode@v1" else _as_episode(row, default_kind="notification"), store=store)
        if result.get("admitted"):
            admitted.append(result)
        else:
            quarantined += 1
        if result.get("preference_candidate"):
            preferences += 1
    for row in sources["feedback"]:
        ep = _as_episode({**row, "kind": "feedback", "summary": row.get("statement")}, default_kind="feedback")
        result = consolidate(ep, store=store)
        if result.get("admitted"):
            admitted.append(result)
        if result.get("preference_candidate") or row.get("schema") == "PreferenceCandidate@v1":
            preferences += 1
        if result.get("reason") in {"QUARANTINED", "INJECTION"}:
            quarantined += 1
    for label, rows in (
        ("notifications", sources["notifications"]),
        ("research_gaps", sources["research_gaps"]),
        ("cio_decisions", sources["cio_decisions"]),
    ):
        kind = "notification" if label != "research_gaps" else "NEED_DATA"
        if label == "cio_decisions":
            kind = "cio_recommendation"
        for row in rows:
            result = consolidate(_as_episode(row, default_kind=kind), store=store)
            if result.get("admitted"):
                admitted.append(result)
            elif result.get("reason") in {"QUARANTINED", "INJECTION"}:
                quarantined += 1
    lesson_candidates = []
    outcome_ids = [str(r.get("outcome_id") or r.get("id") or i) for i, r in enumerate(sources["outcomes"])]
    if outcome_ids:
        lesson = lesson_from_outcomes(
            subject_guid="office:primary",
            outcome_ids=outcome_ids,
            statement="shadow lesson from observed outcomes",
        )
        lesson_candidates.append(lesson)
        if lesson.get("mature"):
            lessons += 1
    receipt = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
        "policy_effect": False,
        "financial_action": False,
        "canonical_writer_live": False,
        "production_sql": False,
        "shadow_only": True,
        "ran_at": _now(),
        "consumed": {k: len(v) for k, v in sources.items()},
        "admitted_candidates": len(admitted),
        "preference_candidates": preferences,
        "lesson_candidates": lessons,
        "quarantined": quarantined,
        "lessons": lesson_candidates,
        "outputs": ["MemoryCandidate", "PreferenceCandidate", "LessonCandidate", "QUARANTINED"],
    }
    out_path = root_path / SHADOW_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True, default=str) + "\n")
    receipt["path"] = str(out_path)
    return receipt
