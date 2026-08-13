"""Dry canaries for the Phase 5 reverse-factor reliability / calibration gate.

These prove the safety contract of the reverse-learning edge: a reverse factor
must earn its weight with sample size, proxy evidence is never conflated with
realized outcomes, and effective weight can never exceed the configured base.
Pure functions only — no live DB / broker / LLM.
"""
from __future__ import annotations

from scripts.lib.two_way_curation import (
    calibrate_reverse_weights,
    calibrated_reverse_weight,
    evidence_class_for,
    reverse_factor_reliability,
)


# ── reliability ramp ──────────────────────────────────────────────────────────

def test_reliability_ramps_linearly_to_nmin():
    """0 → 0.0, half → 0.5, n_min → 1.0."""
    assert reverse_factor_reliability("thesis_outcome", 0)["reliability"] == 0.0
    assert reverse_factor_reliability("thesis_outcome", 3)["reliability"] == 1.0
    assert reverse_factor_reliability("options_edge", 5)["reliability"] == 1.0
    assert reverse_factor_reliability("hermes_research", 5)["reliability"] == 1.0
    assert reverse_factor_reliability("hermes_research", 2)["reliability"] == 0.4


def test_reliability_never_exceeds_one():
    assert reverse_factor_reliability("thesis_outcome", 100)["reliability"] == 1.0
    assert reverse_factor_reliability("options_edge", 9999)["reliability"] == 1.0


def test_reliability_none_negative_and_invalid_are_zero():
    assert reverse_factor_reliability("thesis_outcome", None)["reliability"] == 0.0
    assert reverse_factor_reliability("thesis_outcome", -3)["reliability"] == 0.0
    assert reverse_factor_reliability("thesis_outcome", "not-an-int")["reliability"] == 0.0


def test_reliability_unknown_factor_defaults_to_nmin_5():
    assert reverse_factor_reliability("mystery_factor", 5)["reliability"] == 1.0
    assert reverse_factor_reliability("mystery_factor", 2)["reliability"] == 0.4


# ── proxy vs realized labeling ────────────────────────────────────────────────

def test_evidence_class_defaults():
    assert evidence_class_for("thesis_outcome") == "realized"
    assert evidence_class_for("options_edge") == "realized"
    assert evidence_class_for("hermes_research") == "proxy"
    assert evidence_class_for("unknown_factor") == "proxy"


def test_evidence_class_override():
    assert evidence_class_for("options_edge", override="proxy") == "proxy"
    assert evidence_class_for("options_edge", override="realized") == "realized"
    assert evidence_class_for("options_edge", override="bogus") == "realized"


def test_label_distinguishes_realized_vs_proxy():
    real = reverse_factor_reliability("options_edge", 5, evidence_class="realized")
    proxy = reverse_factor_reliability("options_edge", 5, evidence_class="proxy")
    assert real["label"] != proxy["label"]
    assert ":realized:" in real["label"] and ":proxy:" in proxy["label"]


# ── calibration (weight never inflated) ───────────────────────────────────────

def test_calibrated_weight_never_inflates():
    for n in (0, 1, 2, 4, 5, 50):
        g = calibrated_reverse_weight(0.02, "options_edge", n)
        assert g["effective_weight"] <= g["base_weight"]


def test_calibrated_weight_full_at_nmin():
    g = calibrated_reverse_weight(0.02, "thesis_outcome", 3)
    assert g["effective_weight"] == 0.02
    assert g["trusted"] is True


def test_calibrated_weight_zero_below_min():
    g = calibrated_reverse_weight(0.01, "options_edge", 0)
    assert g["effective_weight"] == 0.0
    assert g["trusted"] is False


def test_calibrate_reverse_weights_map():
    out = calibrate_reverse_weights(
        {"thesis_outcome": 0.02, "options_edge": 0.01, "hermes_research": 0.02},
        {"thesis_outcome": 3, "options_edge": 2, "hermes_research": 5},
    )
    assert out["all_trusted"] is False
    assert out["calibrated"]["thesis_outcome"] == 0.02
    assert out["calibrated"]["options_edge"] == round(0.01 * 0.4, 6)
    assert out["calibrated"]["hermes_research"] == 0.02


def test_calibrate_missing_sample_size_drops_factor():
    out = calibrate_reverse_weights(
        {"options_edge": 0.01},
        {},
    )
    assert out["calibrated"]["options_edge"] == 0.0
    assert out["gates"]["options_edge"]["trusted"] is False


def test_calibrate_all_trusted_when_every_factor_meets_nmin():
    out = calibrate_reverse_weights(
        {"thesis_outcome": 0.02, "options_edge": 0.01},
        {"thesis_outcome": 3, "options_edge": 5},
    )
    assert out["all_trusted"] is True
