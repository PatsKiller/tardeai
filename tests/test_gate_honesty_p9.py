"""P9 — gate honesty. A gate with no store reads NOT_YET_MEASURED, never PASS.

Six gates were hardcoded literals justified by prose comments rather than rows
in a store, and a seventh reported an automated proxy under a gate defined as an
operator rating. `independent_review_coverage` additionally reused the SCORE
count, so it inherited the scorer's coverage for a population with zero reviews.

These tests pin the honest behaviour, including the part that looks like a
regression: the board now shows FEWER passing gates.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cio_gate_measurement_bridge as bridge

# The six that were hardcoded, and the seventh that was an automated proxy.
PREVIOUSLY_HARDCODED = (
    "unsupported_claim_rate",          # was 0.0
    "stale_input_refusal_accuracy",    # was 1.0
    "deadline_budget_adherence",       # was 1.0
    "duplicate_run_rate",              # was 0.0
    "rollback_test_passed",            # was True
    "authority_violations",            # was 0
)
PREVIOUSLY_PROXIED = "operator_usefulness"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A root whose stores mirror the real shapes measured 2026-09-16."""
    cio = tmp_path / "data" / "cio"
    _write(cio / "cio_action_ledger.jsonl", [
        {"event_type": "CIO_ACTION_LEDGER_GENESIS", "payload": {}},
        {"event_type": "CIO_ACTION_CREATED",
         "payload": {"cio_action_id": "pub-001", "status": "OPEN", "domains": ["cash"]}},
        {"event_type": "CIO_ACTION_CREATED",
         "payload": {"cio_action_id": "pub-002", "status": "OPEN", "domains": ["risk"]}},
        # A SUPERSEDED dedup merge is not an artifact.
        {"event_type": "CIO_ACTION_UPDATED",
         "payload": {"cio_action_id": "pub-003", "status": "SUPERSEDED"}},
    ])
    # Reviews that name a DIFFERENT population — the real defect, where 144
    # sentinel rows review guardian/ledger/steph artifacts, not Alex actions.
    _write(cio / "sentinel_reviews.jsonl", [
        {"event_type": "SENTINEL_REVIEW", "reviewer": "sentinel",
         "artifact_id": "df60faeb-f31", "agent": "guardian",
         "status": "PASS", "issues": [], "contradictions": 0},
    ])
    # Scores that DO name Alex actions, with genuine independence.
    _write(cio / "darwin_scorecards.jsonl", [
        {"event_type": "DARWIN_SCORECARD", "scorer": "darwin", "reviewer": "iris",
         "payload": {"action_id": "pub-001", "grade": "B"}},
    ])
    _write(cio / "agent_run_traces.jsonl", [
        {"agent": "alex", "status": "completed",
         "workflow_metrics": {"schema": "workflow_metrics@v1",
                              "step_count": "UNMEASURED",
                              "retry_count": "UNMEASURED"}},
    ])
    return tmp_path


def test_previously_hardcoded_gates_are_now_not_measured(root: Path) -> None:
    gates = bridge._measure_alex(root)["gates"]
    for gate_id in PREVIOUSLY_HARDCODED:
        gate = gates[gate_id]
        assert gate["measured_value"] is None, (
            f"{gate_id} must read NOT_YET_MEASURED, got {gate['measured_value']!r}"
        )
        assert gate["status"] == "NOT_YET_MEASURED"
        assert gate["passing"] is False, f"{gate_id} must not pass while unmeasured"
        # The reason must name what is missing, not argue that it is fine.
        assert gate["note"], f"{gate_id} must say why it is unmeasured"


def test_operator_usefulness_is_not_an_automated_proxy(root: Path) -> None:
    """The gate is an OPERATOR rating; a Darwin grade average is not one."""
    gate = bridge._measure_alex(root)["gates"][PREVIOUSLY_PROXIED]
    assert gate["measured_value"] is None
    assert gate["status"] == "NOT_YET_MEASURED"
    # The proxy is preserved alongside, clearly labelled, rather than discarded.
    assert "darwin_grade_proxy" in gate


def test_at_least_six_gates_report_not_measured(root: Path) -> None:
    """The P9 acceptance check: up from 0 falsely-measured."""
    summary = bridge._measure_alex(root)["summary"]
    assert summary["gates_not_measured"] >= 6, summary


