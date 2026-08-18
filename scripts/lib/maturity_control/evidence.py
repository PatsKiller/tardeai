"""Evidence drill-down for a lesson or case. Structured lineage only — no CoT."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.maturity_control.lessons import collect_lessons
from scripts.lib.maturity_control.store import resolve_root


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def lesson_evidence(lesson_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    view = collect_lessons(root=base)
    lesson = next((l for l in view["lessons"] if l["lesson_id"] == lesson_id), None)
    refs = list((lesson or {}).get("evidence_refs") or [])
    cases_path = base / "data" / "cio" / "cio_production_cases.jsonl"
    cases = []
    if cases_path.is_file():
        from scripts.lib import cio_production_case as cs
        all_cases = cs.materialize_cases(path=cases_path)
        want = set(refs) | {lesson_id}
        for c in all_cases:
            if c.get("case_id") in want or c.get("decision_id") in want:
                cases.append({
                    "case_id": c.get("case_id"),
                    "decision_id": c.get("decision_id"),
                    "status": c.get("status"),
                    "operator_disposition": c.get("operator_disposition"),
                    "note": c.get("note"),
                    "outcome": c.get("outcome"),
                    "darwin": c.get("darwin"),
                })
    traces = []
    for row in _jsonl(base / "data" / "cio" / "agent_run_traces.jsonl")[-20:]:
        traces.append({
            "trace_id": row.get("trace_id"),
            "agent": row.get("agent"),
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "status": row.get("status"),
        })
    receipts = []
    for row in _jsonl(base / "data" / "cio" / "agent_tool_traces.jsonl")[-20:]:
        if row.get("provider") or row.get("fs_provider") or row.get("shadow_only") is not None:
            receipts.append({
                "provider": row.get("fs_provider") or row.get("provider"),
                "capability": row.get("fs_capability") or row.get("tool_name"),
                "request_id": row.get("request_id"),
                "status": row.get("status"),
                "shadow_only": row.get("shadow_only"),
                "behavior_influence": row.get("behavior_influence"),
                "source_asof": row.get("source_asof"),
                "quality_summary": row.get("quality_summary"),
                "fact_count": row.get("fact_count"),
                "estimate_count": row.get("estimate_count"),
            })
    snap = {}
    sp = base / "data" / "cio" / "cio_reflection_candidates.json"
    if sp.is_file():
        try:
            snap = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snap = {}
    return {
        "authority": "READ_ONLY_ADVISORY",
        "lesson": lesson,
        "originating_cases": cases,
        "reflection": {
            "at": snap.get("at"),
            "cases_seen": snap.get("cases_seen"),
            "scored": snap.get("scored"),
            "auto_promotions": snap.get("auto_promotions"),
            "mutates_production": snap.get("mutates_production"),
        },
        "agent_runs": traces,
        "financial_senses_receipts": receipts,
        "hidden_chain_of_thought": False,
    }
