from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_maturity_levels import maturity_contract, maturity_level
from scripts.lib.cio_operator_investment_policy import (
    FIELD_SPECS,
    build_operator_investment_policy,
    discover_legacy_policy_claims,
    ratify_policy_field,
)
from scripts.lib.cio_portfolio_state_v1 import build_portfolio_state


def _holding(symbol: str, value: float, *, account: str = "acct", cash: bool = False, conflicted: bool = False):
    return {
        "symbol": symbol,
        "account_id": account,
        "is_cash": cash,
        "asset_type": "cash" if cash else "equity",
        "market_value": value,
        "canonical_mark": 1.0 if cash else 100.0,
        "source": "read_only_fixture",
        "as_of": "2026-08-23T12:00:00+00:00",
        "conflicted": conflicted,
    }


def test_maturity_contract_preserves_unmeasured_evidence():
    assert maturity_level(None) == {"level": None, "code": "UNMEASURED", "evidence": []}
    contract = maturity_contract()
    assert contract["levels"][7]["code"] == "INSTITUTIONAL_AUTONOMOUS_PROVEN"
    assert contract["missing_evidence"] == "UNMEASURED"


def test_policy_fails_closed_and_inventories_legacy_conflicts(tmp_path: Path):
    policy = build_operator_investment_policy(
        store_path=str(tmp_path / "profile.jsonl"),
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert policy["status"] == "POLICY_REQUIRED"
    assert policy["confirmed_field_count"] == 0
    assert set(policy["missing_fields"]) == set(FIELD_SPECS)
    conflicts = {row["field"]: row for row in policy["legacy_conflicts"]}
    assert "cash_target_range_pct" in conflicts
    assert "max_single_position_pct" in conflicts
    assert {claim["value"] for claim in conflicts["max_single_position_pct"]["claims"]} == {8.0, 12.0}


def test_policy_ratification_is_versioned_operator_confirmation(tmp_path: Path):
    store = tmp_path / "profile.jsonl"
    receipt = ratify_policy_field(
        "cash_target_range_pct",
        {"min": 5, "max": 15},
        store_path=str(store),
    )
    policy = build_operator_investment_policy(
        store_path=str(store),
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert receipt["financial_authority_changed"] is False
    assert policy["fields"]["cash_target_range_pct"]["value"] == {"min": 5.0, "max": 15.0}
    assert policy["fields"]["cash_target_range_pct"]["operator_confirmed"] is True
    assert policy["status"] == "POLICY_REQUIRED"


def test_complete_ratification_resolves_legacy_conflicts(tmp_path: Path):
    store = tmp_path / "profile.jsonl"
    values = {
        "range_pct": {"min": 0, "max": 100},
        "money": 0,
        "text": "operator confirmed",
        "list": [],
        "object": {"max_single_position_pct": 8},
    }
    for name, spec in FIELD_SPECS.items():
        ratify_policy_field(name, values[spec["kind"]], store_path=str(store))
    policy = build_operator_investment_policy(
        store_path=str(store),
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert policy["status"] == "CONFIRMED"
    assert policy["missing_fields"] == []
    assert policy["legacy_conflicts"] == []


@pytest.mark.parametrize(
    "value",
    [None, {"min": -1, "max": 5}, {"min": 20, "max": 10}, {"min": 0, "max": 101}],
)
def test_policy_rejects_invalid_ranges(tmp_path: Path, value):
    with pytest.raises((TypeError, ValueError)):
        ratify_policy_field("cash_target_range_pct", value, store_path=str(tmp_path / "profile.jsonl"))


def test_portfolio_state_does_not_equate_observed_and_investable_cash():
    doc = {
        "generated_at": "2026-08-23T12:00:00+00:00",
        "holdings": [_holding("CASH", 500_000, cash=True), _holding("NOC", 500_000)],
        "portfolio_totals": {"total_value": 1_000_000},
    }
    state = build_portfolio_state(doc)
    assert state["observed_cash_usd"] == 500_000
    assert state["investable_cash_usd"] is None
    assert state["investable_cash_status"] == "UNVERIFIED_INVESTABLE"
    assert state["truth_quality"] == "UNVERIFIED_INVESTABLE"
    assert state["allocation"]["cash"]["pct"] == 50.0


def test_portfolio_state_requires_read_only_evidence_for_every_cash_account():
    doc = {
        "holdings": [
            _holding("CASH", 100, account="a", cash=True),
            _holding("CASH", 200, account="b", cash=True),
            _holding("NOC", 700),
        ],
        "portfolio_totals": {"total_value": 1_000},
    }
    proof = {
        "a": {"verified": True, "source_class": "BROKER_READ_ONLY", "source": "broker_read", "as_of": "now", "investable_cash_usd": 80},
        "b": {"verified": True, "source_class": "BROKER_READ_ONLY", "source": "broker_read", "as_of": "now", "investable_cash_usd": 150},
    }
    state = build_portfolio_state(doc, broker_cash_evidence=proof)
    assert state["truth_quality"] == "VERIFIED"
    assert state["investable_cash_usd"] == 230


def test_portfolio_state_conflict_and_unavailable_states():
    conflicted = build_portfolio_state({
        "holdings": [_holding("NOC", 100, conflicted=True)],
        "portfolio_totals": {"total_value": 100},
    })
    assert conflicted["truth_quality"] == "CONFLICTED"
    assert conflicted["conflicted_position_count"] == 1

    unavailable = build_portfolio_state({"holdings": []})
    assert unavailable["truth_quality"] == "UNAVAILABLE"
    assert unavailable["total_portfolio_value_usd"] == 0


def test_contract_sources_contain_no_broker_mutation_surface():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "scripts/lib/cio_operator_investment_policy.py",
        "scripts/lib/cio_portfolio_state_v1.py",
    ):
        source = (root / rel).read_text(encoding="utf-8").lower()
        for forbidden in ("place_order(", "cancel_order(", "modify_stop(", "2fa"):
            assert forbidden not in source


def test_cio_brain_api_policy_and_portfolio_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from scripts import api_v3_cio

    holdings = tmp_path / "holdings.json"
    holdings.write_text(json.dumps({
        "generated_at": "2026-08-23T12:00:00+00:00",
        "holdings": [_holding("CASH", 400, cash=True), _holding("NOC", 600)],
        "portfolio_totals": {"total_value": 1_000},
    }), encoding="utf-8")
    monkeypatch.setenv("CIO_OPERATOR_PROFILE_JSONL", str(tmp_path / "profile.jsonl"))
    monkeypatch.setenv("TRADEAI_HOLDINGS_JSON", str(holdings))
    monkeypatch.setenv("CIO_CASH_EVIDENCE_JSON", str(tmp_path / "missing-cash-evidence.json"))

    policy = api_v3_cio.get_operator_investment_policy()
    assert policy["ok"] is True
    assert policy["policy"]["status"] == "POLICY_REQUIRED"
    rejected = api_v3_cio.post_operator_investment_policy_ratification({
        "field_name": "benchmark", "value": "SPY",
    })
    assert rejected["error"] == "operator_confirmation_required"
    accepted = api_v3_cio.post_operator_investment_policy_ratification({
        "field_name": "benchmark", "value": "SPY", "operator_identity_class": "OPERATOR",
    })
    assert accepted["ok"] is True
    assert accepted["policy"]["fields"]["benchmark"]["value"] == "SPY"

    state = api_v3_cio.get_portfolio_state_v1()
    assert state["ok"] is True
    assert state["portfolio_state"]["observed_cash_usd"] == 400
    assert state["portfolio_state"]["investable_cash_usd"] is None
