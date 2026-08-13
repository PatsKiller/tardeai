"""Dry tests for the canonical EvidenceRef@v1 envelope + quality gate."""
from __future__ import annotations

import pytest

from scripts.lib.cio_evidence_ref import (
    FRESHNESS_FRESH,
    FRESHNESS_NOT_TIMESTAMPED,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    QUALITY_STATE_AVAILABLE,
    QUALITY_STATE_DATA_UNAVAILABLE,
    QUALITY_STATE_PARTIAL,
    QUALITY_STATE_STALE,
    EvidenceRef,
    freshness_state_for,
    gate_action,
    make_ref,
    render_chain,
    render_evidence_chain,
    value_hash,
)


# ── value_hash ────────────────────────────────────────────────────────────────


def test_value_hash_is_deterministic_across_key_order():
    a = value_hash({"symbol": "AAPL", "weight": 12.5})
    b = value_hash({"weight": 12.5, "symbol": "AAPL"})
    assert a == b
    assert len(a) == 64


def test_value_hash_differs_for_different_values():
    assert value_hash(1.0) != value_hash(1.01)


# ── freshness_state_for ───────────────────────────────────────────────────────


def test_freshness_fresh_within_threshold():
    s = freshness_state_for("2026-08-13T00:00:00+00:00", "2026-08-13T01:00:00+00:00", 86400)
    assert s == FRESHNESS_FRESH


def test_freshness_stale_beyond_threshold():
    s = freshness_state_for("2026-08-10T00:00:00+00:00", "2026-08-13T00:00:00+00:00", 86400)
    assert s == FRESHNESS_STALE


def test_freshness_not_timestamped():
    assert freshness_state_for("", "2026-08-13T00:00:00+00:00", 86400) == FRESHNESS_NOT_TIMESTAMPED


def test_freshness_unparseable_is_unknown():
    assert freshness_state_for("not-a-date", "2026-08-13T00:00:00+00:00", 86400) == FRESHNESS_UNKNOWN


def test_freshness_future_clock_skew_is_fresh_not_stale():
    s = freshness_state_for("2026-08-14T00:00:00+00:00", "2026-08-13T00:00:00+00:00", 86400)
    assert s == FRESHNESS_FRESH


# ── make_ref / EvidenceRef ────────────────────────────────────────────────────


def test_make_ref_pins_value_hash_and_defaults():
    ref = make_ref("holdings", {"total_value": 100.0}, source="holdings.json")
    assert ref.domain == "holdings"
    assert ref.value_hash == value_hash({"total_value": 100.0})
    assert ref.observed_at
    assert ref.ref_id.startswith("ref_")
    assert ref.scope == "none"


def test_make_ref_symbol_scope_inferred():
    ref = make_ref("technicals", {"rsi": 55.0}, symbol="AAPL")
    assert ref.scope == "symbol"
    assert ref.symbol == "AAPL"


def test_evidence_ref_rejects_invalid_quality_state():
    with pytest.raises(ValueError):
        EvidenceRef(domain="x", quality_state="BOGUS")


def test_evidence_ref_rejects_invalid_scope():
    with pytest.raises(ValueError):
        EvidenceRef(domain="x", scope="bogus")


def test_to_dict_roundtrip_omits_none_value():
    ref = make_ref("risk", {"heat": 10.0})
    d = ref.to_dict()
    assert "value" in d
    assert d["value_hash"]


# ── blocking / stale helpers ──────────────────────────────────────────────────


def test_is_blocking_quality_states():
    assert make_ref("x", 1, quality_state=QUALITY_STATE_DATA_UNAVAILABLE).is_blocking
    assert make_ref("x", 1, quality_state=QUALITY_STATE_PARTIAL).is_blocking is False
    assert make_ref("x", 1, quality_state=QUALITY_STATE_AVAILABLE).is_blocking is False


def test_is_stale_flags_both_kinds():
    stale_quality = make_ref("x", 1, quality_state=QUALITY_STATE_STALE)
    assert stale_quality.is_stale
    fresh_quality = make_ref(
        "x", 1,
        source_timestamp="2026-08-10T00:00:00+00:00",
        observed_at="2026-08-13T00:00:00+00:00",
        freshness_state=FRESHNESS_STALE,
    )
    assert fresh_quality.is_stale


# ── render chain ──────────────────────────────────────────────────────────────


def test_render_chain_carries_fact_source_age_quality():
    ref = make_ref(
        "portfolio", {"total_value": 100.0},
        source="data/portfolios/state/holdings.json",
        source_timestamp="2026-08-13T00:00:00+00:00",
        observed_at="2026-08-13T01:00:00+00:00",
        freshness_state=FRESHNESS_FRESH,
    )
    chain = render_chain(ref, specialist="Maria", cio="Alex")
    assert "FACT:" in chain
    assert "holdings.json" in chain
    assert "AGE:" in chain
    assert "QUALITY: AVAILABLE" in chain
    assert "SPECIALIST: Maria" in chain
    assert "CIO: Alex" in chain


def test_render_evidence_chain_returns_one_line_per_ref():
    refs = [make_ref("a", 1), make_ref("b", 2)]
    lines = render_evidence_chain(refs)
    assert len(lines) == 2


# ── gate_action (fail-closed) ─────────────────────────────────────────────────


def test_gate_action_ok_when_required_present():
    refs = [make_ref("portfolio", {"v": 1}), make_ref("risk", {"h": 2})]
    result = gate_action(refs, ["portfolio", "risk"])
    assert result["ok"] is True
    assert result["missing_domains"] == []


def test_gate_action_blocks_missing_domain():
    refs = [make_ref("portfolio", {"v": 1})]
    result = gate_action(refs, ["portfolio", "risk"])
    assert result["ok"] is False
    assert result["missing_domains"] == ["risk"]


def test_gate_action_blocks_blocking_quality():
    refs = [
        make_ref("portfolio", {"v": 1}),
        make_ref("risk", None, quality_state=QUALITY_STATE_DATA_UNAVAILABLE),
    ]
    result = gate_action(refs, ["portfolio", "risk"])
    assert result["ok"] is False
    assert result["blocking_domains"] == ["risk"]
