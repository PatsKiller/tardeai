"""Overnight D3 — lesson provenance OUTCOME_DERIVED vs RESEARCH_DERIVED.

Wave contract:
  Make the distinction permanent via schema field ``lesson_provenance``.
  Existing corpus without supporting_outcome_ids → RESEARCH_DERIVED (projection).
  outcome_to_lesson path stamps OUTCOME_DERIVED on new writes.
  Do not rewrite historical lesson JSONL in place.

This file is on the hardening CI allowlist. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import json

from scripts.lib.outcome_to_lesson import (
    LESSON_PROVENANCE_FIELD,
    PROVENANCE_OUTCOME_DERIVED,
    PROVENANCE_RESEARCH_DERIVED,
    build_candidates,
    candidates_from_case_summaries,
    project_lesson_provenance,
    with_lesson_provenance,
)


def _obs(outcome_id, symbol="SCHD", rec="TRIM", date="2026-08-26",
         horizon="1_session", change=-1.0):
    return {
        "outcome_id": outcome_id,
        "decision_id": f"dec_{outcome_id}",
        "horizon": horizon,
        "realized_state": {
            "symbol": symbol,
            "recommendation": rec,
            "change_pct": change,
            "decision_price_date": date,
        },
    }


def test_schema_field_name_is_lesson_provenance():
    assert LESSON_PROVENANCE_FIELD == "lesson_provenance"
    assert PROVENANCE_OUTCOME_DERIVED == "OUTCOME_DERIVED"
    assert PROVENANCE_RESEARCH_DERIVED == "RESEARCH_DERIVED"


def test_outcome_to_lesson_stamps_outcome_derived():
    cand = build_candidates([_obs("o1", change=-2.0)])[0]
    assert cand[LESSON_PROVENANCE_FIELD] == PROVENANCE_OUTCOME_DERIVED
    assert cand["supporting_outcome_ids"] == ["o1"]


def test_counterexample_only_outcome_path_still_stamps_outcome_derived():
    """TRIM + rise → only counterexamples; supporting ids empty.

    Projection alone would mislabel; the writer stamp is load-bearing.
    """
    cand = build_candidates([_obs("o1", rec="TRIM", change=+2.0)])[0]
    assert cand["supporting_outcome_ids"] == []
    assert cand["counterexamples"] == ["o1"]
    assert cand[LESSON_PROVENANCE_FIELD] == PROVENANCE_OUTCOME_DERIVED
    assert project_lesson_provenance(cand) == PROVENANCE_OUTCOME_DERIVED


def test_case_summary_path_stamps_research_derived():
    mem = {
        "memory_type": "CASE_SUMMARY",
        "status": "ACTIVE",
        "memory_id": "mem_cs_1",
        "symbols": ["AAPL"],
        "source_refs": ["plan_x", "res_y"],
        "plan_ids": ["plan_x"],
    }
    cands = candidates_from_case_summaries([mem])
    assert len(cands) == 1
    assert cands[0]["supporting_outcome_ids"] == []
    assert cands[0][LESSON_PROVENANCE_FIELD] == PROVENANCE_RESEARCH_DERIVED


def test_legacy_row_without_field_and_without_outcomes_is_research_derived():
    """Pre-D3 advisory/KB corpus: no stamp, no supporting_outcome_ids."""
    legacy = {
        "schema": "LessonCandidate@v2",
        "lesson_id": "legacy1",
        "statement": "from advisory kb",
        "supporting_outcome_ids": [],
        # intentionally no lesson_provenance
    }
    assert LESSON_PROVENANCE_FIELD not in legacy
    assert project_lesson_provenance(legacy) == PROVENANCE_RESEARCH_DERIVED
    projected = with_lesson_provenance(legacy)
    assert projected[LESSON_PROVENANCE_FIELD] == PROVENANCE_RESEARCH_DERIVED
    # Original row untouched — projection only.
    assert LESSON_PROVENANCE_FIELD not in legacy


def test_legacy_row_with_supporting_outcomes_projects_outcome_derived():
    legacy = {
        "lesson_id": "legacy2",
        "supporting_outcome_ids": ["o9"],
    }
    assert project_lesson_provenance(legacy) == PROVENANCE_OUTCOME_DERIVED


def test_explicit_stamp_wins_over_inference():
    """Do not let empty supporting ids override an OUTCOME_DERIVED stamp."""
    stamped = {
        LESSON_PROVENANCE_FIELD: PROVENANCE_OUTCOME_DERIVED,
        "supporting_outcome_ids": [],
    }
    assert project_lesson_provenance(stamped) == PROVENANCE_OUTCOME_DERIVED
    research = {
        LESSON_PROVENANCE_FIELD: PROVENANCE_RESEARCH_DERIVED,
        "supporting_outcome_ids": ["should_not_override"],
    }
    assert project_lesson_provenance(research) == PROVENANCE_RESEARCH_DERIVED


def test_apply_path_does_not_rewrite_existing_jsonl_rows(tmp_path):
    """Historical rows stay byte-identical; only new lesson_ids append."""
    from scripts.lib.cio_institutional_learning import _append, _jsonl

    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    legacy_line = {
        "schema": "LessonCandidate@v2",
        "lesson_id": "already_there",
        "scope": "SCHD",
        "task_class": "TRIM",
        "statement": "pre-d3 research lesson",
        "supporting_outcome_ids": [],
        "status": "PROVISIONAL",
    }
    path = cio / "lesson_candidates.jsonl"
    original = json.dumps(legacy_line, sort_keys=True) + "\n"
    path.write_text(original, encoding="utf-8")

    observations = [_obs("new_o1", change=-1.5)]
    candidates = build_candidates(observations, searched_counterexamples=True)
    assert candidates, "fixture must produce at least one new candidate"
    existing = {str(r.get("lesson_id")) for r in _jsonl(path)}
    written = 0
    for candidate in candidates:
        if str(candidate.get("lesson_id")) in existing:
            continue
        _append(path, candidate)
        written += 1
    assert written >= 1

    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert first == original.rstrip("\n"), "legacy row must not be rewritten in place"
    assert LESSON_PROVENANCE_FIELD not in json.loads(first)
    # New append carries the stamp; legacy projection stays research-derived.
    new_rows = [json.loads(line) for line in text.splitlines()[1:]]
    assert all(r.get(LESSON_PROVENANCE_FIELD) == PROVENANCE_OUTCOME_DERIVED for r in new_rows)
    assert project_lesson_provenance(json.loads(first)) == PROVENANCE_RESEARCH_DERIVED


def test_new_writes_include_provenance_field_on_disk(tmp_path):
    from scripts.lib.cio_institutional_learning import _append, _jsonl
    from scripts.lib.outcome_to_lesson import build_candidates

    path = tmp_path / "lesson_candidates.jsonl"
    cand = build_candidates([_obs("disk1", change=-2.0)])[0]
    _append(path, cand)
    rows = _jsonl(path)
    assert len(rows) == 1
    assert rows[0][LESSON_PROVENANCE_FIELD] == PROVENANCE_OUTCOME_DERIVED
