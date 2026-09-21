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

from notify_material_change import _plan_state  # noqa: E402

HPE = {"entry": 44.47, "stop": 40.28, "target": 63.32}
SHORT = {"entry": 50.0, "stop": 55.0, "target": 40.0}


def test_the_reported_hpe_case_is_not_called_stale():
    line = _plan_state(HPE, 61.95)
    assert "stale" not in line.lower(), line
    assert "working" in line
    assert "93%" in line, line          # (61.95-44.47)/(63.32-44.47)
    assert "entry no longer available" in line, "the entry IS unreachable — say so too"


def test_a_won_plan_and_a_blown_plan_do_not_share_a_sentence():
    """The actual defect: abs() made +39% and -37% identical."""
    won = _plan_state(HPE, 61.95)
    blown = _plan_state(HPE, 28.00)
    assert won != blown
    assert "STOP BREACHED" in blown, blown
    assert "STOP BREACHED" not in won


def test_through_the_target_reads_as_reached():
    line = _plan_state(HPE, 64.00)
    assert "TARGET REACHED" in line and "63.32" in line, line


def test_at_the_stop_counts_as_breached_not_merely_near():
    assert "STOP BREACHED" in _plan_state(HPE, 40.28)


def test_below_entry_but_above_stop_is_neither_stale_nor_breached():
    line = _plan_state(HPE, 42.00)
    assert "below entry" in line and "above the stop" in line, line
    assert "STOP BREACHED" not in line


def test_direction_comes_from_the_plan_not_an_assumption():
    """A short falling toward its target is working, not '-16% and stale'."""
    line = _plan_state(SHORT, 42.0)
    assert "working" in line and "80%" in line, line
    assert "TARGET REACHED" in _plan_state(SHORT, 39.0)
    assert "STOP BREACHED" in _plan_state(SHORT, 56.0)


def test_without_a_target_it_says_only_what_it_knows():
    """Distance from entry is all there is — and it must not claim more."""
    line = _plan_state({"entry": 44.47, "stop": 40.28}, 61.95)
    assert "entry is stale" in line and "no target" in line, line
    assert "working" not in line


def test_a_small_move_is_still_reported_plainly():
    line = _plan_state(HPE, 45.50)
    assert "working" in line
    assert "entry no longer available" not in line, "only say that past the 25% bar"
