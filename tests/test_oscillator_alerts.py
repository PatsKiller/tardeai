#!/usr/bin/env python3
"""Confluence-flip alerting tests.

Operator decision (2026-09-11): a single oscillator never alerts. A flip fires
only on ENTRY into a STRONG state, which requires >=3 independent families.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import oscillator_alerts as oa  # noqa: E402


def test_single_oscillator_flip_is_not_a_flip():
    # A conditional/neutral move never fires.
    assert oa.is_directional_flip("NEUTRAL", "BULLISH_CONDITIONAL") is False
    assert oa.is_directional_flip("BEARISH_CONDITIONAL", "NEUTRAL") is False
    assert oa.is_directional_flip("BULLISH_STRONG", "BULLISH_CONDITIONAL") is False


def test_entry_into_strong_is_a_flip():
    assert oa.is_directional_flip("NEUTRAL", "BULLISH_STRONG") is True
    assert oa.is_directional_flip("BEARISH_CONDITIONAL", "BULLISH_STRONG") is True
    assert oa.is_directional_flip("MIXED", "BEARISH_STRONG") is True


def test_first_ever_reading_is_not_a_flip():
    # A None prior is day-one; alerting on every first computation floods the
    # channel.
    assert oa.is_directional_flip(None, "BULLISH_STRONG") is False


def test_repeat_of_same_strong_state_is_not_a_flip():
    assert oa.is_directional_flip("BULLISH_STRONG", "BULLISH_STRONG") is False


def test_detect_returns_only_directional_flips():
    records = [
        {"symbol": "A", "prior_state": "NEUTRAL", "new_state": "BULLISH_STRONG", "affiliation": {}},
        {"symbol": "B", "prior_state": "NEUTRAL", "new_state": "BULLISH_CONDITIONAL", "affiliation": {}},
        {"symbol": "C", "prior_state": None, "new_state": "BEARISH_STRONG", "affiliation": {}},
        {"symbol": "D", "prior_state": "BULLISH_CONDITIONAL", "new_state": "BEARISH_STRONG", "affiliation": {}},
    ]
    flips = oa.detect_confluence_flips(records)
    assert [f["symbol"] for f in flips] == ["A", "D"]


def test_notify_never_bypasses_dedupe(monkeypatch, tmp_path):
    """A repeat of the same from->to is suppressed until reversal."""
    sent: list[str] = []
    state_path = str(tmp_path / "alert_condition_state.json")

    flips1 = [{"symbol": "NVDA", "from": "NEUTRAL", "to": "BULLISH_STRONG",
               "transition": "NEUTRAL->BULLISH_STRONG", "oscillator_affiliation": {}}]
    r1 = oa.notify_confluence_flips(flips1, send_fn=sent.append, state_path=state_path)
    assert r1["sent"] == ["NVDA"]

    # Same flip again, no reversal in between -> suppressed.
    r2 = oa.notify_confluence_flips(flips1, send_fn=sent.append, state_path=state_path)
    assert r2["sent"] == []
    assert r2["suppressed"][0]["suppress_reason"] == "ongoing"


def test_reversal_then_reentry_alerts_again(monkeypatch, tmp_path):
    """A DIFFERENT strong entry re-alerts; the state machine keys on from->to.

    detect_confluence_flips only feeds STRONG entries to the notifier, so the
    "reversal" here is a different transition string — matching how
    industry_momentum treats a from->to change as the reversal.
    """
    sent: list[str] = []
    state_path = str(tmp_path / "alert_condition_state.json")

    def flip(frm, to):
        return [{"symbol": "NVDA", "from": frm, "to": to, "transition": f"{frm}->{to}",
                 "oscillator_affiliation": {}}]

    oa.notify_confluence_flips(flip("NEUTRAL", "BULLISH_STRONG"), send_fn=sent.append, state_path=state_path)
    # A different strong entry is a distinct transition and re-alerts.
    oa.notify_confluence_flips(flip("NEUTRAL", "BEARISH_STRONG"), send_fn=sent.append, state_path=state_path)
    assert len(sent) == 2, "a different strong transition should re-alert"


def test_alert_line_names_the_oscillator(monkeypatch, tmp_path):
    sent: list[str] = []
    state_path = str(tmp_path / "alert_condition_state.json")
    aff = {"display_name": "Indicator Confluence", "contributing_oscillators": ["rsi", "macd"]}
    oa.notify_confluence_flips(
        [{"symbol": "AMD", "from": "NEUTRAL", "to": "BEARISH_STRONG",
          "transition": "NEUTRAL->BEARISH_STRONG", "oscillator_affiliation": aff}],
        send_fn=sent.append, state_path=state_path,
    )
    assert sent, "a flip should send"
    assert "INDICATOR CONFLUENCE" in sent[0]
    assert "AMD" in sent[0]
    assert "rsi" in sent[0] and "macd" in sent[0]


def test_daily_cap_bounds_the_firehose(monkeypatch, tmp_path):
    sent: list[str] = []
    state_path = str(tmp_path / "alert_condition_state.json")
    flips = [
        {"symbol": f"S{i}", "from": "NEUTRAL", "to": "BULLISH_STRONG",
         "transition": "NEUTRAL->BULLISH_STRONG", "oscillator_affiliation": {}}
        for i in range(10)
    ]
    r = oa.notify_confluence_flips(flips, send_fn=sent.append, state_path=state_path, max_per_day=3)
    assert len(sent) == 3
    assert len(r["suppressed"]) == 7


def test_condition_key_is_stable_per_symbol():
    assert oa.confluence_condition_key("NVDA") == "confluence:NVDA"
    assert oa.confluence_condition_key("nvda") != oa.confluence_condition_key("NVDA")
