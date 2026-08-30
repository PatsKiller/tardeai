"""Telegram delivery is ON, at the narrowest bar the operator asked for.

2026-08-29 operator sentence: "Telegram on" — channel @tradeai_cio_bot, bar
S6 fire only. Two independent gates must BOTH be true to deliver
(`situation_notify_telegram` here and CIO_SITUATION_NOTIFY=1 in the unit
environment), so this file pins the config half.

The re-notify guards are pinned as hard as the bar itself. They are what keeps
a 4-message desk from becoming a 400-message one on the next re-enrich.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

POLICY = Path(__file__).resolve().parent.parent / "config" / "cio_llm_policy.yaml"


@pytest.fixture(scope="module")
def pol():
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def test_delivery_is_enabled(pol):
    assert pol["situation_notify_telegram"] is True


def test_the_bar_is_s6_only(pol):
    """Widening this list is a deliberate act needing its own sentence."""
    assert pol["notify_situation_types"] == ["S6_CONCENTRATION_OR_DISPOSITION"]


@pytest.mark.parametrize("sit", [
    "S1_POSITION_LIFECYCLE", "S2_STOP_GAP",
    "S5_CASH_DEPLOYMENT", "S8_DEFENSIVE_REGIME",
])
def test_the_other_canary_types_do_not_deliver(pol, sit):
    assert sit not in pol["notify_situation_types"]


def test_the_re_notify_guards_are_intact(pol):
    """Re-enrich must not re-push. These bound the blast radius."""
    assert pol["notify_once_per_fingerprint"] is True
    assert float(pol["notify_cooldown_hours"]) >= 12
    assert float(pol["notify_min_gap_minutes"]) >= 5


def test_the_financial_lane_is_untouched(pol):
    """Delivery on is not authority on. MBI stays 0, no financial action."""
    txt = POLICY.read_text(encoding="utf-8")
    assert "financial lane remains OFF_BY_POLICY" in txt
