"""A1/A2 trigger rules — the replay the spec's acceptance asks for, as fixtures.

Synthetic numbers only: this proves ordering and arithmetic, and makes no claim about a live quote, a live stop or
what the operator's account holds.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import critical_text_triggers as t  # noqa: E402


# ── A1: extended-hours price at or near a stop that cannot fire until 9:30 ────────────────────────────────

def test_a1_fires_when_the_extended_hours_price_reaches_the_stop():
    ev = t.extended_hours_near_stop("SPCX", "Roth", 131.20, 130.00, date_key="2026-11-04")
    assert ev is not None and ev["alert_class"] == t.A1
    assert ev["suggested_limit"] == 130.90            # 0.25 % under the print, above the stop
    assert ev["distance_pct"] == 0.92
    assert "inactive till 9:30" in ev["trigger"]


def test_a1_fires_below_the_stop_too():
    ev = t.extended_hours_near_stop("SPCX", "Roth", 129.00, 130.00, date_key="2026-11-04")
    assert ev is not None and ev["distance_pct"] < 0


def test_a1_stays_quiet_when_the_price_is_far_above_the_stop():
    assert t.extended_hours_near_stop("SPCX", "Roth", 140.00, 130.00) is None       # 7.7 % away, outside 2 %


def test_a1_uses_the_configurable_band():
    assert t.extended_hours_near_stop("SPCX", None, 140.00, 130.00, within_pct=10.0) is not None


def test_a1_does_not_re_text_on_the_same_price_or_a_small_dip():
    first = t.extended_hours_near_stop("SPCX", None, 131.20, 130.00, date_key="d")
    assert first is not None
    same = t.extended_hours_near_stop("SPCX", None, 131.10, 130.00, last_texted_price=131.20, date_key="d")
    assert same is None                                            # only 0.08 % lower, step is 1 %
    deeper = t.extended_hours_near_stop("SPCX", None, 129.50, 130.00, last_texted_price=131.20, date_key="d")
    assert deeper is not None                                      # 1.3 % lower: a new step


def test_a1_refuses_placeholder_and_non_finite_numbers():
    for bad in (None, "", "—", "N/A", float("nan"), float("inf"), True):
        assert t.extended_hours_near_stop("SPCX", None, bad, 130.00) is None
        assert t.extended_hours_near_stop("SPCX", None, 131.20, bad) is None
    assert t.extended_hours_near_stop("", None, 131.20, 130.00) is None   # no symbol, no text


# ── A2: a big move left the stop below the policy's own recommendation ───────────────────────────────────

def test_a2_fires_on_a_one_day_move_with_the_stop_left_behind():
    ev = t.stop_not_raised("SPCX", "Roth", 120.00, 132.00, move_1d_pct=12.0, shares=100, price=140.00,
                           date_key="2026-11-04")
    assert ev is not None and ev["alert_class"] == t.A2
    assert ev["recommended_stop"] == 132.00 and ev["live_stop"] == 120.00
    assert ev["gain_at_risk_usd"] == 2000.00                       # (140 − 120) × 100
    assert "Raise stop to 132.00" == ev["action"]


def test_a2_fires_on_a_five_day_move():
    assert t.stop_not_raised("SPCX", None, 120.00, 132.00, move_1d_pct=2.0, move_5d_pct=16.0) is not None


def test_a2_fires_when_there_is_no_stop_at_all():
    ev = t.stop_not_raised("SPCX", None, None, 132.00, move_1d_pct=12.0)
    assert ev is not None and ev["live_stop"] is None and "missing" in ev["trigger"]


def test_a2_stays_quiet_when_the_stop_is_already_close_enough():
    assert t.stop_not_raised("SPCX", None, 131.00, 132.00, move_1d_pct=12.0) is None      # within 2 %
    assert t.stop_not_raised("SPCX", None, 140.00, 132.00, move_1d_pct=12.0) is None      # above it


def test_a2_stays_quiet_without_a_qualifying_move():
    assert t.stop_not_raised("SPCX", None, 120.00, 132.00, move_1d_pct=5.0, move_5d_pct=9.0) is None


def test_a2_refuses_placeholder_numbers():
    assert t.stop_not_raised("SPCX", None, 120.00, "—", move_1d_pct=12.0) is None
    assert t.stop_not_raised("SPCX", None, 120.00, 132.00, move_1d_pct=float("nan")) is None
    assert t.stop_not_raised("", None, 120.00, 132.00, move_1d_pct=12.0) is None


# ── the replay fixtures the acceptance names (synthetic, not a claim about the live account) ─────────────

def test_replay_the_10_30_selloff_would_have_texted_before_the_stop():
    """A held name sells off through the day: at 131.20 the A1 rule fires while the stop still cannot."""
    fired = []
    for stamp, price in (("09:35", 150.0), ("15:40", 138.0), ("15:55", 133.1), ("16:05", 131.2)):
        ev = t.extended_hours_near_stop("SPCX", "Roth", price, 130.00, date_key="2026-10-30")
        if ev:
            fired.append((stamp, ev["suggested_limit"]))
    assert fired and fired[0][0] == "16:05"            # the first print inside the 2 % band
    assert fired[0][1] == 130.90


def test_replay_the_spcx_card_produces_the_specified_sentence_shape():
    ev = t.extended_hours_near_stop("SPCX", "Roth", 131.20, 130.00, date_key="2026-11-04")
    from scripts.lib.critical_texts import format_text
    text = format_text(ev)
    assert text.startswith("ACT NOW SPCX (Roth) ext-hrs 131.20, stop 130.00 inactive till 9:30.")
    assert text.endswith("CC Risk") and len(text) <= 160


# ── CX3 (whole-head review of d7d9c5004, 2026-11-05): the account is part of the identity ─────────────

def test_a1_identity_includes_the_account_at_the_same_price():
    """Two accounts at the same symbol/date/price used to share one id, so the second text was suppressed."""
    account_a = t.extended_hours_near_stop("SPCX", "Account A", 131.20, 130.00, date_key="2026-11-04")
    account_b = t.extended_hours_near_stop("SPCX", "Account B", 131.20, 130.00, date_key="2026-11-04")
    assert account_a["event_id"] != account_b["event_id"]
    # One account, one scope: spacing/case differences are the same account, not a second alert.
    same_account = t.extended_hours_near_stop("SPCX", "  account a ", 131.20, 130.00, date_key="2026-11-04")
    assert same_account["event_id"] == account_a["event_id"]


def test_a2_identity_includes_the_account():
    account_a = t.stop_not_raised("SPCX", "Account A", 120.00, 132.00, move_1d_pct=12.0, date_key="2026-11-04")
    account_b = t.stop_not_raised("SPCX", "Account B", 120.00, 132.00, move_1d_pct=12.0, date_key="2026-11-04")
    assert account_a["event_id"] != account_b["event_id"]


def test_an_unscoped_identity_cannot_collide_with_a_named_account():
    unscoped = t.extended_hours_near_stop("SPCX", None, 131.20, 130.00, date_key="2026-11-04")
    scoped = t.extended_hours_near_stop("SPCX", "all", 131.20, 130.00, date_key="2026-11-04")
    assert unscoped["event_id"] != scoped["event_id"]


ANCHOR = 'CRITICAL_TEXTS_20261104'  # config/ci_gates/critical_texts_20261104.json names this file
