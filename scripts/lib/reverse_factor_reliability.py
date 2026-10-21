"""reverse_factor_reliability.py — Phase 5 reverse-factor reliability gate + proxy/realized labeling (pure, no I/O).

Extracted verbatim from lib/two_way_curation.py on 2026-10-21 (PR #1899), which re-exports every name below, so
existing importers are unchanged. Why a module of its own: hermes_watchlist_scorer.py (n8n lane
hermes-watchlist-scorer) needs only these pure functions, and importing two_way_curation pulls db_adapter ->
holdings_guard -> schwab_* into the lane's import closure (broker_module / order_placement;
tests/test_lane_transitive_capabilities_20261015.py). This module imports nothing from the repo.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 — reverse-factor reliability + proxy/realized labeling (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

# A reverse-learning factor must EARN its weight with sample size. Below n_min
# the factor is damped linearly toward zero — never inflated. This is the single
# place that enforces "do not inflate reverse-learning weights before sample
# size/calibration justifies it", and it labels proxy vs realized evidence so
# the intel card never conflates a weak signal with a graded outcome.

EVIDENCE_CLASS = ("realized", "proxy")

# Minimum sample size (n) before a reverse factor is trusted at full weight.
RELIABILITY_N_MIN = {
    "thesis_outcome": 3,   # graded realized trade/paper outcomes
    "options_edge": 5,     # closed options paper outcomes
    "hermes_research": 5,  # graded research rows
}

# Default evidence class per reverse factor. options_edge is realized only when
# sourced from closed outcomes; IV-rank/queue edge is proxy (caller overrides).
FACTOR_EVIDENCE_CLASS = {
    "thesis_outcome": "realized",
    "options_edge": "realized",
    "hermes_research": "proxy",
}

# Single source of truth for the reverse-learning factors the scorer reliability-gates.
# The scorer reads `<factor>_n` from watchlist_items to damp each below its n_min.
REVERSE_FACTORS = ("thesis_outcome", "options_edge", "hermes_research")


def evidence_class_for(factor: str, *, override: Optional[str] = None) -> str:
    """Resolve a reverse factor's evidence class (realized vs proxy).

    Explicit override wins. Unknown factor defaults to 'proxy' (fail-safe: an
    unclassified signal is treated as the weaker evidence class, never realized).
    """
    if override in EVIDENCE_CLASS:
        return override
    return FACTOR_EVIDENCE_CLASS.get(str(factor or "").lower(), "proxy")


def reverse_factor_reliability(factor: str, n: Optional[int], *,
                               evidence_class: Optional[str] = None) -> Dict[str, Any]:
    """Reliability gate for one reverse factor.

    reliability ramps linearly n / n_min, capped at 1.0. n of None/0/negative →
    0.0 (drop the factor — never fabricate a neutral). Returns the factor name,
    sample size, n_min, reliability, evidence_class, trusted (n >= n_min), and a
    distinct label embedding the evidence class.
    """
    f = str(factor or "").lower()
    n_min = RELIABILITY_N_MIN.get(f, 5)
    ec = evidence_class_for(f, override=evidence_class)
    try:
        n_i = int(n) if n is not None else 0
    except (TypeError, ValueError):
        n_i = 0
    n_i = max(0, n_i)
    reliability = min(1.0, n_i / n_min) if n_min > 0 else 0.0
    return {
        "factor": f,
        "n": n_i,
        "n_min": n_min,
        "reliability": round(reliability, 4),
        "evidence_class": ec,
        "trusted": n_i >= n_min,
        "label": f"{f}:{ec}:n={n_i}",
    }


def calibrated_reverse_weight(base_weight: float, factor: str, n: Optional[int], *,
                              evidence_class: Optional[str] = None) -> Dict[str, Any]:
    """Effective reverse-factor weight after the reliability gate.

    effective_weight = base_weight * reliability, so it can never exceed the
    base weight. Returns the full gate dict plus base_weight / effective_weight.
    """
    gate = reverse_factor_reliability(factor, n, evidence_class=evidence_class)
    base = max(0.0, float(base_weight or 0.0))
    effective = round(base * gate["reliability"], 6)
    return {**gate, "base_weight": base, "effective_weight": effective}


def calibrate_reverse_weights(base_weights: Dict[str, float],
                              sample_sizes: Dict[str, Optional[int]], *,
                              evidence_class: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Apply the reliability gate to a map of reverse-factor weights.

    base_weights: {factor: weight}; sample_sizes: {factor: n}. Returns
    {calibrated: {factor: effective_weight}, gates: {factor: gate}, all_trusted}.
    Only factors present in base_weights are calibrated; a factor missing from
    sample_sizes is damped to 0 (it has no evidence of calibration yet).
    """
    calibrated: Dict[str, float] = {}
    gates: Dict[str, Dict[str, Any]] = {}
    for factor, base in (base_weights or {}).items():
        n = (sample_sizes or {}).get(factor)
        ec = None
        if evidence_class and factor in evidence_class:
            ec = evidence_class[factor]
        g = calibrated_reverse_weight(base, factor, n, evidence_class=ec)
        calibrated[factor] = g["effective_weight"]
        gates[factor] = g
    return {
        "calibrated": calibrated,
        "gates": gates,
        "all_trusted": all(g["trusted"] for g in gates.values()) if gates else True,
    }
