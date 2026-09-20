"""AI Analyst freshness SLA — weekday producer, weekend-safe bound."""

from __future__ import annotations

from datetime import datetime, timedelta

from scripts.lib.ai_analyst_freshness import (
    AI_ANALYST_STALE_AFTER_HOURS,
    ai_analyst_is_stale,
)


def test_sla_is_seventy_two_hours():
    assert AI_ANALYST_STALE_AFTER_HOURS == 72


def test_friday_cache_fresh_on_sunday_morning():
    # The defect: 48h marked Fri 07:15 stale by Sun 07:31 (~48.3h).
    gen = datetime(2026, 9, 18, 7, 15, 8)
    now = datetime(2026, 9, 20, 7, 31, 0)
    assert (now - gen) > timedelta(hours=48)
    assert (now - gen) < timedelta(hours=72)
    assert ai_analyst_is_stale(gen.isoformat(), now=now) is False


def test_friday_cache_stale_after_missed_monday():
    gen = datetime(2026, 9, 18, 7, 15, 8)
    now = datetime(2026, 9, 21, 9, 0, 0)  # Mon 09:00, past 72h
    assert ai_analyst_is_stale(gen.isoformat(), now=now) is True


def test_missing_generated_at_is_stale():
    assert ai_analyst_is_stale(None) is True
    assert ai_analyst_is_stale("") is True
