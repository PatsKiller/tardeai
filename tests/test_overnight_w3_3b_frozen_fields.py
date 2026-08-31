"""Night Three Wave 3b — frozen fields that imply judgment but never move.

A6 confirmed next_reviews identical across inputs and standing_policy_template
unconditional. A field whose value never moves regardless of input is a
constant, not a judgment.

This tranche demotes those constants off judgment registers:
- next_review / next_reviews → standing_cadence_template when undated
- portfolio_implication → standing_policy_template (B5 + source demotion)

Authority: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_command_center import build_office_home
from scripts.lib.cio_investment_product import (
    PORTFOLIO_IMPLICATION_CONSTANT,
    build_temperament,
)
from scripts.lib.cio_operator_product import (
    _temperament_display,
    build_operator_product,
)
from scripts.lib.cio_operator_renderers import command_center_view
from scripts.lib.operator_decision_contract import (
    NOT_PROVIDED,
    STANDING_CADENCE_TEMPLATE,
    normalize_decision,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _rows_materially_different() -> list[dict]:
    """Five materially different situations — A6 constructed-input shape."""
    return [
        {
            "symbol": "AAPL",
            "recommended_action": "HOLD",
            "priority": "LOW",
            "title": "AAPL hold",
            "description": "thesis remains intact and hold remains correct",
        },
        {
            "symbol": "TSLA",
            "recommended_action": "TRIM",
            "priority": "HIGH",
            "title": "TSLA trim",
            "description": "size too large vs risk budget",
            "data_quality": "DEGRADED",
        },
        {
            "symbol": "NVDA",
            "recommended_action": "AVOID",
            "priority": "NOW",
            "title": "NVDA avoid",
            "description": "valuation extended; wait for reset",
        },
        {
            "symbol": "MSFT",
            "recommended_action": "REENTER",
            "priority": "NEXT",
            "title": "MSFT reenter",
            "description": "back in governed re-entry zone",
        },
        {
            "symbol": "META",
            "recommended_action": "WATCH",
            "priority": "LOW",
            "title": "META watch",
            "description": "wait for catalyst confirmation",
        },
    ]


def _write_brief(root: Path, *, recommendations: list[dict], temperament: dict | None = None) -> None:
    from scripts.lib.canonical_store_registry import resolve_store

    loc = resolve_store("cio.product.current", root=root)
    path = Path(loc["primary_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = temperament or {
        "title": "RISK OFF — SELECTIVE RISK",
        "regime": "risk off",
        "regime_as_of": "2026-08-28",
        "cash": 100.0,
        "cash_pct": 10.0,
        "portfolio_implication": None,
        "standing_policy_template": PORTFOLIO_IMPLICATION_CONSTANT,
        "portfolio_implication_class": "T",
        "portfolio_implication_is_guidance": False,
        "portfolio_implication_role": "standing_policy_template",
        "narrative": "Temperament RISK OFF.",
    }
    path.write_text(
        json.dumps(
            {
                "schema": "CIOInvestmentProduct@v1",
                "available": True,
                "as_of": "2026-08-31T12:00:00+00:00",
                "product_id": "w3_3b_brief",
                "decision_id": "w3_3b_brief",
                "final_position": "HOLD",
                "summary": {"headline": "[T] Nothing requires action today."},
                "recommendations": recommendations,
                "temperament": temp,
                "reentry_book": {
                    "count": 0,
                    "counts": {},
                    "surface": "A",
                    "scope": "former holdings vs exit trigger",
                },
            }
        ),
        encoding="utf-8",
    )


# ── contract demotion ────────────────────────────────────────────────────────

def test_standing_cadence_demoted_off_dated_catalyst_fields():
    """BEFORE: next_review carried the cadence constant on every card.
    AFTER: judgment fields cleared; constant on standing_cadence_template.
    """
    before = STANDING_CADENCE_TEMPLATE
    d = normalize_decision(
        {
            "symbol": "SCHD",
            "recommended_action": "HOLD",
            "title": "HOLD SCHD",
            "description": "Thesis intact; quality compounder remains core.",
        },
        generation_id="g1",
        as_of="2026-08-31T12:00:00+00:00",
    )
    assert d["next_review"] is None
    assert d["next_review_at"] is None
    assert d["standing_cadence_template"] == before
    assert d["next_review_role"] == "standing_cadence_template"
    assert d["next_review_is_dated_catalyst"] is False
    assert d["field_status"]["next_review_at"] == NOT_PROVIDED


def test_dated_catalyst_still_renders_when_producer_supplies_one():
    d = normalize_decision(
        {
            "symbol": "META",
            "recommended_action": "WATCH",
            "title": "META watch",
            "description": "wait for catalyst",
            "next_review": "2026-09-15 earnings",
        },
        generation_id="g1",
    )
    assert d["next_review"] == "2026-09-15 earnings"
    assert d["next_review_at"] == "2026-09-15 earnings"
    assert d["next_review_is_dated_catalyst"] is True
    assert d["next_review_role"] == "dated_catalyst"
    assert d["standing_cadence_template"] is None


def test_a6_constructed_inputs_cadence_identical_but_demoted():
    """Feed materially different situations; cadence constant is byte-identical
    across all of them — and that is now honest because it is not on the
    judgment-shaped next_review fields.
    """
    outs = [
        normalize_decision(r, generation_id="g_a6", as_of="2026-08-31T00:00:00+00:00")
        for r in _rows_materially_different()
    ]
    # Judgment fields are uniformly cleared (identical Nones) — honest omit.
    assert all(o["next_review"] is None for o in outs)
    assert all(o["next_review_at"] is None for o in outs)
    # Template field is byte-identical across all five — expected constant.
    templates = [o["standing_cadence_template"] for o in outs]
    assert len(set(templates)) == 1
    assert templates[0] == STANDING_CADENCE_TEMPLATE
    # Decisions themselves still move with input.
    assert len({o["decision"] for o in outs}) > 1
    assert len({o["entity"] for o in outs}) == 5


# ── temperament / standing policy ────────────────────────────────────────────

def test_build_temperament_writes_standing_policy_not_guidance():
    temp = build_temperament(
        regime={"label": "risk_off", "as_of": "2026-08-28"},
        holdings={"positions": []},
        fs_rows=[],
        lessons={"counts": {"RATIFIED_CONTEXT": 0}},
        infl={
            "gates": {"lesson_mode": "OFF", "financial_senses_mode": "OFF"},
            "memory_mode": "OFF",
            "memory_behavior_influence": 0,
        },
    )
    assert temp["portfolio_implication"] is None
    assert temp["standing_policy_template"] == PORTFOLIO_IMPLICATION_CONSTANT
    assert temp["portfolio_implication_is_guidance"] is False
    assert temp["portfolio_implication_role"] == "standing_policy_template"


def test_standing_policy_identical_across_regimes_and_honest():
    """standing_policy_template is unconditional — byte-identical across
    materially different regimes. Honest because it is labeled a template,
    not situation guidance.
    """
    regimes = [
        {"label": "risk_off", "as_of": "2026-08-01"},
        {"label": "risk_on", "as_of": "2026-08-15"},
        {"label": "UNKNOWN", "as_of": None},
    ]
    temps = []
    for reg in regimes:
        temps.append(
            build_temperament(
                regime=reg,
                holdings={"positions": []},
                fs_rows=[{"id": 1}] if reg["label"] == "risk_on" else [],
                lessons={"counts": {"RATIFIED_CONTEXT": 2 if reg["label"] == "risk_off" else 0}},
                infl={
                    "gates": {"lesson_mode": "OFF", "financial_senses_mode": "OFF"},
                    "memory_mode": "OFF",
                    "memory_behavior_influence": 0,
                },
            )
        )
    policies = [t["standing_policy_template"] for t in temps]
    assert len(set(policies)) == 1
    assert policies[0] == PORTFOLIO_IMPLICATION_CONSTANT
    assert all(t["portfolio_implication"] is None for t in temps)
    # Title / narrative still move with regime — judgment-capable fields vary.
    assert len({t["title"] for t in temps}) > 1


def test_temperament_display_idempotent_when_already_demoted():
    temp = _temperament_display(
        {
            "portfolio_implication": None,
            "standing_policy_template": PORTFOLIO_IMPLICATION_CONSTANT,
            "portfolio_implication_class": "T",
            "portfolio_implication_is_guidance": False,
            "portfolio_implication_role": "standing_policy_template",
            "cash": 100.0,
        },
        {"as_of": "2026-08-03", "cash_as_of": {"as_of": "2026-08-03"}},
    )
    assert temp["portfolio_implication"] is None
    assert temp["standing_policy_template"] == PORTFOLIO_IMPLICATION_CONSTANT
    assert temp["portfolio_implication_is_guidance"] is False


# ── operator product / surfaces ──────────────────────────────────────────────

def test_product_next_reviews_omits_standing_cadence(tmp_path: Path):
    """BEFORE: next_reviews = [cadence, cadence, …] identical across entries.
    AFTER: next_reviews = [] (judgment register empty); constant on template.
    """
    recs = [
        {
            "symbol": r["symbol"],
            "recommended_action": r["recommended_action"],
            "title": r["title"],
            "description": r["description"],
            "priority": r.get("priority"),
        }
        for r in _rows_materially_different()
    ]
    _write_brief(tmp_path, recommendations=recs)
    product = build_operator_product(root=tmp_path, persist=False)
    assert product["next_reviews"] == []
    assert product["standing_cadence_template"] == STANDING_CADENCE_TEMPLATE
    assert product["next_reviews_role"] == "standing_cadence_template"
    assert product["next_reviews_is_judgment"] is False
    # Decision cards projected via CC view omit next_review when demoted.
    view = command_center_view(product)
    assert all((d.get("next_review") in (None, "")) for d in view["decisions"])
    temp = view["temperament"]
    assert temp.get("portfolio_implication") in (None, "")
    assert temp.get("standing_policy_template") == PORTFOLIO_IMPLICATION_CONSTANT


def test_product_keeps_dated_catalyst_in_next_reviews(tmp_path: Path):
    recs = [
        {
            "symbol": "META",
            "recommended_action": "WATCH",
            "title": "META watch",
            "description": "wait for catalyst",
            "next_review": "2026-09-15 earnings",
        },
        {
            "symbol": "AAPL",
            "recommended_action": "HOLD",
            "title": "AAPL hold",
            "description": "thesis remains intact and hold remains correct",
        },
    ]
    _write_brief(tmp_path, recommendations=recs)
    product = build_operator_product(root=tmp_path, persist=False)
    assert len(product["next_reviews"]) == 1
    assert "2026-09-15 earnings" in product["next_reviews"][0]
    assert product["next_reviews_is_judgment"] is True
    assert product["next_reviews_role"] == "dated_catalysts"
    # Standing cadence still recorded for the undated entry.
    assert product["standing_cadence_template"] == STANDING_CADENCE_TEMPLATE


def test_home_temperament_demotion(tmp_path: Path):
    _write_brief(
        tmp_path,
        recommendations=[],
        temperament={
            "title": "RISK OFF",
            "portfolio_implication": PORTFOLIO_IMPLICATION_CONSTANT,
            "portfolio_implication_class": "T",
        },
    )
    product = build_operator_product(root=tmp_path, persist=False)
    home = build_office_home(operator_product=product)
    assert home["temperament"].get("portfolio_implication") in (None, "")
    assert home["temperament"].get("standing_policy_template") == PORTFOLIO_IMPLICATION_CONSTANT
    assert home["temperament"].get("portfolio_implication_is_guidance") is False
