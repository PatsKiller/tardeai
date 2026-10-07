"""Spent one-shots are not enabled-while-retired. A live recurring timer is."""
from __future__ import annotations

from scripts.lib.n8n_lane_host_conflict import (
    ALIGNED,
    CLASSIFIER_FALSE_POSITIVE_CLOSED,
    CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED,
    ENABLED_WHILE_DECLARED_NEVER_SCHEDULED,
    ENABLED_WHILE_DECLARED_RETIRED,
    classify_cron,
    classify_timer,
)


def test_spent_one_shots_are_not_a_retired_contradiction():
    for unit in ("at-observation-01.timer", "at-observation-01-closeout.timer"):
        assert unit
        result = classify_timer(
            declared_state="RETIRED",
            unit_file_state="enabled",
            sub_state="elapsed",
            next_elapse="",
            recurring=False,
        )
        assert result == CLASSIFIER_FALSE_POSITIVE_CLOSED


def test_a_recurring_enabled_timer_still_contradicts_never_scheduled():
    result = classify_timer(
        declared_state="NEVER_SCHEDULED",
        unit_file_state="enabled",
        sub_state="waiting",
        next_elapse="Wed 2026-10-07 19:30:00 EDT",
        recurring=True,
    )
    assert result == ENABLED_WHILE_DECLARED_NEVER_SCHEDULED


def test_a_recurring_enabled_timer_still_contradicts_retired():
    result = classify_timer(
        declared_state="RETIRED",
        unit_file_state="enabled",
        sub_state="waiting",
        next_elapse="Wed 2026-10-07 19:30:00 EDT",
        recurring=True,
    )
    assert result == ENABLED_WHILE_DECLARED_RETIRED


def test_an_active_recurring_timer_is_aligned():
    result = classify_timer(
        declared_state="ACTIVE",
        unit_file_state="enabled",
        sub_state="waiting",
        next_elapse="next",
        recurring=True,
    )
    assert result == ALIGNED


def test_maturity_cron_is_a_real_never_scheduled_conflict():
    assert (
        classify_cron(declared_state="NEVER_SCHEDULED", command_present=True)
        == CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED
    )
