"""Pure entry-card presentation: a plan ratio never stands in for a current ratio."""

from copy import deepcopy

import pytest

from scripts.lib import telegram_cards as cards

BASE = {
    "symbol": "CANARY",
    "price": 20,
    "stop": 15,
    "target": 30,
    "entry_low": 18,
    "entry_high": 19,
}


@pytest.fixture(autouse=True)
def isolated_card_chrome(monkeypatch):
    """No config, source lookup, provider or delivery is needed to render the facts."""
    monkeypatch.setattr(cards, "ttl_text", lambda category: "4 days")
    for name in ("cc_symbol_url", "cc_trading_url", "trading_view_url", "opportunity_url", "chart_image_url"):
        monkeypatch.setattr(cards, name, lambda symbol: "https://example.invalid/" + symbol)


def render(item):
    return cards.entry_card(
        item,
        marker="🟡",
        state="NEAR_ENTRY",
        stance="HUMAN REVIEW",
        held=False,
        review_status="UNREVIEWED",
        next_action="Review before allocating capital",
        hard_block=None,
        evidence=["Advisory only — nothing queued, nothing executed"],
    ).render()


def ratio_line(item):
    return next(line for line in render(item)["text"].splitlines() if "R:R" in line)


def test_plan_ratio_cannot_stand_in_for_missing_current():
    line = ratio_line({**BASE, "rr": 1.8})
    assert "R:R unavailable at current price" in line
    assert "ideal-zone 1.80" in line


def test_existing_advisory_headers_and_supplied_levels_are_preserved():
    payload = render({**BASE, "current_rr": 0.8, "rr": 1.8})
    text = payload["text"]
    assert "ENTRY APPROACHING" in text
    assert "HUMAN REVIEW" in text and "Review: UNREVIEWED" in text
    assert "Current: $20.00" in text and "Zone: $18.00 - $19.00" in text
    assert "$15.00 · risk to stop $5.00" in text
    assert "$30.00 · reward to target $10.00" in text
    assert "nothing queued, nothing executed" in text
    assert payload["parse_mode"] == "HTML"


def test_zero_risk_does_not_make_the_renderer_calculate_a_ratio():
    text = render({**BASE, "price": 15, "stop": 15})["text"]
    assert "risk to stop $0.00" in text
    assert "R:R inf" not in text and "R:R nan" not in text
    assert "R:R 2.00" not in text


@pytest.mark.parametrize("key", ["rr_at_ideal_entry", "rr", "ideal_rr"])
def test_supported_plan_aliases_are_explicitly_labeled(key):
    line = ratio_line({**BASE, key: 1.8})
    assert "R:R unavailable at current price" in line
    assert "ideal-zone 1.80" in line


@pytest.mark.parametrize("key", ["rr_at_current_price", "current_rr"])
def test_supplied_current_is_labeled_without_recalculating_it(key):
    line = ratio_line({**BASE, key: 0.8, "rr_at_ideal_entry": 1.8})
    assert "R:R 0.80 at current price" in line
    assert "ideal-zone 1.80" in line
    assert "2.00" not in line, "the supplied value must not be replaced with a newly calculated ratio"


def test_valid_zero_ratios_are_not_missing():
    line = ratio_line({**BASE, "rr_at_current_price": 0, "rr_at_ideal_entry": 0})
    assert "R:R 0.00 at current price" in line
    assert "ideal-zone 0.00" in line
    assert "unavailable" not in line


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf"), "NaN", "Infinity", "bad", {}, True])
def test_missing_or_nonfinite_ratios_are_unavailable_for_their_own_basis(value):
    line = ratio_line({**BASE, "rr_at_current_price": value, "rr_at_ideal_entry": value})
    assert "R:R unavailable at current price" in line
    assert "ideal-zone unavailable" in line


def test_missing_plan_does_not_hide_a_valid_current_ratio():
    line = ratio_line({**BASE, "rr_at_current_price": 0.8})
    assert "R:R 0.80 at current price" in line
    assert "ideal-zone unavailable" in line


def test_explicit_null_and_existing_alias_precedence_are_preserved():
    line = ratio_line({**BASE, "rr_at_current_price": None, "current_rr": 0.8, "rr_at_ideal_entry": None, "rr": 1.8})
    assert "R:R unavailable at current price" in line
    assert "ideal-zone unavailable" in line


def test_rendering_does_not_mutate_the_advisory_packet():
    item = {**BASE, "rr_at_current_price": 0.8, "rr_at_ideal_entry": 1.8, "unrelated": {"retained": [1, 2]}}
    before = deepcopy(item)
    render(item)
    assert item == before
