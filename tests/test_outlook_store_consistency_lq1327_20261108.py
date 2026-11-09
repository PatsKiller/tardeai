"""LQ-20261107-1327 — the outlook/plan inputs must agree with the stores, and absence must never become a value.

Synthetic numbers only; the live 2026-11-06 figures are quoted in the comments so the boundary cases are
recognisable. Nothing here reads a store, a network or a model.

ANCHOR: OUTLOOK_STORE_CONSISTENCY_LQ1327_20261108
"""
from __future__ import annotations

from scripts.lib.market_risk.reentry_watch import _guard
from scripts.lib.market_risk.sectors import classify_state
from scripts.monday_plan_brief import _reentry_line

# The shipped defaults. The policy file may override any key; these tests pin the rule, not the file.
CFG: dict = {}


# ── (e) a group in a deep drawdown with an extreme 5-session move is at least WEAK ─────────────────────────────


def test_energy_on_11_06_is_at_least_weak() -> None:
    """Energy 2026-11-06: -12.0% off its 20-session high, z5 -3.88, rs20 +0.24.

    The old rule required ``rs20 <= 0``, so a group that had merely matched SPY over a month could fall 12% and
    still read NEUTRAL — the exact row the operator asked about.
    """
    assert (
        classify_state(
            dd20=-12.0, rs20=0.24, z5=-3.88, zrs=-2.43, z1=-1.0, zrs1=-1.0,
            b5=-2.7, b1=-1.0, r5=-12.0, r1=-1.0, cfg=CFG,
        )
        == "WEAK"
    )


def test_a_deep_drawdown_alone_is_not_weak() -> None:
    """A 12% drawdown with an ordinary 5-session move is not an outlier; the old rule may still read it."""
    assert (
        classify_state(
            dd20=-12.0, rs20=1.0, z5=-1.0, zrs=0.0, z1=-0.5, zrs1=0.0,
            b5=1.0, b1=0.1, r5=-3.0, r1=0.0, cfg=CFG,
        )
        == "NEUTRAL"
    )


def test_an_extreme_z_without_the_drawdown_is_not_weak() -> None:
    """One bad day's z-score never marks a group weak — the price gate still has to hold (staples 10-23)."""
    assert (
        classify_state(
            dd20=-2.0, rs20=-0.4, z5=-3.9, zrs=-1.0, z1=-2.5, zrs1=-1.0,
            b5=-0.5, b1=-0.2, r5=-2.0, r1=-0.3, cfg=CFG,
        )
        == "NEUTRAL"
    )


def test_a_flat_defensive_group_stays_neutral() -> None:
    assert (
        classify_state(
            dd20=-0.5, rs20=0.3, z5=-3.95, zrs=-0.2, z1=-1.0, zrs1=0.0,
            b5=0.5, b1=0.1, r5=0.4, r1=0.0, cfg=CFG,
        )
        == "NEUTRAL"
    )


def test_the_stress_path_is_unchanged() -> None:
    """Technology 2026-11-06: dd20 -16.1, rs20 -11.57, z5 -2.18, zrs -2.17 -> STRESS, as before."""
    assert (
        classify_state(
            dd20=-16.1, rs20=-11.57, z5=-2.18, zrs=-2.17, z1=-1.4, zrs1=-1.0,
            b5=-2.7, b1=-1.0, r5=-8.23, r1=-2.0, cfg=CFG,
        )
        == "STRESS"
    )


def test_the_price_weak_weak_path_is_unchanged() -> None:
    assert (
        classify_state(
            dd20=-5.0, rs20=-2.0, z5=-2.0, zrs=-0.5, z1=-1.0, zrs1=0.0,
            b5=-1.0, b1=0.0, r5=-3.0, r1=0.0, cfg=CFG,
        )
        == "WEAK"
    )


def test_the_resilient_path_is_unchanged() -> None:
    """Benchmark down, group up: the resilient branch still answers when the price gate does not."""
    assert (
        classify_state(
            dd20=-1.0, rs20=4.0, z5=1.0, zrs=1.5, z1=1.0, zrs1=1.5,
            b5=-2.0, b1=-0.5, r5=1.0, r1=0.2, cfg=CFG,
        )
        == "RESILIENT"
    )


# ── (b) a per-account exit says where the shares are still held ────────────────────────────────────────────────


def _rec(**extra) -> dict:
    rec: dict = {"as_of": "2026-11-08T21:00:00Z", "conditions": [], "status": "RE_ENTER_IF"}
    rec.update(extra)
    return rec


def test_a_partial_exit_says_where_the_shares_are_still_held() -> None:
    """V on 2026-11-06: sold at 413 in the rollover IRA, still held in one other account."""
    text = "\n".join(
        _reentry_line("V", _rec(exit_date="2026-11-06", exit_account_type="ira", exit_account_scope="acct-7cc14b8e",
                                held_elsewhere=["acct-edc14ec3"]))
    )
    assert "partial exit, not flat" in text
    assert "sold in the IRA account on 2026-11-06" in text
    assert "still held in 1 other account (acct-edc14ec3)" in text


def test_a_flat_exit_claims_no_holdings() -> None:
    text = "\n".join(_reentry_line("DAIC", _rec(exit_date="2026-10-12", exit_account_type="ira", held_elsewhere=[])))
    assert "partial exit" not in text
    assert "still held" not in text


def test_an_unrecorded_exit_date_is_said_not_guessed() -> None:
    text = "\n".join(_reentry_line("V", _rec(exit_account_type="", held_elsewhere=["acct-1"])))
    assert "sold in the account on an unrecorded session" in text


def test_the_reentry_line_still_passes_the_behaviour_guard() -> None:
    """MBI_BEHAVIOR = 0: the added line names no order, size or stop."""
    _guard(
        "\n".join(
            _reentry_line("V", _rec(exit_date="2026-11-06", exit_account_type="ira",
                                    held_elsewhere=["acct-edc14ec3", "acct-7cc14b8e"]))
        )
    )


def test_every_held_account_is_named() -> None:
    text = "\n".join(
        _reentry_line("V", _rec(exit_account_type="ira", held_elsewhere=["acct-a", "acct-b"]))
    )
    assert "still held in 2 other accounts (acct-a, acct-b)" in text
