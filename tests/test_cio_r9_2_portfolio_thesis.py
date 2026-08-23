from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_portfolio_thesis_v1 import (
    build_portfolio_thesis_candidate,
    classify_portfolio_thesis_delta,
    load_latest_portfolio_thesis,
    load_symbol_thesis_refs,
    reconcile_portfolio_thesis,
)


NOW = datetime(2026, 8, 23, 14, 0, tzinfo=timezone.utc)


def _policy(confirmed: bool = False) -> dict:
    fields = {
        "cash_target_range_pct": {"value": {"min": 5, "max": 15}, "operator_confirmed": confirmed},
        "equity_range_pct": {"value": {"min": 60, "max": 80}, "operator_confirmed": confirmed},
        "fixed_income_range_pct": {"value": {"min": 10, "max": 25}, "operator_confirmed": confirmed},
    }
    return {"status": "CONFIRMED" if confirmed else "POLICY_REQUIRED", "version": "policy_v1", "content_hash": "p1", "fields": fields}


def _portfolio(*, verified: bool = False, conflicted: bool = False) -> dict:
    return {
        "version": "portfolio_v1",
        "truth_quality": "CONFLICTED" if conflicted else ("VERIFIED" if verified else "UNVERIFIED_INVESTABLE"),
        "observed_cash_usd": 578_111.14,
        "investable_cash_usd": 500_000.0 if verified else None,
        "conflicted_position_count": 1 if conflicted else 0,
        "allocation": {
            "cash": {"pct": 45.04},
            "equity": {"pct": 54.96},
            "fixed_income": {"pct": 0.0},
        },
    }


def _market(verified: bool = False) -> dict:
    return {
        "version": "market_v1",
        "truth_quality": "VERIFIED" if verified else "PARTIAL",
        "fields": {"regime": {"value": "risk_on_trend"}},
    }


def _seasonality(verified: bool = False) -> dict:
    return {"version": "seasonality_v1", "truth_quality": "VERIFIED" if verified else "UNAVAILABLE"}


def _candidate(**overrides) -> dict:
    values = {
        "policy": _policy(),
        "portfolio_state": _portfolio(),
        "market_context": _market(),
        "seasonality": _seasonality(),
        "symbol_theses": [{"symbol": "NOC", "thesis_id": "symbol_noc", "thesis_version": "symbol_noc@v5", "stance": "HOLD"}],
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return build_portfolio_thesis_candidate(**values)


def test_initial_live_shape_is_honestly_insufficient() -> None:
    candidate = _candidate()
    assert candidate["state"] == "INSUFFICIENT_DATA"
    assert candidate["current_posture"] == "HOLD_CASH_RESEARCH_FIRST"
    assert candidate["cash_posture"]["investable_cash_usd"] is None
    assert "OPERATOR_POLICY_REQUIRED" in candidate["research_gaps"]
    assert "INVESTABLE_CASH_UNVERIFIED" in candidate["research_gaps"]
    assert candidate["financial_action"] is False
    assert candidate["symbol_thesis_refs"] == [{
        "symbol": "NOC",
        "thesis_id": "symbol_noc",
        "thesis_version": "symbol_noc@v5",
        "stance": "HOLD",
        "portfolio_role": None,
    }]


def test_identical_semantic_evidence_does_not_create_a_new_version(tmp_path: Path) -> None:
    store = tmp_path / "portfolio.jsonl"
    first = reconcile_portfolio_thesis(_candidate(), store_path=str(store))
    second = reconcile_portfolio_thesis(_candidate(evaluated_at=NOW.replace(minute=1)), store_path=str(store))
    assert first["published"] is True
    assert first["thesis"]["thesis_version"] == "cio_portfolio@v1"
    assert second["published"] is False
    assert second["delta"]["classification"] == "NO_NEW_INFO"
    assert len(store.read_text(encoding="utf-8").splitlines()) == 1


def test_new_material_evidence_versions_and_classifies_delta(tmp_path: Path) -> None:
    store = tmp_path / "portfolio.jsonl"
    reconcile_portfolio_thesis(_candidate(), store_path=str(store))
    current = _candidate(
        policy=_policy(confirmed=True),
        portfolio_state=_portfolio(verified=True),
        market_context=_market(verified=True),
        seasonality=_seasonality(verified=True),
        methodology_refs=["canon_claim_1"],
    )
    result = reconcile_portfolio_thesis(current, store_path=str(store))
    assert result["published"] is True
    assert result["thesis"]["thesis_version"] == "cio_portfolio@v2"
    assert result["delta"]["classification"] == "ROTATES"
    assert load_latest_portfolio_thesis(str(store))["state"] == "CURRENT"


def test_conflicted_canonical_input_never_becomes_actionable() -> None:
    candidate = _candidate(portfolio_state=_portfolio(conflicted=True))
    delta = classify_portfolio_thesis_delta(None, candidate)
    assert candidate["state"] == "CONFLICTED"
    assert candidate["current_posture"] == "RESEARCH_FIRST"
    assert delta["classification"] == "CONFLICTED"
    assert delta["financial_action"] is False


def test_content_hash_tampering_is_rejected() -> None:
    candidate = _candidate()
    candidate["core_thesis"] = "tampered"
    with pytest.raises(ValueError, match="content_hash mismatch"):
        classify_portfolio_thesis_delta(None, candidate)


def test_symbol_projection_only_returns_held_identity_refs(tmp_path: Path) -> None:
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps({"current": {
        "symbol_noc": {"symbol": "NOC", "thesis_version": "symbol_noc@v5", "state": "CURRENT"},
        "symbol_msft": {"symbol": "MSFT", "thesis_version": "symbol_msft@v2", "state": "THIN"},
        "desk": {"thesis_version": "desk@v9"},
    }}), encoding="utf-8")
    refs = load_symbol_thesis_refs(projection, {"NOC"})
    assert refs == [{
        "symbol": "NOC",
        "thesis_id": "symbol_noc",
        "thesis_version": "symbol_noc@v5",
        "stance": "CURRENT",
        "portfolio_role": None,
    }]


def test_portfolio_thesis_sources_have_no_financial_mutation_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = ("schwab_order", "place_order", "cancel_order", "modify_stop", "unlock_broker", "two_factor")
    for relative in (
        "scripts/lib/cio_portfolio_thesis_v1.py",
        "scripts/materialize_cio_portfolio_thesis.py",
    ):
        source = (root / relative).read_text(encoding="utf-8").lower()
        assert not any(token in source for token in forbidden)