def test_review_coverage_is_not_the_score_count(root: Path) -> None:
    """The reviews name another population, so Alex's review coverage is 0.0.

    The old implementation assigned this gate the Darwin SCORE count and so
    reported the scorer's coverage for a population with no reviews at all.
    """
    gates = bridge._measure_alex(root)["gates"]
    review = gates["independent_review_coverage"]
    score = gates["independent_score_coverage"]
    assert review["measured_value"] == 0.0, review
    assert review["passing"] is False
    # 1 of 2 real actions is scored -> 0.5. The two gates must not be equal.
    assert score["measured_value"] == 0.5, score
    assert review["measured_value"] != score["measured_value"], (
        "review coverage must be measured independently of score coverage"
    )


def test_self_scoring_is_refused(tmp_path: Path) -> None:
    """A producer scoring itself is not an independent score."""
    cio = tmp_path / "data" / "cio"
    _write(cio / "cio_action_ledger.jsonl", [
        {"event_type": "CIO_ACTION_CREATED",
         "payload": {"cio_action_id": "pub-001", "status": "OPEN"}},
    ])
    _write(cio / "darwin_scorecards.jsonl", [
        # scorer == the producer 'alex'
        {"event_type": "DARWIN_SCORECARD", "scorer": "alex", "reviewer": "iris",
         "payload": {"action_id": "pub-001", "grade": "A"}},
    ])
    gate = bridge._measure_alex(tmp_path)["gates"]["independent_score_coverage"]
    assert gate["measured_value"] == 0.0, gate
    assert "self-scored" in gate["evidence"]


def test_scorer_equal_to_reviewer_is_refused(tmp_path: Path) -> None:
    """Reviewer and scorer must be distinct agents, not one agent twice."""
    cio = tmp_path / "data" / "cio"
    _write(cio / "cio_action_ledger.jsonl", [
        {"event_type": "CIO_ACTION_CREATED",
         "payload": {"cio_action_id": "pub-001", "status": "OPEN"}},
    ])
    _write(cio / "darwin_scorecards.jsonl", [
        {"event_type": "DARWIN_SCORECARD", "scorer": "darwin", "reviewer": "darwin",
         "payload": {"action_id": "pub-001", "grade": "A"}},
    ])
    gate = bridge._measure_alex(tmp_path)["gates"]["independent_score_coverage"]
    assert gate["measured_value"] == 0.0
    assert "scorer==reviewer" in gate["evidence"]


def test_contradiction_rate_refuses_an_empty_denominator(root: Path) -> None:
    """No reviewed Alex actions means no computable contradiction rate.

    Dividing contradictions by 'all review rows ever written' is what previously
    produced a 0.0 PASS from a population Alex does not appear in.
    """
    gate = bridge._measure_alex(root)["gates"]["contradiction_rate"]
    assert gate["measured_value"] is None
    assert "denominator" in gate["note"]


def test_measurements_for_evaluate_gates_omits_unmeasured(root: Path) -> None:
    measurements = bridge._measure_alex(root)
    mapping = bridge.measurements_for_evaluate_gates(measurements)
    for gate_id in PREVIOUSLY_HARDCODED + (PREVIOUSLY_PROXIED,):
        assert gate_id not in mapping, f"{gate_id} must not be handed to evaluate_gates"
    assert "independent_review_coverage" in mapping


def test_evaluate_gates_refuses_promotion_on_these_measurements(root: Path) -> None:
    """The bridge now actually feeds evaluate_gates, and it refuses promotion."""
    from scripts.agent_runtime.agents import FLEET, evaluate_gates

    mapping = bridge.measurements_for_evaluate_gates(bridge._measure_alex(root))
    report = evaluate_gates(FLEET["alex"], mapping)
    assert report.promotable is False
    assert report.blockers


def test_promotion_authority_is_unchanged() -> None:
    """P9 must not touch the promotion rails."""
    from scripts.agent_runtime import maturity_observability as obs

    assert obs.PROMOTION_AUTHORITY == "HUMAN_ONLY"
    assert obs.AUTOMATIC_PROMOTION_PERMITTED is False


def test_no_gate_can_pass_while_unmeasured(root: Path) -> None:
    """The invariant behind all of the above."""
    for gate in bridge._measure_alex(root)["gates"].values():
        if gate["measured_value"] is None:
            assert gate["passing"] is False
