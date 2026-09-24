"""A winning plan and a blown plan must not share a sentence (operator, 2026-09-21).

Reported on HPE: entry $44.47, stop $40.28, target $63.32, price $61.95 — 92.7% of the
way to target — and the alert said "plan is stale — price is +39% from its entry".

The old branch was `abs(dist) > 25 -> "plan is stale"`. Because of `abs()`, price $28.00,
which is 31% THROUGH the stop, produced the same words. `target` and `stop` were already
in the plan dict and unused.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from notify_material_change import plan_levels  # noqa: E402

# Re-anchored 2026-09-24: the notice no longer writes a plan sentence (the maturity
# review moved it to one routed state per name), but the property this file protects
# is unchanged and now lives in plan_levels: a won plan and a blown plan are never
# read the same way, and direction comes from the plan's own geometry.

HPE = {"entry": 44.47, "stop": 40.28, "target": 63.32}
SHORT = {"entry": 50.0, "stop": 55.0, "target": 40.0}


def test_the_reported_hpe_case_is_neither_stopped_nor_done():
    lv = plan_levels(HPE, 61.95)
    assert not lv["hit_stop"] and not lv["hit_target"]
    assert round(lv["dist_pct"]) == 39


def test_a_won_plan_and_a_blown_plan_do_not_share_a_state():
    """The actual defect: abs() made +39% and -37% identical."""
    won, blown = plan_levels(HPE, 61.95), plan_levels(HPE, 28.00)
    assert blown["hit_stop"] and not won["hit_stop"]
    assert won["dist_pct"] > 0 > blown["dist_pct"]


def test_through_the_target_reads_as_reached():
    assert plan_levels(HPE, 64.00)["hit_target"]


def test_at_the_stop_counts_as_breached_not_merely_near():
    assert plan_levels(HPE, 40.28)["hit_stop"]


def test_below_entry_but_above_stop_is_neither():
    lv = plan_levels(HPE, 42.00)
    assert not lv["hit_stop"] and not lv["hit_target"] and lv["dist_pct"] < 0


def test_direction_comes_from_the_plan_not_an_assumption():
    """A short falling toward its target is working, not stopped."""
    assert not plan_levels(SHORT, 42.0)["hit_stop"]
    assert plan_levels(SHORT, 39.0)["hit_target"]
    assert plan_levels(SHORT, 56.0)["hit_stop"]


def test_no_plan_or_no_price_claims_nothing():
    for lv in (plan_levels(None, 10.0), plan_levels(HPE, None), plan_levels({"entry": 0}, 5.0)):
        assert not lv["hit_stop"] and not lv["hit_target"] and lv["dist_pct"] is None
