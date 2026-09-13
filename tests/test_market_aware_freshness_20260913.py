"""Freshness measured in market time, for sources that only move in market time.

EVIDENCE_GAP. Every CIO run was blocked at the evidence gate with a single
missing domain. Measured 2026-09-13T01:00Z, a Saturday:

    portfolio generated_at   2026-09-11 16:45 ET   (Friday's post-close reprice)
    age                      28.2 hours
    freshness threshold      43,200 s = 12 hours, wall clock
    -> STALE -> EVIDENCE_GAP -> every SCHEDULED_CIO_BRIEF run blocked

Five of the six required domains were AVAILABLE. The data was not broken:
Friday's close is the freshest portfolio state that can exist on a Saturday,
because nothing reprices a position while the exchange is shut. The threshold
was in the wrong units, so the CIO was structurally blocked every weekend and
every weeknight before the morning reprice.

The danger in fixing this is obvious -- it would be easy to write something that
just makes old data look young. These tests exist mostly to pin the cases where
it must STILL go stale.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.cio_market_aware_freshness import (
    is_stale,
    last_session_close,
    market_is_open,
)

ET = ZoneInfo("America/New_York")
THRESHOLD = 43200  # 12h, the real portfolio threshold
FRI_CLOSE_REPRICE = datetime(2026, 9, 11, 16, 45, 2, tzinfo=ET)  # the real stamp


def _stale(now, as_of=FRI_CLOSE_REPRICE, market_hours_only=True):
    return is_stale(as_of, now, THRESHOLD, market_hours_only=market_hours_only)


# ── the reported defect ───────────────────────────────────────────────────

def test_friday_close_is_not_stale_on_saturday():
    """NEGATIVE CONTROL: this is the exact live case that blocked every run."""
    assert _stale(datetime(2026, 9, 12, 21, 0, tzinfo=ET)) is False


def test_friday_close_is_not_stale_on_sunday():
    assert _stale(datetime(2026, 9, 13, 12, 0, tzinfo=ET)) is False


def test_friday_close_is_not_stale_monday_premarket():
    """Nothing has traded yet, so Friday's close is still authoritative."""
    assert _stale(datetime(2026, 9, 14, 9, 0, tzinfo=ET)) is False


# ── what must STILL go stale ──────────────────────────────────────────────

def test_goes_stale_once_the_market_opens():
    """The whole point. While the exchange is open the source should be
    updating, so age means what it says -- 66h of Friday data is stale."""
    assert _stale(datetime(2026, 9, 14, 11, 0, tzinfo=ET)) is True


def test_missing_a_session_reprice_still_goes_stale():
    """Data from BEFORE the last close is stale even while the market is shut.
    This is what stops the rule being a way to hide a missed producer run."""
    week_old = datetime(2026, 9, 4, 16, 45, tzinfo=ET)
    assert _stale(datetime(2026, 9, 12, 21, 0, tzinfo=ET), as_of=week_old) is True


def test_fresh_data_is_never_marked_stale():
    assert _stale(datetime(2026, 9, 11, 17, 0, tzinfo=ET)) is False


# ── the flag must be opt-in and inert by default ──────────────────────────

def test_without_the_flag_behaviour_is_unchanged():
    """Domains not marked market_hours_only must be bit-identical to before."""
    for now in (
        datetime(2026, 9, 12, 21, 0, tzinfo=ET),
        datetime(2026, 9, 13, 12, 0, tzinfo=ET),
        datetime(2026, 9, 14, 11, 0, tzinfo=ET),
    ):
        wall = (now - FRI_CLOSE_REPRICE).total_seconds() > THRESHOLD
        assert _stale(now, market_hours_only=False) is wall


@pytest.mark.parametrize("hours", [1, 6, 11])
def test_inside_threshold_is_never_stale_either_way(hours):
    now = datetime(2026, 9, 11, 16, 45, 2, tzinfo=ET).replace(
        hour=16 + (hours if 16 + hours < 24 else 0)
    )
    if now <= FRI_CLOSE_REPRICE:
        pytest.skip("clock arithmetic wrapped; covered by the explicit cases")
    assert _stale(now) is False
    assert _stale(now, market_hours_only=False) is False


# ── calendar helpers ──────────────────────────────────────────────────────

def test_last_session_close_skips_the_weekend():
    close = last_session_close(datetime(2026, 9, 13, 12, 0, tzinfo=ET))
    assert close is not None
    assert close.date() == datetime(2026, 9, 11, tzinfo=ET).date()


def test_market_open_only_during_regular_hours():
    assert market_is_open(datetime(2026, 9, 14, 11, 0, tzinfo=ET)) is True
    assert market_is_open(datetime(2026, 9, 14, 8, 0, tzinfo=ET)) is False
    assert market_is_open(datetime(2026, 9, 14, 18, 0, tzinfo=ET)) is False
    assert market_is_open(datetime(2026, 9, 12, 11, 0, tzinfo=ET)) is False


def test_registry_carries_the_flag_for_portfolio():
    from scripts.lib.cio_domain_registry import CIODomainRegistry

    r = CIODomainRegistry.load()
    assert r.get("portfolio").freshness_market_hours_only is True
    assert r.get("risk").freshness_market_hours_only is False, (
        "the flag is opt-in; unmarked domains keep wall-clock ageing"
    )
