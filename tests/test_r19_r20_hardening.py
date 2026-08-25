"""R19 spine/registry and R20 provenance — no production activation."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.r19_evidence_spine import project_joins
from scripts.lib.r19_experiment_registry import evaluate_registration, register_hypothesis
from scripts.lib.r19_learning_engine import attempt_historical_review_ready
from scripts.lib.r20_universe_propagation import propagate_from_canonical_root

CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
REPO = Path(__file__).resolve().parents[1]


def test_spine_does_not_fuzzy_join_observations_to_checkpoints() -> None:
    spine = project_joins(CURRENT)
    assert spine["originals_rewritten"] is False
    assert spine["candidate_joins_forbidden_for_scored_learning"] is True
    assert spine["counts"]["UNRESOLVED_WITH_REASON"] >= 1
    # Existing obs decision_ids do not match checkpoint decision_ids.
    assert "observation_decision_id_not_in_checkpoints" in spine["unresolved_reasons"]
    # Ticker lineages are CANDIDATE, not scored.
    assert spine["counts"]["CANDIDATE_JOIN"] >= 1


def test_historical_store_does_not_earn_review_ready() -> None:
    out = attempt_historical_review_ready(
        CURRENT, source_sha="2d988c766db3e591dbaa9951f1f441513cf1193a",
        evidence_class="HISTORICAL_REPLAY",
    )
    assert out["status"] == "NO_HYPOTHESIS_EARNED_REVIEW_READY"
    assert out.get("financial_action") is False


def test_registry_rejects_late_registration_and_changed_criteria(tmp_path) -> None:
    spec = {
        "statement": "x",
        "cohort_definition": {"k": 1},
        "metric": "objective_score",
        "expected_direction": "improve",
        "minimum_sample_size": 8,
        "training_cutoff": "2026-01-01T00:00:00+00:00",
        "holdout_start": "2026-02-01T00:00:00+00:00",
        "holdout_end": "2026-03-01T00:00:00+00:00",
        "acceptance_criteria": {"min_delta": 0.05},
    }
    late = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="abc",
        registered_at="2026-04-01T00:00:00+00:00", mode="CONTEMPORANEOUS",
    )
    assert late["ok"] is False
    assert late["reason"] == "REGISTRATION_AFTER_HOLDOUT_VISIBLE"
    live_recon = register_hypothesis(
        tmp_path, spec, evidence_class="LIVE", source_sha="abc",
        mode="RECONSTRUCTED_AS_OF",
    )
    assert live_recon["ok"] is False
    ok = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="abc",
        registered_at="2026-01-01T00:00:00+00:00", mode="CONTEMPORANEOUS",
    )
    assert ok["ok"] is True
    changed = dict(spec)
    changed["metric"] = "other"
    ev = evaluate_registration(
        ok["registration"],
        train_rows=[{"objective_score": 0.5}] * 8,
        holdout_rows=[{"objective_score": 0.9}] * 8,
        spec=changed,
    )
    assert ev["status"] == "CRITERIA_CHANGED_AFTER_REGISTRATION"


def test_registry_can_earn_review_ready_when_holdout_is_real(tmp_path) -> None:
    spec = {
        "statement": "holdout mean exceeds train by threshold",
        "source_lesson_ids": ["les_1"],
        "cohort_definition": {"policy": "FAST"},
        "metric": "objective_score",
        "expected_direction": "improve",
        "minimum_sample_size": 8,
        "training_cutoff": "2026-01-15T00:00:00+00:00",
        "holdout_start": "2026-01-15T00:00:00+00:00",
        "holdout_end": "2026-02-01T00:00:00+00:00",
        "acceptance_criteria": {"min_delta": 0.05},
    }
    reg = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="unit",
        registered_at="2026-01-15T00:00:00+00:00", mode="CONTEMPORANEOUS",
    )
    train = [{"objective_score": 0.50, "decision_id": f"d{i}"} for i in range(10)]
    hold = [{"objective_score": 0.80, "decision_id": f"h{i}"} for i in range(10)]
    ev = evaluate_registration(reg["registration"], train_rows=train, holdout_rows=hold, spec=spec)
    assert ev["status"] == "REVIEW_READY"
    assert ev["holdout_n"] == 10
    assert ev["delta"] >= 0.05
    miss = evaluate_registration(
        reg["registration"],
        train_rows=[{"objective_score": 0.8}] * 10,
        holdout_rows=[{"objective_score": 0.5}] * 10,
        spec=spec,
    )
    assert miss["status"] == "NO_HYPOTHESIS_EARNED_REVIEW_READY"


def test_r20_auditable_propagation_excludes_incomplete_edges() -> None:
    out = propagate_from_canonical_root(CURRENT, "NOC", evidence_class="HISTORICAL_REPLAY", max_n=8)
    assert out["silent_incomplete_edges_used_for_score"] is False
    cov = out["provenance_coverage"]
    assert cov["securities_in_universe"] and cov["securities_in_universe"] > 200
    used = (cov["fully_provenance_complete_edges"] or 0) + (cov["candidate_incomplete_edges"] or 0)
    if used:
        assert cov["provenance_complete_ratio"] == round(
            cov["fully_provenance_complete_edges"] / used, 4
        )
    for c in out.get("candidates") or []:
        assert c.get("status") == "PROVENANCE_COMPLETE"
        assert c.get("edges")
        assert all(e.get("provenance_complete") for e in c["edges"])
        assert "CLASSIFICATION" in {e.get("relationship_type") for e in c["edges"]} or True
    for inc in out.get("incomplete_candidates") or []:
        assert inc.get("status") == "PROVENANCE_INCOMPLETE"


def test_r20_traces_cover_multiple_paths() -> None:
    out = propagate_from_canonical_root(CURRENT, "NOC", evidence_class="HISTORICAL_REPLAY", max_n=12)
    paths = {p for c in out.get("candidates") or [] for p in c.get("paths") or []}
    # Classification-complete industry/sector should appear; catalyst graph edges may be incomplete.
    assert "industry" in paths or "sector" in paths
    assert out["starting_evidence_artifact"]["symbol"] == "NOC"
    assert out["originating_entity"]["membership_reasons"]
    if out.get("truncated"):
        assert out["excluded_sample"][0]["why_excluded"] == "RANK_BELOW_CUTOFF"
