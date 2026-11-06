"""Re-entry honesty (PKG-SELLOFF-INTEL-20261106 B). Synthetic symbols and bars only.

ANCHOR: REENTRY_HONESTY_20261106

1. An exit with no completed session after it is "Pending next close", never "Still falling".
2. Every evaluated verdict carries ``verdict_basis``, the rule that decided it, so "Confirmed" (Stage 2, any one
   price check) beside "2 of 5" (Stage 1) reads as two rules, not a contradiction.
3. The new verdict never pages: it is outside STAGE_CARD_VERDICTS, and a later move from it pages exactly like a
   move from "Still falling".
"""
from __future__ import annotations

from datetime import date, timedelta

from scripts.lib.market_risk import reentry_stages as rs
from scripts.lib.market_risk import reentry_watch as rw

POLICY = {"reentry_watch": {"stage2": {"confirm_ma_sessions": [10, 20], "confirm_above_exit": True}}}


def _bars(closes, start=date(2026, 10, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c,
             "volume": 1000} for i, c in enumerate(closes)]


def _eval(bars, exit_date, exit_price=100.0, tier="YELLOW"):
    return rs.evaluate(symbol="ZZQ", exit_date=exit_date, exit_price=exit_price, bars=bars, group_ratio=[],
                       hedging_series=[], market_tier=tier, policy=POLICY)


def test_exit_after_the_last_close_is_pending():
    bars = _bars([100.0] * 25)
    out = _eval(bars, exit_date="2026-12-31")
    assert out["verdict"] == "Pending next close"
    assert out["stage1"] == {"met": 0, "of": 0, "conditions": []}
    assert "pending" in out["verdict_basis"]


def test_exit_on_the_last_close_is_pending():
    # The exit-day bar closed on the exit itself: it is not a session SINCE the exit.
    bars = _bars([100.0] * 25)
    out = _eval(bars, exit_date=bars[-1]["date"])
    assert out["verdict"] == "Pending next close", out


def test_one_session_after_the_exit_is_evaluated():
    bars = _bars([100.0] * 24 + [90.0, 89.0])
    out = _eval(bars, exit_date=bars[-2]["date"], exit_price=95.0)
    assert out["verdict"] != "Pending next close"
    assert out["stage1"]["of"] == 5


def test_confirmed_names_the_price_check_and_the_stage1_count():
    # Falls after the exit, then closes above the exit price: Stage 2 passes while Stage 1 does not (tier ORANGE).
    bars = _bars([100.0] * 24 + [96.0, 94.0, 101.0])
    out = _eval(bars, exit_date=bars[23]["date"], exit_price=100.0, tier="ORANGE")
    assert out["verdict"] == "Confirmed", out
    basis = out["verdict_basis"]
    assert basis.startswith("confirmed by price:")
    assert "close above 100.00" in basis
    assert f"Stage 1 is {out['stage1']['met']} of 5" in basis
    assert out["stage1"]["met"] < 5  # the case the lead flagged: Confirmed while Stage 1 is not complete


def test_still_falling_basis_carries_the_count():
    bars = _bars([100.0] * 24 + [96.0, 94.0, 92.0])
    out = _eval(bars, exit_date=bars[23]["date"], exit_price=100.0, tier="ORANGE")
    assert out["verdict"] == "Still falling", out
    assert out["verdict_basis"] == f"still falling: no price confirmation, Stage 1 {out['stage1']['met']} of 5"


def test_pending_is_a_known_verdict_that_never_pages():
    assert "Pending next close" in rs.VERDICTS
    assert "Pending next close" not in rw.STAGE_CARD_VERDICTS


def _doc(verdict):
    return {"_stages_contract": rw.STAGES_CONTRACT,
            "ZZQ": {"symbol": "ZZQ", "exit_date": "2026-11-06", "as_of": "2026-11-09", "status": "RE_ENTER_IF",
                    "stages": {"verdict": verdict}}}


def test_moving_into_pending_sends_no_card():
    assert rw.stage_cards(_doc("Pending next close"), _doc("Still falling"), {"reentry_watch": {}}) == []


def test_moving_out_of_pending_pages_like_still_falling():
    from_pending = rw.stage_cards(_doc("Confirmed"), _doc("Pending next close"), {"reentry_watch": {}})
    from_falling = rw.stage_cards(_doc("Confirmed"), _doc("Still falling"), {"reentry_watch": {}})
    assert len(from_pending) == len(from_falling) == 1
    assert "was Pending next close" in from_pending[0]["text"]


def test_basis_text_passes_the_card_guard():
    bars = _bars([100.0] * 24 + [96.0, 94.0, 101.0])
    out = _eval(bars, exit_date=bars[23]["date"], exit_price=100.0, tier="ORANGE")
    rw._guard(out["verdict_basis"])  # no order, size or stop wording
