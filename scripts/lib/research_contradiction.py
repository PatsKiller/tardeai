"""Deterministic contradiction-candidate detection across research records."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

SCHEMA = "ResearchContradictionCandidate@v1"
ASSESSMENT_SCHEMA = "ResearchContradictionAssessment@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
POSITIVE = frozenset({"CONFIRMS", "STRENGTHENS"})
NEGATIVE = frozenset({"WEAKENS", "INVALIDATES"})


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _value(record: dict[str, Any], group: str, key: str) -> Any:
    metadata = record.get("metadata") or {}
    bucket = metadata.get(group) or {}
    value = bucket.get(key)
    if group == "factual" and isinstance(value, dict):
        return value.get("value")
    if group == "judgment" and isinstance(value, dict):
        return (value.get("tags") or {}).get(key)
    return value


def _shared_context(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    shared = []
    for group, key in (("factual", "sector"), ("factual", "industry"), ("judgment", "theme"), ("judgment", "catalyst_type")):
        lv, rv = _value(left, group, key), _value(right, group, key)
        if lv and rv and lv == rv:
            shared.append(f"{group}.{key}:{lv}")
    return shared


def _opposes(left: dict[str, Any], right: dict[str, Any]) -> bool:
    lc = str(left.get("classification") or "").upper()
    rc = str(right.get("classification") or "").upper()
    if (lc in POSITIVE and rc in NEGATIVE) or (lc in NEGATIVE and rc in POSITIVE):
        return True
    ls = str(_value(left, "judgment", "stance") or "").upper()
    rs = str(_value(right, "judgment", "stance") or "").upper()
    return {ls, rs} == {"BULLISH", "BEARISH"}


def find_contradiction_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates only; this function never resolves or rewrites artifacts."""
    out = []
    ordered = sorted(records, key=lambda row: str(row.get("delta_id") or row.get("research_id") or ""))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            left_id = str(left.get("delta_id") or left.get("research_id") or "")
            right_id = str(right.get("delta_id") or right.get("research_id") or "")
            if not left_id or not right_id or left_id == right_id:
                continue
            shared = _shared_context(left, right)
            if not shared or not _opposes(left, right):
                continue
            core = {"left": left_id, "right": right_id, "shared": shared}
            out.append({
                "schema": SCHEMA,
                "candidate_id": "contra_" + _digest(core)[:20],
                "status": "CANDIDATE",
                "left_artifact_id": left_id,
                "right_artifact_id": right_id,
                "left_symbol": left.get("symbol"),
                "right_symbol": right.get("symbol"),
                "shared_context": shared,
                "opposition": {
                    "left_classification": left.get("classification"),
                    "right_classification": right.get("classification"),
                },
                "evidence_refs": list(dict.fromkeys(
                    list(left.get("source_refs") or []) + list(right.get("source_refs") or [])
                ))[:40],
                "self_validated": False,
                "thesis_rewritten": False,
                "authority": AUTHORITY,
                "financial_action": False,
            })
    return out


def persist_candidates(records: list[dict[str, Any]], *, path: Path) -> dict[str, Any]:
    """Append new candidates without resolving or rewriting any source artifact."""
    existing: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("candidate_id"):
                existing.add(str(row["candidate_id"]))
    candidates = find_contradiction_candidates(records)
    written = 0
    for candidate in candidates:
        if candidate["candidate_id"] in existing:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(candidate, sort_keys=True, default=str) + "\n")
        existing.add(candidate["candidate_id"])
        written += 1
    return {
        "ok": True,
        "candidates": len(candidates),
        "written": written,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def assess_candidate(
    candidate: dict[str, Any],
    *,
    assessor_id: str,
    assessor_provider: str,
    artifact_producers: list[str],
    assessment: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    """Record independent challenge; an artifact producer cannot assess itself."""
    if candidate.get("schema") != SCHEMA:
        raise ValueError("contradiction_candidate_required")
    if assessor_id in set(artifact_producers) or assessor_provider in set(artifact_producers):
        raise ValueError("self_validation_forbidden")
    return {
        "schema": ASSESSMENT_SCHEMA,
        "candidate_id": candidate.get("candidate_id"),
        "status": "ASSESSED",
        "assessor_id": assessor_id,
        "assessor_provider": assessor_provider,
        "assessment": assessment,
        "evidence_refs": list(dict.fromkeys(evidence_refs))[:40],
        "assessed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "self_validated": False,
        "thesis_rewritten": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
