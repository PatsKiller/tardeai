"""The two DST P0s: session labels must not assume a fixed UTC offset (2026-11-02).

DST ended 2026-11-01. Two live paths hardcoded a summer offset / summer UTC hours and were wrong all
winter:

* ``lib.canonical_observation.market_session`` built its label from ``at + timedelta(hours=-4)``. It is
  not advisory-only — ``options_desk_quote_refresh`` refreshes quotes only when it returns ``REGULAR`` —
  so under EST it refreshed an hour early and stopped an hour early, losing the 15:00-16:00 ET hour of
  the real session.
* ``proposal_quote_trust.classify_quote_trust`` compared raw UTC hour bands (13-21 UTC as "open"). Under
  EST that labelled 09:00-09:30 ET ``regular_hours`` with ``trading_now=True`` and 15:00-16:00 ET
  ``extended_hours``.

Both tests assert the SAME label in a winter and a summer instant, so neither can pass by accident in
one season.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

from scripts.lib import canonical_observation as CO
from scripts.proposal_quote_trust import classify_quote_trust

NY = ZoneInfo("America/New_York")
WINTER = datetime(2026, 11, 2)   # EST, UTC-05:00
SUMMER = datetime(2026, 7, 2)    # EDT, UTC-04:00


def _at(day, hour, minute):
    return day.replace(hour=hour, minute=minute, tzinfo=NY)


# ── P0-1: canonical_observation.market_session ─────────────────────────────────────────────────────


@pytest.mark.parametrize("day", [WINTER, SUMMER], ids=["EST", "EDT"])
@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (3, 30, "CLOSED"),
        (8, 30, "PRE_MARKET"),
        (9, 45, "REGULAR"),
        (15, 30, "REGULAR"),   # the regression: EST used to say AFTER_HOURS here
        (16, 30, "AFTER_HOURS"),
        (19, 0, "AFTER_HOURS"),
        (20, 30, "CLOSED"),
    ],
)
def test_market_session_is_dst_correct(day, hour, minute, expected):
    assert CO.market_session(_at(day, hour, minute)) == expected


def test_market_session_last_hour_of_the_session_is_regular_in_both_seasons():
    """15:00-16:00 ET is regular hours; the fixed -04:00 shift called it AFTER_HOURS all winter."""
    for day in (WINTER, SUMMER):
        assert CO.market_session(_at(day, 15, 30)) == "REGULAR"
        assert CO.market_session(_at(day, 15, 59)) == "REGULAR"


def test_market_session_accepts_a_naive_value_as_utc():
    """The module's stamps are UTC; a naive value must not be read as local ET."""
    naive = _at(WINTER, 15, 30).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    assert CO.market_session(naive) == "REGULAR"


def test_market_session_labels_the_weekend():
    saturday = datetime(2026, 11, 7, 12, 0, tzinfo=NY)
    assert CO.market_session(saturday) == "WEEKEND"


# ── P0-2: proposal_quote_trust session bands ───────────────────────────────────────────────────────


@pytest.mark.parametrize("day", [WINTER, SUMMER], ids=["EST", "EDT"])
@pytest.mark.parametrize(
    "hour,minute,session,trading",
    [
        (3, 30, "closed", False),
        (8, 0, "closed", False),
        (9, 0, "extended_hours", True),
        (9, 25, "extended_hours", True),   # the DST regression: EST used to say regular_hours
        (9, 35, "regular_hours", True),
        (15, 30, "regular_hours", True),   # the DST regression: EST used to say extended_hours
        (16, 30, "extended_hours", True),
        (19, 0, "closed", False),
        (20, 30, "closed", False),
    ],
)
def test_quote_trust_session_bands_are_dst_correct(day, hour, minute, session, trading):
    out = classify_quote_trust({}, now=_at(day, hour, minute))
    assert out["market_session"] == session
    assert out["trading_now"] is trading


def test_quote_trust_weekend_is_never_trading():
    saturday = datetime(2026, 11, 7, 12, 0, tzinfo=NY)
    out = classify_quote_trust({}, now=saturday)
    assert out["market_session"] == "weekend"
    assert out["trading_now"] is False


def test_quote_trust_refuses_a_naive_now():
    """A naive value is ambiguous: canonical_observation reads it as UTC, this would read it as ET."""
    with pytest.raises(ValueError, match="timezone-aware"):
        classify_quote_trust({}, now=datetime(2026, 11, 2, 15, 30))


@pytest.mark.parametrize("day", [WINTER, SUMMER], ids=["EST", "EDT"])
@pytest.mark.parametrize(
    "hour,minute,second,session,trading",
    [
        (9, 29, 59, "extended_hours", True),
        (9, 30, 0, "regular_hours", True),
        (15, 59, 59, "regular_hours", True),
        (16, 0, 0, "extended_hours", True),
        (16, 59, 59, "extended_hours", True),
        (17, 0, 0, "closed", False),
    ],
)
def test_quote_trust_exact_boundaries(day, hour, minute, second, session, trading):
    at = _at(day, hour, minute).replace(second=second)
    out = classify_quote_trust({}, now=at)
    assert out["market_session"] == session
    assert out["trading_now"] is trading


def test_quote_trust_does_not_widen_the_trading_window():
    """The pre-DST window was 09:00-17:00 ET. 08:00 and 18:00 must stay closed (review F3)."""
    for hour in (8, 18):
        out = classify_quote_trust({}, now=_at(WINTER, hour, 0))
        assert out["market_session"] == "closed", f"{hour}:00 ET must not report trading"
        assert out["trading_now"] is False


# ── F7: the REAL gate, not just the coarse label ───────────────────────────────────────────────────


def test_desk_session_gate_is_calendar_and_dst_aware():
    """Quote refresh gates on desk_session -> is_rth, which overrides the coarse label."""
    from scripts.lib.desk_session import market_session as gate

    assert gate(_at(WINTER, 15, 30)) == "REGULAR", "15:30 EST is RTH; the coarse -04:00 label said AFTER_HOURS"
    assert gate(_at(WINTER, 8, 30)) == "PRE_MARKET"
    assert gate(datetime(2026, 11, 26, 11, 0, tzinfo=NY)) == "CLOSED", "Thanksgiving"
    assert gate(datetime(2026, 11, 27, 14, 0, tzinfo=NY)) == "CLOSED", "NYSE early close 13:00 ET"


def test_the_coarse_label_has_no_calendar_and_that_is_documented():
    """KNOWN LIMITATION, asserted so adding a calendar is a deliberate change and not a surprise.

    The coarse label reports REGULAR on a holiday morning; only ``is_rth`` (via desk_session) knows
    the NYSE calendar. Callers that gate live work must use is_rth.
    """
    assert CO.market_session(datetime(2026, 11, 26, 11, 0, tzinfo=NY)) == "REGULAR"
