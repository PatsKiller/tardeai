"""Canonical options recommendation comparison. No network.

    .venv/bin/python -m pytest tests/test_recommendation_comparison_20260925.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.options_strategy_matrix import ABSENT, MATRIX, known_family, registry_gaps
from scripts.lib.recommendation_comparison import build_recommendation_comparison

_THESIS = {"verdict": "constructive", "direction": "bullish", "thesis_version": "desk@v9", "evidence_refs": []}


def _cc(**extra):
    row = {
        "symbol": "V",
        "strategy": "covered_call",
        "data_source": "schwab_chain",
        "underlying_price": 367.53,
        "stop": 357.50,
        "share_count": 100,
        "premium_total": 171,
        "dte": 29,
        "pop_pct": 55,
        "pop_basis": "desk_cache",
        "enterprise": {"live_eligible": True, "blocks": []},
    }
    row.update(extra)
    return row


def test_covered_call_risk_is_the_shares_not_the_premium():
    cmp = build_recommendation_comparison(
        _cc(), equity={"price": 367.53, "stop": 357.50, "share_count": 100}, thesis=_THESIS,
        generated_at="2026-09-25T00:00:00Z",
    )
    assert "Premium is income" in cmp["stock_play"]["maximum_loss_model"]
    assert cmp["options_play"]["maximum_risk"] == round((367.53 - 357.50) * 100, 2)
    assert cmp["options_play"]["maximum_risk"] != 171


def test_nine_shares_is_review_required():
    cmp = build_recommendation_comparison(
        _cc(share_count=9), equity={"price": 367.53, "stop": 357.50, "share_count": 9}, thesis=_THESIS,
    )
    assert cmp["comparison"]["preferred_structure"] == "review_required"
    assert "NEED_100_SHARES" in cmp["stock_play"]["risk_notes"]


def test_credit_spread_uses_package_max_loss():
    row = {
        "symbol": "RDDT",
        "strategy": "credit_spread",
        "data_source": "schwab_chain",
        "max_loss": 500,
        "max_profit": 120,
        "premium_total": 40,
        "dte": 30,
        "pop_pct": 60,
        "pop_basis": "package",
        "underlying_price": 200,
        "stop": 180,
        "share_count": 100,
        "enterprise": {"live_eligible": True, "blocks": []},
    }
    cmp = build_recommendation_comparison(row, thesis=_THESIS, generated_at="2026-09-25T00:00:00Z")
    assert cmp["options_play"]["maximum_risk"] == 500
    assert cmp["options_play"]["maximum_risk"] != 40


def test_missing_pop_cannot_prefer_options():
    row = _cc()
    row.pop("pop_pct")
    row.pop("pop_basis")
    cmp = build_recommendation_comparison(row, thesis=_THESIS)
    assert cmp["options_play"]["probability_of_success"] is None
    assert cmp["comparison"]["preferred_structure"] != "options"


def test_ensemble_is_not_a_cio_review():
    row = _cc(ensemble_verdict={"confidence": 0.91})
    cmp = build_recommendation_comparison(row, thesis=_THESIS)
    assert cmp["oversight"]["review_status"] == "unreviewed"
    assert cmp["oversight"]["authority"] == "READ_ONLY_ADVISORY"


def test_stale_quote_cannot_prefer_options():
    cmp = build_recommendation_comparison(_cc(quote_stale=True), thesis=_THESIS)
    assert cmp["provenance"]["freshness"] == "stale"
    assert cmp["comparison"]["preferred_structure"] != "options"


def test_same_inputs_are_stable_and_carry_no_behavior_keys():
    kwargs = dict(
        equity={"price": 367.53, "stop": 357.50, "share_count": 100},
        thesis=_THESIS,
        generated_at="2026-09-25T00:00:00Z",
    )
    a = build_recommendation_comparison(_cc(), **kwargs)
    b = build_recommendation_comparison(_cc(), **kwargs)
    assert a == b

    def walk(node):
        if isinstance(node, dict):
            assert not {"shares", "qty", "order", "size_usd"} & set(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(a)


def test_a_cheap_spread_does_not_invent_a_stock_side():
    row = {
        "symbol": "T",
        "strategy": "debit_spread",
        "data_source": "schwab_chain",
        "max_loss": 100,
        "dte": 30,
        "pop_pct": 50,
        "pop_basis": "package",
        "enterprise": {"live_eligible": True, "blocks": []},
    }
    cmp = build_recommendation_comparison(row, thesis=_THESIS)
    assert cmp["stock_play"]["action"] == "unavailable"
    assert cmp["comparison"]["preferred_structure"] == "review_required"


def test_desk_pin_is_not_this_proposals_thesis():
    row = _cc()
    cmp = build_recommendation_comparison(row, generated_at="2026-09-25T21:00:00Z")
    assert cmp["thesis"]["thesis_version"] is None
    assert cmp["comparison"]["preferred_structure"] == "review_required"
    assert cmp["provenance"]["policy_versions"] == ["policy_version_unpinned"]
    assert "1.2.7" not in str(cmp["provenance"]["policy_versions"])


def test_bare_cio_string_is_not_a_review():
    row = _cc(cio_disposition="reviewed")
    cmp = build_recommendation_comparison(row, thesis=_THESIS)
    assert cmp["oversight"]["review_status"] == "unreviewed"
    linked = build_recommendation_comparison(
        _cc(cio_disposition="reviewed", cio_review_id="rev-1"), thesis=_THESIS,
    )
    assert linked["oversight"]["review_status"] == "reviewed"
    assert linked["oversight"]["cio_review_id"] == "rev-1"


def test_credit_reward_over_risk_not_loss_over_capital():
    row = {
        "symbol": "AMZN",
        "strategy": "credit_spread",
        "data_source": "schwab_chain",
        "underlying_price": 249.38,
        "max_profit": 73,
        "max_loss": 1177,
        "pop_pct": 83.1,
        "dte": 21,
        "enterprise": {"live_eligible": True, "blocks": []},
    }
    cmp = build_recommendation_comparison(row, thesis=_THESIS)
    assert cmp["options_play"]["probability_of_success"] == 83.1
    assert cmp["options_play"]["probability_basis"] == "proposal.pop_pct"
    assert cmp["options_play"]["expected_return"] is None
    assert cmp["options_play"]["max_profit"] == 73
    assert cmp["comparison"]["reward_to_risk"] == round(73 / 1177, 4)
    assert cmp["comparison"]["risk_reward"] == cmp["comparison"]["reward_to_risk"]
    assert cmp["comparison"]["risk_to_capital"] != cmp["comparison"]["reward_to_risk"]
    assert cmp["comparison"]["preferred_structure"] == "neither"
    assert cmp["comparison"]["opportunity_cost"] is None
    text = cmp["comparison"]["capital_efficiency"].lower()
    assert "sell" not in text
    assert "73" in cmp["comparison"]["capital_efficiency"]
    assert "1,177" in cmp["comparison"]["capital_efficiency"] or "1177" in cmp["comparison"]["capital_efficiency"]


def test_amzn_credit_uses_the_numbers_on_the_row_and_refuses():
    row = {
        "symbol": "AMZN",
        "strategy": "credit_spread",
        "account": "schwab_taxable",
        "data_source": "schwab_chain",
        "underlying_price": 249.38,
        "short_strike": 232.5,
        "long_strike": 220,
        "max_profit": 73,
        "max_loss": 1177,
        "pop_pct": 83.1,
        "dte": 21,
        "enterprise": {"live_eligible": True, "blocks": []},
        "ensemble_verdict": {"confidence": 0.8},
    }
    cmp = build_recommendation_comparison(
        row,
        thesis={"verdict": "bullish", "direction": "bullish", "thesis_version": "desk@v5", "evidence_refs": []},
        generated_at="2026-09-25T20:42:00Z",
    )
    assert cmp["options_play"]["probability_of_success"] == 83.1
    assert cmp["options_play"]["probability_basis"] == "proposal.pop_pct"
    assert cmp["options_play"]["expected_return"] is None
    assert cmp["comparison"]["preferred_structure"] == "neither"
    text = cmp["comparison"]["capital_efficiency"]
    assert "73" in text and ("1177" in text or "1,177" in text) and "0.06" in text
    assert "sell" not in text.lower()
    assert "sell" not in cmp["oversight"]["cio_commentary"].lower()
    assert cmp["oversight"]["review_status"] == "unreviewed"
    assert cmp["stock_play"]["maximum_loss_model"] == "No stop on this row, so shares are not compared."


def test_credit_above_the_floor_is_not_refused():
    row = {
        "symbol": "T",
        "strategy": "credit_spread",
        "data_source": "schwab_chain",
        "underlying_price": 200,
        "stop": 180,
        "share_count": 100,
        "max_profit": 400,
        "max_loss": 1000,
        "pop_pct": 55,
        "dte": 30,
        "enterprise": {"live_eligible": True, "blocks": []},
    }
    cmp = build_recommendation_comparison(row, thesis=_THESIS, generated_at="2026-09-25T00:00:00Z")
    assert cmp["comparison"]["risk_reward"] == 0.4
    assert cmp["comparison"]["preferred_structure"] != "neither"


def test_matrix_covers_generated_families_and_refuses_leaps():
    for sid in ("covered_call", "cash_secured_put", "protective_put", "long_call", "debit_spread", "credit_spread"):
        assert known_family(sid)
        assert MATRIX[sid]["negative_cases"]
        assert MATRIX[sid]["lifecycle"].endswith("options_lifecycle_policy.json")
    assert not known_family("leaps_diagonal")
    assert "leaps_diagonal" in ABSENT
    reg = yaml.safe_load((ROOT / "config/options_strategy_registry.yaml").read_text())
    strategies = reg["strategies"]
    flags = {k: bool(v.get("live_enabled")) for k, v in strategies.items()}
    assert registry_gaps(list(strategies), live_flags=flags) == []
