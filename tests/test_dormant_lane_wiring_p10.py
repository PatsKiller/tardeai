"""P10 — the built-but-unwired lanes now have a production caller.

Each of these symbols was correct, tested, and reachable from nothing outside
its own tests. `check_dark_contracts.py` catches the schema-literal form of this
defect and explicitly does not catch the transitive form, which is where these
were hiding.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts import run_dormant_lane_consumers as runner
from scripts.lib import research_contradiction_consumer as consumer


def _args(**kw) -> argparse.Namespace:
    base = {"lane": None, "root": None, "state_root": None,
            "resume_run_id": None, "apply": False, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_every_named_lane_is_registered() -> None:
    """The nine lanes P10 names, plus the P6 gate wired 2026-09-17. No silent omission."""
    assert set(runner.LANES) == {
        "critics", "sentinel", "mvl_resume", "close_goal", "commitments",
        "challenges", "contradictions", "data_gap_registry",
        "evidence_refresh_job",
        # 2026-09-17: run_tiered_validation_gate.py, the fourth P6 entrypoint, was
        # the only one of its tranche never armed. Pinned in full by
        # tests/test_tiered_validation_wiring.py.
        "tiered_validation",
    }


def test_critics_lane_reaches_the_panel_at_zero_cost() -> None:
    """CriticPanel/reconcile_critics get their first production caller, tier-0."""
    result = runner.lane_critics(_args())
    assert result["ok"] is True
    assert result["cost_usd"] == 0.0
    assert result["provider_calls"] == 0
    # Two free states are reachable without a provider, and both are correct:
    # BLOCK_DETERMINISTIC when the deterministic kernel refuses release (the
    # short-circuit that happens BEFORE any critic call), and PROVIDER_FAILURE
    # when it allows release but no reflective lane completed. Neither can
    # incur cost, which is the property this lane exists to hold.
    assert result["direct_state"] in {"BLOCK_DETERMINISTIC", "PROVIDER_FAILURE"}
    assert result["panel_state"] in {"BLOCK_DETERMINISTIC", "PROVIDER_FAILURE"}


def test_sentinel_lane_refuses_a_ticket_with_no_identity() -> None:
    """The negative control: a kernel that releases this is inspecting nothing."""
    result = runner.lane_sentinel(_args())
    assert result["ok"] is True
    assert result["refused_release_allowed"] is False
    assert result["negative_control_held"] is True
    assert result["refused_finding_codes"]


def test_mvl_resume_is_reachable_but_not_invoked() -> None:
    """Reachability without a side effect nobody asked for."""
    result = runner.lane_mvl_resume(_args())
    assert result["ok"] is True
    assert result["reachable"] is True
    assert result["resumed"] is None


def test_already_wired_lanes_are_reported_not_rewired() -> None:
    """Two of the nine already run. Claiming to wire them would be false."""
    for lane in ("data_gap_registry", "evidence_refresh_job"):
        result = runner.LANES[lane](_args())
        assert result["ok"] is True
        assert result["wired"] == "ALREADY_WIRED"


def test_contradictions_lane_refuses_apply() -> None:
    """Escalate, never resolve: picking one of two candidate truths destroys one."""
    report = runner.run(_args(lane="contradictions", apply=True))
    result = report["results"][0]
    assert result["applied"] is False
    assert "escalate-never-resolve" in result["apply_refused"]


def test_contradiction_consumer_reads_the_store(tmp_path: Path) -> None:
    """The reader 31,762 candidates never had."""
    store = tmp_path / "data" / "cio" / "research_contradiction_candidates.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"schema": consumer.CANDIDATE_SCHEMA, "candidate_id": "c1",
         "symbol": "ACME", "left_producer": "hermes", "right_producer": "maria",
         "detected_at": "2026-09-15T12:00:00+00:00"},
        {"schema": consumer.CANDIDATE_SCHEMA, "candidate_id": "c2",
         "symbol": "ACME", "left_producer": "hermes", "right_producer": "vega",
         "detected_at": "2026-09-15T13:00:00+00:00"},
        {"schema": "SomethingElse@v1", "candidate_id": "ignored"},
    ]
    store.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    loaded = consumer.load_candidates(root=tmp_path)
    assert len(loaded) == 2, "rows of another schema must not be read as candidates"

    digest = consumer.digest(loaded)
    assert digest["candidates_read"] == 2
    assert digest["subjects_in_conflict"] == 1
    top = digest["top_subjects"][0]
    assert top["subject"] == "ACME"
    assert top["candidate_count"] == 2
    assert set(top["producers"]) == {"hermes", "maria", "vega"}


def test_missing_candidate_store_is_empty_not_fatal(tmp_path: Path) -> None:
    assert consumer.load_candidates(root=tmp_path) == []
    assert consumer.digest([])["subjects_in_conflict"] == 0


def test_an_artifact_producer_cannot_assess_its_own_contradiction() -> None:
    """Independence is delegated to the existing rule, not re-implemented."""
    candidate = {
        "schema": consumer.CANDIDATE_SCHEMA, "candidate_id": "c1",
        "symbol": "ACME", "left_producer": "hermes", "right_producer": "maria",
    }
    with pytest.raises(ValueError, match="self_validation_forbidden"):
        consumer.prepare_assessment(
            candidate, assessor_id="hermes", assessor_provider="hermes",
            assessment="looks fine to me", evidence_refs=["e1"],
        )


def test_an_independent_assessor_is_accepted() -> None:
    candidate = {
        "schema": consumer.CANDIDATE_SCHEMA, "candidate_id": "c1",
        "symbol": "ACME", "left_producer": "hermes", "right_producer": "maria",
    }
    assessment = consumer.prepare_assessment(
        candidate, assessor_id="sentinel", assessor_provider="deterministic",
        assessment="unresolved", evidence_refs=["e1", "e1", "e2"],
    )
    assert assessment["schema"] == consumer.ASSESSMENT_SCHEMA
    assert assessment["self_validated"] is False
    assert assessment["thesis_rewritten"] is False
    assert assessment["evidence_refs"] == ["e1", "e2"], "refs must be de-duplicated"


def test_the_runner_is_advisory_and_scheduled_after_operator_approve() -> None:
    assert runner.AUTHORITY == "READ_ONLY_ADVISORY"
    assert runner.MBI_BEHAVIOR == 0
    assert runner.FINANCIAL_ACTION is False
    # Operator APPROVE full package 2026-09-16 armed the cron; declaration must match.
    assert "INSTALLED" in runner.SCHEDULED_ENTRYPOINT
    assert "PROPOSAL ONLY" not in runner.SCHEDULED_ENTRYPOINT


def test_commitment_sweep_entrypoint_declares_its_installed_schedule() -> None:
    """P10 (2026-09-16) recorded the sweep as PROPOSAL ONLY. On 2026-09-24 the
    operator approved a cron grant and the 18:20 line was installed (agentic-memory
    tranche 1, lane commitment-outcome-sweep). The declaration must say so, and the
    lane row must agree — an installed job that still reads "not installed" is the
    same honesty defect in the other direction."""
    import json
    from pathlib import Path

    from scripts import sweep_commitment_outcomes as sweep

    assert "PROPOSAL ONLY" not in sweep.SCHEDULED_ENTRYPOINT
    assert "cron: 20 18 * * *" in sweep.SCHEDULED_ENTRYPOINT
    assert "commitment-outcome-sweep" in sweep.SCHEDULED_ENTRYPOINT
    reg = json.loads((Path(__file__).resolve().parents[1] / "config" / "lane_registry.json").read_text())
    row = next(l for l in reg["lanes"] if l["lane_id"] == "commitment-outcome-sweep")
    assert row["state"] == "ACTIVE"
    assert row["scheduler"]["kind"] == "cron"
    assert row["scheduler"]["expression"].startswith("20 18 * * *")
    assert "scripts/sweep_commitment_outcomes.py --apply" in row["scheduler"]["match"]
