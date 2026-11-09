"""LQ-20261107-1643 — a Stage 2 price check is the recovery, not the confirmation.

Operator, 2026-11-09 (screenshot 13:15-13:25 ET): the re-entry card read **CONFIRMED** on four stopped-out names
while Stage 1 was 0 or 1 of 5, and they asked "buy now?". The engine's verdict rule put Stage 2 (any one price
check: a close above the 10/20-day average or above the exit) ahead of Stage 1, so a name that had merely traded
back over its exit price was labelled Confirmed with every setup condition still unmet. The operator chose
option 1: **CONFIRMED only after Stage 1 is complete**; otherwise the card says *Price recovered — waiting for
Stage 1 (n of 5)*.

Fail-before: ``verdict_for`` did not exist, and ``evaluate`` returned "Confirmed" for the shapes in
``test_a_price_check_over_an_incomplete_stage1_is_not_confirmed`` and
``test_quote_bars_above_the_exit_are_never_confirmed``. Pass-after: both read "Price recovered" and say how much
of Stage 1 is done; a name with all five Stage 1 conditions AND a price check is still "Confirmed", and
invalidation still outranks both.

Hermetic: synthetic bars only (no real symbols, prices or names); no DB, no network.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.market_risk import reentry_stages as rs  # noqa: E402

POLICY = {
    "reentry_watch": {
        "stage1": {"volume_ratio_min": 1.0, "volume_avg_sessions": 5, "group_rs_sessions": 3, "hedging_peak_sessions": 3,
                   "hedging_ease_pct": 10, "blocked_tiers": ["ORANGE", "RED"]},
        "stage2": {"confirm_ma_sessions": [10, 20], "confirm_above_exit": True},
        "short_history_anchor": "swing_low_vwap",
        "verdict": {"basing_min_sessions": 3, "basing_band_pct": 3.0, "invalidation_sessions": 10, "trend_sessions": 5},
    }
}


def _bars(rows, start=date(2026, 9, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(), "open": o, "high": h, "low": lo, "close": c, "volume": v}
            for i, (o, h, lo, c, v) in enumerate(rows)]


def _history(n=25, px=100.0):
    return [(px, px + 1, px - 1, px, 1000) for _ in range(n)]


# ── the rule, in one place ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "kwargs, expected",
    [
        # Stage 2 passes, Stage 1 does not: the defect the operator read as "buy now?".
        ({"invalidated": False, "stage1_met": 0, "stage1_of": 5, "stage2_met": True, "basing": False}, "Price recovered"),
        ({"invalidated": False, "stage1_met": 1, "stage1_of": 5, "stage2_met": True, "basing": False}, "Price recovered"),
        ({"invalidated": False, "stage1_met": 4, "stage1_of": 5, "stage2_met": True, "basing": False}, "Price recovered"),
        # Nothing to complete is not complete: an empty Stage 1 can never confirm.
        ({"invalidated": False, "stage1_met": 0, "stage1_of": 0, "stage2_met": True, "basing": False}, "Price recovered"),
        # Both stages: still Confirmed, unchanged.
        ({"invalidated": False, "stage1_met": 5, "stage1_of": 5, "stage2_met": True, "basing": False}, "Confirmed"),
        # Stage 1 without the price check: still Early setup.
        ({"invalidated": False, "stage1_met": 5, "stage1_of": 5, "stage2_met": False, "basing": False}, "Early setup"),
        ({"invalidated": False, "stage1_met": 1, "stage1_of": 5, "stage2_met": False, "basing": True}, "Basing"),
        ({"invalidated": False, "stage1_met": 1, "stage1_of": 5, "stage2_met": False, "basing": False}, "Still falling"),
        # Invalidation outranks every pass.
        ({"invalidated": True, "stage1_met": 5, "stage1_of": 5, "stage2_met": True, "basing": False}, "Invalidated"),
    ],
)
def test_the_verdict_rule(kwargs, expected):
    assert rs.verdict_for(**kwargs) == expected
    assert expected in rs.VERDICTS


# ── through evaluate() on the shape the operator saw ──────────────────────────────────────────────────────────

def test_a_price_check_over_an_incomplete_stage1_is_not_confirmed():
    """The live shape: a gap back over the exit price, no two-green-closes setup, no group/hedging history."""
    hist = _history(25)
    tail = [(95, 96, 90, 91, 1000),   # red: the exit day's follow-through never starts
            (91, 97, 90.5, 96.5, 1000)]  # one green close, back above the 95 exit
    bars = _bars(hist + tail)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["stage2"]["met"] is True, "the price check really did pass — that is what made it look confirmed"
    assert out["stage1"]["met"] < out["stage1"]["of"]
    assert out["stage1_complete"] is False
    assert out["verdict"] == "Price recovered", out["stage1"]


def test_all_five_conditions_plus_the_price_check_is_still_confirmed():
    hist = _history(25)
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89, 91, 89.5, 90.5, 1000),
            (90.6, 92.0, 90.4, 91.8, 1000), (91.9, 93.5, 91.7, 93.2, 1500),
            (93, 96, 92.5, 95.5, 2000)]      # still above the 88 swing low, now above the 95 exit
    bars = _bars(hist + tail)
    ratio = [1.0, 0.98, 0.96, 0.95, 0.955, 0.96, 0.97]
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=ratio,
                      hedging_series=[3.8, 3.9, 3.2], market_tier="YELLOW", policy=POLICY)
    assert out["stage1"]["met"] == 5, out["stage1"]
    assert out["stage2"]["met"] is True
    assert out["stage1_complete"] is True
    assert out["verdict"] == "Confirmed"


def test_quote_bars_above_the_exit_are_never_confirmed():
    """A quote-only name has no session open or volume: Stage 1 cannot be measured, so it cannot be complete."""
    closes = [80.0] * 19 + [96.0]                      # above sma10/sma20 and above the 95 exit
    bars = [{"date": (date(2026, 9, 1) + timedelta(days=i)).isoformat(), "close": c} for i, c in enumerate(closes)]
    out = rs.evaluate(symbol="AAA", exit_date=bars[18]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["stage2"]["met"] is True
    assert out["stage1_complete"] is False
    assert out["verdict"] == "Price recovered", out["stage1"]


def test_no_session_since_the_exit_reports_an_incomplete_stage1():
    out = rs.evaluate(symbol="AAA", exit_date="2099-01-01", exit_price=100.0, bars=_bars(_history(5)),
                      group_ratio=[], hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["verdict"] == "Still falling"
    assert out["stage1_complete"] is False


def test_the_confirmed_gate_is_a_status_only_field():
    """MBI_BEHAVIOR = 0: the new field is a boolean status, and the payload still carries no behaviour terms."""
    hist = _history(25)
    bars = _bars(hist + [(95, 96, 90, 91, 1000), (91, 97, 90.5, 96.5, 1000)])
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert isinstance(out["stage1_complete"], bool)
