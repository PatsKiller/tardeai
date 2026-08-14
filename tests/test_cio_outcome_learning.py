"""cio_outcome_learning.py — dry tests for Phase 10 outcome learning.

Verifies the disposition → learning-candidate → reverse-writeback → calibration
loop, pure derivation, the store-backed orchestrator, and the safety invariants
(no forbidden effects, no fabricated learning from a non-signal).
No broker / order / provider / DB calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.cio_learning_candidate import ALLOWED_EFFECTS, FORBIDDEN_EFFECTS  # noqa: E402
from scripts.lib.cio_learning_candidate import CIOLearningCandidateStore  # noqa: E402
from scripts.lib.cio_outcome_store import CIOOutcomeStore  # noqa: E402
from scripts.lib.cio_outcome_learning import (  # noqa: E402
    DEFAULT_REVERSE_BASE_WEIGHTS,
    aggregate_factor_samples,
    build_calibration,
    derive_learning_candidates,
    derive_reverse_writebacks,
    grade_and_learn,
    normalize_disposition,
    outcome_signal,
)


@pytest.fixture
def stores(tmp_path):
    outcome_store = CIOOutcomeStore(store_path=str(tmp_path / "outcomes.jsonl"))
    learning_store = CIOLearningCandidateStore(store_path=str(tmp_path / "learning.jsonl"))
    return outcome_store, learning_store


# ── Disposition normalization ────────────────────────────────────────────────


def test_normalize_disposition_both_vocabularies():
    assert normalize_disposition("ack") == "ACKNOWLEDGED"
    assert normalize_disposition("reject") == "REJECTED"
    assert normalize_disposition("defer") == "DEFERRED"
    assert normalize_disposition("done") == "DONE"
    assert normalize_disposition("ACCEPTED") == "ACCEPTED"
    assert normalize_disposition("CANCELLED") == "CANCELLED"


def test_normalize_disposition_unknown_is_none():
    assert normalize_disposition("") is None
    assert normalize_disposition(None) is None
    assert normalize_disposition("garbage") is None


# ── Outcome signal ───────────────────────────────────────────────────────────


def test_outcome_signal_measured_outcome_is_authoritative():
    assert outcome_signal("REJECTED", "POSITIVE") == "hit"
    assert outcome_signal("ACCEPTED", "NEGATIVE") == "miss"
    assert outcome_signal("DEFERRED", "MIXED") == "neutral"


def test_outcome_signal_disposition_proxy_when_unmeasured():
    assert outcome_signal("ACCEPTED", "UNKNOWN") == "hit"
    assert outcome_signal("DONE", "NOT_MEASURABLE") == "hit"
    assert outcome_signal("REJECTED", "UNKNOWN") == "miss"
    assert outcome_signal("DEFERRED", "UNKNOWN") == "neutral"


def test_outcome_signal_skip_when_no_signal():
    assert outcome_signal("ACKNOWLEDGED", "UNKNOWN") == "skip"
    assert outcome_signal("CANCELLED", "NOT_MEASURABLE") == "skip"


# ── Learning candidate derivation ────────────────────────────────────────────


def test_derive_candidates_negative_mints_calibration():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="REJECTED", outcome_status="NEGATIVE",
        what_was_wrong="Overweighted a lagging sector",
    )
    effects = {c["proposed_effect"] for c in cands}
    assert "confidence_calibration" in effects
    # Every candidate effect is allowed (never forbidden).
    assert effects <= set(ALLOWED_EFFECTS)
    assert not (effects & set(FORBIDDEN_EFFECTS))


def test_derive_candidates_positive_mints_retrieval():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="ACCEPTED", outcome_status="POSITIVE",
        what_was_right="Dividend thesis held",
    )
    effects = {c["proposed_effect"] for c in cands}
    assert "retrieval_weighting" in effects


def test_derive_candidates_unknowns_mints_research_checklist():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="ACKNOWLEDGED", outcome_status="MIXED",
        unknowns="Energy capex trajectory unclear",
    )
    effects = {c["proposed_effect"] for c in cands}
    assert "research_checklist" in effects


def test_derive_candidates_rejected_mints_routing():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="REJECTED", outcome_status="UNKNOWN",
    )
    assert any(c["proposed_effect"] == "routing_proposal" for c in cands)


def test_derive_candidates_deferred_mints_routing_followup():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="DEFERRED", outcome_status="UNKNOWN",
    )
    assert any(c["proposed_effect"] == "routing_proposal" for c in cands)


def test_derive_candidates_no_signal_mints_nothing():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="ACKNOWLEDGED", outcome_status="UNKNOWN",
        result_summary="", what_was_right="", what_was_wrong="", unknowns="",
    )
    assert cands == []


def test_derive_candidates_carry_parent_links():
    cands = derive_learning_candidates(
        cio_action_id="a1", operator_disposition="REJECTED", outcome_status="NEGATIVE",
        what_was_wrong="x", parent_outcome_id="out-1", symbol="SCHD",
    )
    assert cands
    for c in cands:
        assert c["parent_action_id"] == "a1"
        assert c["parent_outcome_id"] == "out-1"
        assert c["evidence"]


# ── Reverse writeback derivation ─────────────────────────────────────────────


def test_reverse_writeback_hit_requires_symbol():
    wbs = derive_reverse_writebacks(
        operator_disposition="ACCEPTED", outcome_status="POSITIVE", symbol="SCHD",
    )
    assert len(wbs) == 1
    wb = wbs[0]
    assert wb["factor"] == "thesis_outcome"
    assert wb["realized_outcome"] == "win"
    assert wb["thesis_win"] is True
    assert wb["n"] == 1
    assert wb["evidence_class"] == "realized"


def test_reverse_writeback_miss_and_neutral():
    miss = derive_reverse_writebacks(
        operator_disposition="REJECTED", outcome_status="NEGATIVE", symbol="CVX",
    )[0]
    assert miss["realized_outcome"] == "loss"
    assert miss["thesis_win"] is False

    neutral = derive_reverse_writebacks(
        operator_disposition="DEFERRED", outcome_status="MIXED", symbol="CVX",
    )[0]
    assert neutral["realized_outcome"] == "scratch"
    assert neutral["thesis_win"] is None


def test_reverse_writeback_no_symbol_skipped():
    # A book-level outcome with no symbol cannot fold onto a per-symbol row.
    wbs = derive_reverse_writebacks(
        operator_disposition="ACCEPTED", outcome_status="POSITIVE", symbol=None,
    )
    assert wbs == []


def test_reverse_writeback_disposition_proxy_is_labeled_proxy():
    # A disposition with no measurement is a proxy signal, not a realized outcome.
    wbs = derive_reverse_writebacks(
        operator_disposition="ACCEPTED", outcome_status="UNKNOWN", symbol="SCHD",
    )
    assert len(wbs) == 1
    assert wbs[0]["factor"] == "thesis_outcome"
    assert wbs[0]["evidence_class"] == "proxy"


def test_reverse_writeback_skip_mints_nothing():
    wbs = derive_reverse_writebacks(
        operator_disposition="ACKNOWLEDGED", outcome_status="UNKNOWN", symbol="SCHD",
    )
    assert wbs == []


def test_reverse_writeback_options_and_research():
    wbs = derive_reverse_writebacks(
        operator_disposition="ACCEPTED", outcome_status="POSITIVE", symbol="SCHD",
        options_edge_score=72.0, hermes_research_score=60.0,
    )
    factors = {wb["factor"] for wb in wbs}
    assert factors == {"thesis_outcome", "options_edge", "hermes_research"}
    opt = next(wb for wb in wbs if wb["factor"] == "options_edge")
    assert opt["evidence_class"] == "realized"
    res = next(wb for wb in wbs if wb["factor"] == "hermes_research")
    assert res["evidence_class"] == "proxy"


# ── Calibration ──────────────────────────────────────────────────────────────


def test_calibration_never_inflates_and_damps_below_n_min():
    samples = aggregate_factor_samples([
        {"factor": "thesis_outcome", "n": 1, "evidence_class": "realized"},
    ])
    cal = build_calibration(sample_sizes={f: a["n"] for f, a in samples.items()})
    assert "thesis_outcome" in cal["calibrated"]
    base = DEFAULT_REVERSE_BASE_WEIGHTS["thesis_outcome"]
    eff = cal["calibrated"]["thesis_outcome"]
    assert eff < base  # n=1 below n_min=3 → damped
    assert cal["gates"]["thesis_outcome"]["trusted"] is False


def test_calibration_full_weight_at_n_min():
    cal = build_calibration(sample_sizes={"thesis_outcome": 3})
    assert cal["gates"]["thesis_outcome"]["trusted"] is True
    assert cal["calibrated"]["thesis_outcome"] == DEFAULT_REVERSE_BASE_WEIGHTS["thesis_outcome"]


def test_calibration_empty_damps_all_to_zero():
    cal = build_calibration(sample_sizes={})
    # No samples → every reverse factor is damped to zero and untrusted.
    assert cal["all_trusted"] is False
    assert cal["calibrated"] == {f: 0.0 for f in DEFAULT_REVERSE_BASE_WEIGHTS}


# ── Orchestrator (store-backed) ──────────────────────────────────────────────


def test_grade_and_learn_closes_loop(stores):
    outcome_store, learning_store = stores
    res = grade_and_learn(
        outcome_store=outcome_store,
        learning_store=learning_store,
        cio_action_id="action-1",
        operator_disposition="REJECTED",
        outcome_status="NEGATIVE",
        result_summary="Lost on a premature energy tilt",
        what_was_wrong="Overweighted energy ahead of a supply glut",
        unknowns="Supply/demand balance timing",
        symbol="XOM",
    )
    assert res["ok"] is True
    assert res["signal"] == "miss"
    assert res["candidate_count"] >= 1
    assert res["writeback_count"] >= 1

    # Outcome is durable and linked.
    assert outcome_store.get_outcomes("action-1")
    # Learning candidates persisted and effect-constrained.
    persisted = learning_store.list_candidates()
    assert len(persisted) == res["candidate_count"]
    assert all(
        e["payload"]["proposed_effect"] in ALLOWED_EFFECTS for e in persisted
    )
    # Calibration reflects the single realized sample (damped below n_min).
    assert "thesis_outcome" in res["calibration"]["calibrated"]


def test_grade_and_learn_no_signal_is_fail_closed(stores):
    outcome_store, learning_store = stores
    res = grade_and_learn(
        outcome_store=outcome_store,
        learning_store=learning_store,
        cio_action_id="action-2",
        operator_disposition="ACKNOWLEDGED",
        outcome_status="UNKNOWN",
    )
    assert res["ok"] is True
    assert res["signal"] == "skip"
    assert res["candidate_count"] == 0
    assert res["writeback_count"] == 0
    assert learning_store.list_candidates() == []
    # No outcome samples → reverse factors are damped to zero (not trusted).
    assert res["calibration"]["all_trusted"] is False
    assert res["calibration"]["calibrated"]["thesis_outcome"] == 0.0


def test_grade_and_learn_unknown_disposition_rejected(stores):
    outcome_store, learning_store = stores
    res = grade_and_learn(
        outcome_store=outcome_store,
        learning_store=learning_store,
        cio_action_id="action-3",
        operator_disposition="INVALID_STATUS",
        outcome_status="POSITIVE",
    )
    assert res["ok"] is False
    assert res["error"] == "unknown_disposition"
    # Nothing persisted.
    assert learning_store.list_candidates() == []
