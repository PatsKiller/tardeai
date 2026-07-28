#!/usr/bin/env python3
"""Scalp session clock — premarket/regular/noon-cutoff windows, configurable active start, and the
per-setup FIRED-eligibility gate. Premarket and regular denominators never mix (market_session)."""
from __future__ import annotations

import sys
from datetime import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_session as ss  # noqa: E402

# default config (active_fire_start 07:00, cutoff 12:00)
DEFAULT = {"session": {"tz": "America/New_York", "regular_open": "09:30", "regular_close": "16:00",
                       "context_collection_start": "06:00", "active_fire_start": "07:00",
                       "active_fire_start_min": "06:00", "no_new_fire_after": "12:00"}}
# operator moves the active start to 06:00
EARLY = {"session": {**DEFAULT["session"], "active_fire_start": "06:00"}}


@pytest.mark.parametrize("hhmm,expected", [
    ((5, 59), ss.CLOSED), ((6, 0), ss.PREMARKET), ((7, 30), ss.PREMARKET), ((9, 29), ss.PREMARKET),
    ((9, 30), ss.REGULAR), ((11, 59), ss.REGULAR), ((12, 0), ss.POST_CUTOFF), ((15, 0), ss.POST_CUTOFF),
    ((16, 0), ss.CLOSED), ((20, 0), ss.CLOSED),
])
def test_phase(hhmm, expected):
    assert ss.phase(time(*hhmm), DEFAULT) == expected


@pytest.mark.parametrize("hhmm,expected", [
    ((5, 0), None), ((6, 30), ss.PREMARKET), ((9, 0), ss.PREMARKET),
    ((10, 0), ss.REGULAR), ((13, 0), ss.REGULAR), ((16, 30), None),
])
def test_market_session_never_mixes_denominators(hhmm, expected):
    assert ss.market_session(time(*hhmm), DEFAULT) == expected


def test_new_fire_allowed_default_window():
    assert not ss.new_fire_allowed(time(6, 30), DEFAULT)   # context-only under default
    assert ss.new_fire_allowed(time(7, 0), DEFAULT)        # active start
    assert ss.new_fire_allowed(time(9, 0), DEFAULT)
    assert ss.new_fire_allowed(time(11, 59), DEFAULT)
    assert not ss.new_fire_allowed(time(12, 0), DEFAULT)   # noon cutoff
    assert not ss.new_fire_allowed(time(15, 0), DEFAULT)


def test_new_fire_allowed_when_active_start_configured_to_0600():
    assert ss.new_fire_allowed(time(6, 30), EARLY)         # now allowed by config, no code change


def test_active_fire_start_cannot_precede_minimum():
    cfg = {"session": {**DEFAULT["session"], "active_fire_start": "05:00", "active_fire_start_min": "06:00"}}
    # clamps up to the minimum → 05:30 still not allowed
    assert not ss.new_fire_allowed(time(5, 30), cfg)
    assert ss.new_fire_allowed(time(6, 30), cfg)


# ── per-setup eligibility ──
ORB = {"supported_sessions": ["REGULAR"], "active_window_et": "09:45-10:30"}
PREMKT = {"supported_sessions": ["PREMARKET"], "active_window_et": "07:00-09:29"}


def test_orb_regular_window():
    assert ss.setup_eligible(ORB, time(10, 0), DEFAULT)[0]
    assert not ss.setup_eligible(ORB, time(9, 40), DEFAULT)[0]      # before its 09:45 window
    assert ss.setup_eligible(ORB, time(9, 40), DEFAULT)[1] == "OUTSIDE_SETUP_WINDOW"
    assert not ss.setup_eligible(ORB, time(10, 45), DEFAULT)[0]     # after 10:30
    ok, reason = ss.setup_eligible(ORB, time(12, 30), DEFAULT)      # after noon cutoff
    assert not ok and reason == "OUTSIDE_WINDOW_POST_NOON_CUTOFF"


def test_orb_rejects_premarket_session():
    ok, reason = ss.setup_eligible(ORB, time(8, 0), DEFAULT)
    assert not ok and reason == "SESSION_NOT_SUPPORTED_PREMARKET"


def test_premarket_setup_default_and_configured():
    assert ss.setup_eligible(PREMKT, time(7, 30), DEFAULT)[0]       # default active fire
    ok, reason = ss.setup_eligible(PREMKT, time(6, 30), DEFAULT)    # context-only under default
    assert not ok and reason == "OUTSIDE_WINDOW_BEFORE_ACTIVE_START"
    assert ss.setup_eligible(PREMKT, time(6, 30), EARLY)[0]         # fires when configured to 06:00
    # premarket setup cannot fire in the regular session
    ok2, reason2 = ss.setup_eligible(PREMKT, time(10, 0), DEFAULT)
    assert not ok2 and reason2 == "SESSION_NOT_SUPPORTED_REGULAR"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
