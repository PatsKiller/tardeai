"""Nightly reflection — propose only.

Consumes production cases and writes candidate lessons / hypotheses /
unresolved contradictions. Never mutates production config or ratifies itself.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_production_case import load_cases, score_case_darwin

AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_reflection_candidates.jsonl"

LESSON_STATES = (
    "CANDIDATE", "RATIFIED", "DISPUTED", "DEPRECATED", "SUPERSEDED", "REJECTED",
)


def reflect(*, cases_path: Optional[Path] = None, out_path: Optional[Path] = None) -> dict[str, Any]:
    cases = load_cases(cases_path)
    proposals: list[dict[str, Any]] = []
    scored = 0
    for c in cases:
        if c.get("status") == "OPEN" and not c.get("darwin"):
            c = dict(c, darwin=score_case_darwin(c))
            scored += 1
        if c.get("operator_disposition") and not c.get("outcome"):
            proposals.append({
                "kind": "unresolved_contradiction",
                "state": "CANDIDATE",
                "text": f"Case {c.get('case_id')} has disposition but no outcome window.",
                "decision_id": c.get("decision_id"),
            })
        if str((c.get("research") or {}).get("decision_use_audit", {}).get("status")) == "UNAVAILABLE":
            proposals.append({
                "kind": "candidate_lesson",
                "state": "CANDIDATE",
                "text": "Retrieval-before-reasoning missing — record MEMORY_NOT_CONSULTED.",
                "decision_id": c.get("decision_id"),
            })
        if c.get("auto_promoted"):
            proposals.append({
                "kind": "unresolved_contradiction",
                "state": "DISPUTED",
                "text": "auto_promoted=true is forbidden; human ratify required.",
                "decision_id": c.get("decision_id"),
            })
    rec = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cases_seen": len(cases),
        "scored": scored,
        "proposals": proposals,
        "mutates_production": False,
        "auto_promotions": 0,
        "authority": AUTHORITY,
    }
    dest = out_path or OUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    with dest.with_suffix(".jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return rec
