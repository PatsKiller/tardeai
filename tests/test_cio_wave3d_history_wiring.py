"""Wave 3D — the gate's fail-closed rule must actually be fed its inputs.

`ResearchNeedDecision@v2` has always contained "prior execution_language ->
skip, fail closed". Nothing exercised it in production: the dry report built
its input from the plan projection alone and never passed `prior_outcome`, so
plans carrying a prior "execution language not allowed in research output"
failure were presented as eligible for a paid first pass.

A guard that exists but is not wired to its inputs is not a guard. These tests
hold the wiring.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_research_gate import decide
from scripts.lib.cio_research_history import (
    gate_inputs_for, history_by_plan, prior_outcome_for,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def root(tmp_path):
    d = tmp_path / "data" / "cio"
    d.mkdir(parents=True)
    rows = [
        {"plan_id": "p_taint", "research_id": "r1", "status": "queued"},
        {"plan_id": "p_taint", "research_id": "r1", "status": "failed",
         "error": "execution language not allowed in research output"},
        {"plan_id": "p_ok", "research_id": "r2", "status": "queued"},
        {"plan_id": "p_ok", "research_id": "r2", "status": "completed"},
        {"plan_id": "p_fail", "research_id": "r3", "status": "failed",
         "error": "provider timeout"},
    ]
    (d / "hermes_research_requests.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path


def test_execution_language_history_is_detected(root):
    h = history_by_plan(root)
    assert h["p_taint"]["execution_language"] is True
    assert prior_outcome_for("p_taint", h) == "execution_language"


def test_completed_history_maps_to_valid(root):
    h = history_by_plan(root)
    assert prior_outcome_for("p_ok", h) == "VALID"


def test_ordinary_failure_is_not_execution_language(root):
    """A provider timeout must not be mistaken for a tainted artifact."""
    h = history_by_plan(root)
    assert h["p_fail"]["execution_language"] is False
    assert prior_outcome_for("p_fail", h) == "FAIL"


def test_execution_language_outranks_a_later_completion(root):
    """Fail closed is a state, not one signal among several."""
    h = history_by_plan(root)
    h["p_taint"]["completed"] = True
    assert prior_outcome_for("p_taint", h) == "execution_language"


def test_unknown_plan_returns_none(root):
    assert prior_outcome_for("p_missing", history_by_plan(root)) is None


def test_the_gate_fails_closed_once_it_is_told(root):
    """The end-to-end point: history -> gate inputs -> skip."""
    h = history_by_plan(root)
    gate_in = {"material": True, "kind": "held_core_thesis", "plan_id": "p_taint"}
    gate_in.update(gate_inputs_for("p_taint", h))
    r = decide(gate_in, now=NOW)
    assert r["decision"] == "skip"
    assert r["reason"] == "execution_language_fail_closed"


def test_without_the_wiring_the_same_plan_looks_eligible(root):
    """Documents the defect this module fixes.

    Identical plan, no history passed: the gate routes it to a paid first pass
    because nothing told it the prior artifact was tainted.
    """
    r = decide({"material": True, "kind": "held_core_thesis",
                "plan_id": "p_taint"}, now=NOW)
    assert r["decision"] == "flash"


def test_gate_inputs_carry_the_research_id(root):
    gi = gate_inputs_for("p_ok", history_by_plan(root))
    assert gi["research_id"] == "r2"
    assert "r2" in gi["prior_artifact_ids"]


def test_history_module_writes_nothing(root):
    import inspect

    from scripts.lib import cio_research_history as mod

    src = inspect.getsource(mod)
    for bad in ("open(", "write_text", "mkdir"):
        # read_text is expected; writing is not
        assert f".{bad}" not in src.replace(".read_text", ""), bad
