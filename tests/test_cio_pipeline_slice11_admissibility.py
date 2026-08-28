"""Slice 11: live advisory path gates TRIM of non-held. Fail-closed on unknown holding."""
from __future__ import annotations

from scripts.lib.cio_advisory_admissibility import (
    UNKNOWN_HOLDING,
    admit_advisory,
    gate_recommendation_rows,
)
from scripts.lib.cio_investment_product import _recommendations


HELD = {"holdings": [{"symbol": "SCHD", "quantity": 10, "price": 80}], "generated_at": "2026-08-28"}


def test_fake_trim_of_non_held_blocked():
    recs = _recommendations(
        {
            "DO_NOW": [{"symbol": "FAKETICK", "action": "TRIM", "why": "too big"}],
            "WATCH_CLOSELY": [],
            "RE_ENTER_IF": [],
            "AVOID": [],
        },
        {"title": "TEST", "portfolio_implication": "x", "narrative": "y"},
        holdings=HELD,
    )
    fake = [r for r in recs if r.get("symbol") == "FAKETICK"]
    assert fake
    assert fake[0]["blocked"] is True
    assert fake[0]["recommended_action"] == "NO_ACTION"
    assert "NOT CURRENTLY HELD" in fake[0]["to_block"]
    assert fake[0]["original_recommendation"] == "TRIM"


def test_held_trim_still_admissible():
    recs = _recommendations(
        {
            "DO_NOW": [{"symbol": "SCHD", "action": "TRIM", "why": "size"}],
            "WATCH_CLOSELY": [],
            "RE_ENTER_IF": [],
            "AVOID": [],
        },
        {"title": "TEST", "portfolio_implication": "x", "narrative": "y"},
        holdings=HELD,
    )
    schd = [r for r in recs if r.get("symbol") == "SCHD"]
    assert schd
    assert not schd[0].get("blocked")
    assert schd[0]["recommended_action"] == "TRIM"


def test_unknown_holding_fail_closed():
    g = admit_advisory(symbol="NVDA", recommendation="TRIM", holdings={})
    assert g["admissible"] is False
    assert g["reason"] == UNKNOWN_HOLDING
    assert g["blocked"] is True
    rows = gate_recommendation_rows(
        [{"symbol": "NVDA", "recommended_action": "TRIM"}],
        holdings=None,
    )
    assert rows[0]["recommended_action"] == "NO_ACTION"
    assert rows[0]["blocked"] is True


def test_avoid_on_unheld_is_not_disposal():
    g = admit_advisory(symbol="NKE", recommendation="AVOID", holdings=HELD)
    assert g["admissible"] is True
    assert not g["blocked"]
