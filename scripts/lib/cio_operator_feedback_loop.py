"""Explicit operator feedback → AgentEpisode + PreferenceCandidate.

Does not infer stronger policy than stated. MEMORY_BEHAVIOR_INFLUENCE=0.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.agent_episode import append_episode, build_episode
from scripts.lib.memory_consolidator import consolidate
from scripts.lib.preference_candidate import from_feedback
from scripts.lib.semantic_operator_memory import classify_plane

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "OperatorFeedbackIngest@v1"
STORE = "data/cio/preference_candidates.jsonl"
MEMORY_BEHAVIOR_INFLUENCE = 0

FEEDBACK_RE = re.compile(
    r"(?is)\b("
    r"don'?t notify me|"
    r"do not notify me|"
    r"i prefer|"
    r"treat [A-Z]{1,5} as|"
    r"this (?:recommendation )?was useful|"
    r"this wasn'?t relevant|"
    r"this was not relevant|"
    r"ignore previous|"
    r"place order|"
    r"retract|"
    r"correction:|"
    r"never mind|"
    r"i no longer|"
    r"cancel that preference"
    r")\b"
)

INJECTION_RE = re.compile(r"(?is)\b(ignore previous instructions|place order|send 2fa|disable risk)\b")


def looks_like_feedback(text: str) -> bool:
    return bool(FEEDBACK_RE.search(text or ""))


def classify_feedback(text: str) -> str:
    t = (text or "").strip()
    low = t.lower()
    if INJECTION_RE.search(t):
        return "PROMPT_INJECTION"
    if re.search(r"(?is)\b(retract|never mind|i no longer|cancel that preference)\b", t):
        return "RETRACTION"
    if low.startswith("correction:") or re.search(r"(?is)\bactually\b.*\bnot\b", t):
        return "CORRECTION"
    if re.search(r"(?is)\bbut\b|\binstead\b|\bno longer\b", t) and looks_like_feedback(t):
        return "CONTRADICTION"
    if re.search(r"(?is)\b(maybe|not sure|kind of|sort of)\b", t):
        return "AMBIGUOUS"
    if looks_like_feedback(t):
        return "EXPLICIT_PREFERENCE"
    return "AMBIGUOUS"


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _normalize_statement(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:400]


def evolve_preference(
    *,
    statement: str,
    kind: str,
    existing: list[dict[str, Any]],
    episode_id: str,
    subject_guid: str,
) -> dict[str, Any]:
    norm = _normalize_statement(statement)
    same = [c for c in existing if _normalize_statement(c.get("statement") or "") == norm and not c.get("retracted")]
    if kind == "PROMPT_INJECTION":
        return {
            "schema": "PreferenceCandidate@v1",
            "status": "QUARANTINED",
            "statement": statement[:400],
            "policy_effect": False,
            "memory_behavior_influence": 0,
            "hidden_preference": False,
            "authority": AUTHORITY,
        }
    if kind == "AMBIGUOUS":
        cand = from_feedback(
            subject_guid=subject_guid,
            statement=statement,
            supporting_feedback_ids=[episode_id],
        )
        cand["status"] = "AMBIGUOUS"
        cand["confidence"] = "low"
        cand["policy_effect"] = False
        return cand
    if kind == "RETRACTION" and existing:
        last = dict(existing[-1])
        last["retracted"] = True
        last["retracted_by"] = episode_id
        last["policy_effect"] = False
        last["memory_behavior_influence"] = 0
        last["status"] = "RETRACTED"
        return last
    if kind in {"CONTRADICTION", "CORRECTION"} and existing:
        prior = existing[-1]
        cand = from_feedback(
            subject_guid=subject_guid,
            statement=statement,
            supporting_feedback_ids=[episode_id],
            contradictions=[prior.get("preference_candidate_id") or prior.get("statement") or "prior"],
            first_seen=prior.get("first_seen"),
        )
        cand["status"] = kind
        cand["supersedes"] = prior.get("preference_candidate_id")
        cand["policy_effect"] = False
        return cand
    if same:
        cand = dict(same[-1])
        ids = list(cand.get("supporting_feedback_ids") or [])
        if episode_id not in ids:
            ids.append(episode_id)
        cand["supporting_feedback_ids"] = ids
        cand["sample_size"] = len(ids)
        cand["last_seen"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cand["confidence"] = "low" if len(ids) < 3 else ("medium" if len(ids) < 8 else "high")
        cand["status"] = "REPEATED"
        cand["policy_effect"] = False
        cand["memory_behavior_influence"] = 0
        return cand
    cand = from_feedback(
        subject_guid=subject_guid,
        statement=statement,
        supporting_feedback_ids=[episode_id],
    )
    cand["status"] = "NEW"
    return cand


def ingest_operator_feedback(
    text: str,
    *,
    root: Path | str,
    source: str = "telegram",
    subject_guid: str | None = None,
    operator_id: str = "operator:primary",
) -> dict[str, Any]:
    root_path = Path(root)
    kind = classify_feedback(text)
    subject = subject_guid or "operator:primary"
    episode = build_episode(
        kind="feedback",
        subject_guid=subject,
        summary=text[:500],
        refs={"source": source, "operator_id": operator_id, "feedback_kind": kind},
        agent="alex",
    )
    append_episode(root_path, episode)
    store_path = root_path / STORE
    existing = _load_candidates(store_path)
    candidate = evolve_preference(
        statement=text,
        kind=kind,
        existing=existing,
        episode_id=episode["episode_id"],
        subject_guid=subject,
    )
    plane = classify_plane({"kind": "feedback", "text": text})
    consolidator = consolidate(episode)
    _append(store_path, candidate)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
        "policy_effect": False,
        "financial_action": False,
        "inferred_stronger_policy": False,
        "hidden_preference": False,
        "kind": kind,
        "episode": episode,
        "preference_candidate": candidate,
        "plane": plane,
        "consolidator": {
            "admitted": consolidator.get("admitted"),
            "reason": consolidator.get("reason"),
            "memory_behavior_influence": consolidator.get("memory_behavior_influence"),
        },
        "provenance": {
            "operator_input": text[:500],
            "source": source,
            "episode_id": episode["episode_id"],
        },
    }
