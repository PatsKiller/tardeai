"""Dust, CASH, TEST and not-held names must never produce a fire or an S0.

Four subjects, each a real case from this book:

    SCHG   0.2294 shares  — dust residual, permanently ~100% below basis, so a
                            ratio branch fires forever unless dust is excluded
    SRNE   $0.90          — dust; a live open S1 existed on it
    CASH                  — not an entity a thesis can be about
    QCOM                  — not held at all

The 20-minute SRNE bug was the re-fire case: a detector that skips a subject
but does not record the skip will happily fire again on the next cycle.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.cio_graph_impact_held import build as graph_build
from scripts.lib.cio_s0_operator_loop import (
    REFUSE_CASH, REFUSE_DUST, mint_eligibility, route_turn,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
DUST = {"SCHG", "SRNE", "JEPI", "LDOS"}
HELD = {"SCHD", "V", "XLI", "ARKX", "SPCX", "BND", "NOC", "RTX"}


# ------------------------------------------------------------- S0 mint

@pytest.mark.parametrize("sym,reason", [
    ("SCHG", REFUSE_DUST), ("SRNE", REFUSE_DUST), ("CASH", REFUSE_CASH),
])
def test_dust_and_cash_refuse_s0_mint(sym, reason):
    assert mint_eligibility(sym, dust=DUST) == reason


def test_a_dust_question_refuses_rather_than_minting():
    r = route_turn("what about SCHG", plans=[], dust=DUST, now=NOW)
    assert r["action"] == "refuse"
    assert r["reason"] == REFUSE_DUST
    assert r["plan_id"] is None


def test_a_held_non_dust_name_still_mints():
    """The guard must not swallow legitimate subjects."""
    r = route_turn("what about RTX", plans=[], dust=DUST, now=NOW)
    assert r["action"] == "mint"
    assert r["symbol"] == "RTX"


def test_a_not_held_name_still_mints_an_s0_question():
    """QCOM is not held — asking about it is legitimate; firing S1/S6 is not."""
    r = route_turn("what about QCOM", plans=[], dust=DUST, now=NOW)
    assert r["action"] == "mint"


# ------------------------------------------------------- graph impact

def test_dust_cash_and_test_are_skipped_by_graph_with_a_reason():
    book = {"resolved_sector_contributors": {
        "Dividend": [{"symbol": "SCHD", "market_value": 351408}]}}
    r = graph_build(symbols=["SCHG", "SRNE", "CASH", "TEST1", "SCHD"],
                    holdings=book, held=HELD, dust=DUST)
    reasons = {s["symbol"]: s["skip_reason"] for s in r["skipped"]}
    assert reasons["SCHG"] == "dust_residual"
    assert reasons["SRNE"] == "dust_residual"
    assert reasons["CASH"] == "cash_or_non_entity"
    assert reasons["TEST1"] == "test_symbol"
    assert all(s["graph_impact"] is None for s in r["skipped"])


def test_a_not_held_name_is_skipped_by_graph_not_silently_empty():
    book = {"resolved_sector_contributors": {}}
    r = graph_build(symbols=["QCOM"], holdings=book, held=HELD, dust=DUST)
    assert r["skipped"][0]["skip_reason"] == "not_held"


# --------------------------------------------------- detector skip reasons

@pytest.mark.parametrize("sym,mv", [("SCHG", 8.09), ("SRNE", 0.90)])
def test_the_detector_records_a_dust_skip(sym, mv):
    """The re-fire bug: a skip that is not recorded happens again next cycle."""
    from scripts.lib.cio_situation_detector import _subject_skip_reason

    reason = _subject_skip_reason(sym, market_value=mv, market_value_known=True)
    assert reason == "dust_residual", f"{sym} at ${mv} must skip as dust"


def test_cash_is_skipped_by_the_detector():
    from scripts.lib.cio_situation_detector import _subject_skip_reason

    assert _subject_skip_reason(
        "CASH", market_value=630784.82, market_value_known=True) is not None


def test_a_cusip_is_skipped_as_not_a_ticker():
    from scripts.lib.cio_situation_detector import _subject_skip_reason

    assert _subject_skip_reason(
        "12507E201", market_value=100.0, market_value_known=True) == "not_a_ticker"


def test_a_real_holding_is_not_skipped():
    from scripts.lib.cio_situation_detector import _subject_skip_reason

    assert _subject_skip_reason(
        "SCHD", market_value=351408.81, market_value_known=True) is None


def test_unknown_market_value_is_held_never_dust():
    """dust_residual@v1: unknown MV is HELD, never dust — do not guess it away."""
    from scripts.lib.cio_situation_detector import _subject_skip_reason

    assert _subject_skip_reason(
        "XYZ", market_value=None, market_value_known=False) != "dust_residual"


# ------------------------------------------------------------- notify

def test_no_dust_fire_would_notify():
    from scripts.lib import cio_notification_policy as policy

    r = policy.decide({"plan_id": "p", "situation_type": "S1_POSITION_LIFECYCLE",
                       "symbols": ["SRNE"], "material": True}, now=NOW)
    assert r["would_send"] is False
