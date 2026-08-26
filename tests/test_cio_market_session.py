"""P0-8 — deterministic injectable NYSE session calendar (no network)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_market_session import (  # noqa: E402
    EXCHANGE,
    MARKET_SESSION_VERSION,
    NYSESessionService,
    STATE_CLOSED,
    STATE_POST,
    STATE_PRE,
    STATE_RTH,
    get_market_session,
    set_session_service,
)

ET = ZoneInfo("America/New_York")
REQUIRED = (
    "exchange", "session_date", "state",
    "official_open", "official_close", "early_close", "source",
)


def _assert_shape(sess: dict) -> None:
    for k in REQUIRED:
        assert k in sess, k
    assert sess["exchange"] == EXCHANGE
    assert sess["state"] in (STATE_PRE, STATE_RTH, STATE_POST, STATE_CLOSED)
    assert sess["source"] == MARKET_SESSION_VERSION


def test_labor_day_closed():
    noon = datetime(2026, 9, 7, 12, 0, tzinfo=ET)
    sess = get_market_session(noon)
    _assert_shape(sess)
    assert sess["session_date"] == "2026-09-07"
    assert sess["state"] == STATE_CLOSED
    assert sess["official_open"] is None
    assert sess["official_close"] is None
    assert sess["early_close"] is False


def test_thanksgiving_closed():
    noon = datetime(2026, 11, 26, 12, 0, tzinfo=ET)
    sess = get_market_session(noon)
    assert sess["state"] == STATE_CLOSED
    assert sess["session_date"] == "2026-11-26"
    # 2025 Thanksgiving is also closed
    sess25 = get_market_session(datetime(2025, 11, 27, 12, 0, tzinfo=ET))
    assert sess25["state"] == STATE_CLOSED


def test_day_after_thanksgiving_early_close():
    black_friday_rth = datetime(2026, 11, 27, 12, 0, tzinfo=ET)
    sess = get_market_session(black_friday_rth)
    assert sess["state"] == STATE_RTH
    assert sess["early_close"] is True
    assert sess["official_close"] is not None
    close = datetime.fromisoformat(sess["official_close"])
    assert close.astimezone(ET).hour == 13
    assert close.astimezone(ET).minute == 0

    after = get_market_session(datetime(2026, 11, 27, 14, 0, tzinfo=ET))
    assert after["state"] == STATE_POST
    assert after["early_close"] is True


def test_july_4_and_observed():
    # 2025-07-04 is Friday — full close
    s25 = get_market_session(datetime(2025, 7, 4, 12, 0, tzinfo=ET))
    assert s25["state"] == STATE_CLOSED
    assert s25["session_date"] == "2025-07-04"

    # 2026-07-04 is Saturday; observed Friday 2026-07-03
    s26_sat = get_market_session(datetime(2026, 7, 4, 12, 0, tzinfo=ET))
    assert s26_sat["state"] == STATE_CLOSED
    s26_obs = get_market_session(datetime(2026, 7, 3, 12, 0, tzinfo=ET))
    assert s26_obs["state"] == STATE_CLOSED
    assert s26_obs["session_date"] == "2026-07-03"

    # 2027-07-04 is Sunday; observed Monday 2027-07-05
    s27_obs = get_market_session(datetime(2027, 7, 5, 12, 0, tzinfo=ET))
    assert s27_obs["state"] == STATE_CLOSED
    assert s27_obs["session_date"] == "2027-07-05"


def test_dst_before_and_after_official_open_utc():
    # DST 2026 starts Sunday March 8. Friday Mar 6 is EST; Monday Mar 9 is EDT.
    winter = get_market_session(datetime(2026, 3, 6, 10, 0, tzinfo=ET))
    assert winter["state"] == STATE_RTH
    w_open = datetime.fromisoformat(winter["official_open"]).astimezone(ZoneInfo("UTC"))
    assert (w_open.hour, w_open.minute) == (14, 30)  # 09:30 EST = 14:30 UTC

    summer = get_market_session(datetime(2026, 3, 9, 10, 0, tzinfo=ET))
    assert summer["state"] == STATE_RTH
    s_open = datetime.fromisoformat(summer["official_open"]).astimezone(ZoneInfo("UTC"))
    assert (s_open.hour, s_open.minute) == (13, 30)  # 09:30 EDT = 13:30 UTC


def test_regular_summer_session():
    # Thursday 2026-07-02 — full session, EDT
    rth = get_market_session(datetime(2026, 7, 2, 10, 0, tzinfo=ET))
    assert rth["state"] == STATE_RTH
    assert rth["early_close"] is False
    open_et = datetime.fromisoformat(rth["official_open"]).astimezone(ET)
    close_et = datetime.fromisoformat(rth["official_close"]).astimezone(ET)
    assert (open_et.hour, open_et.minute) == (9, 30)
    assert (close_et.hour, close_et.minute) == (16, 0)

    pre = get_market_session(datetime(2026, 7, 2, 8, 0, tzinfo=ET))
    assert pre["state"] == STATE_PRE
    post = get_market_session(datetime(2026, 7, 2, 17, 0, tzinfo=ET))
    assert post["state"] == STATE_POST
    night = get_market_session(datetime(2026, 7, 2, 21, 0, tzinfo=ET))
    assert night["state"] == STATE_CLOSED


def test_regular_winter_session():
    # Thursday 2026-01-15 — full session, EST
    rth = get_market_session(datetime(2026, 1, 15, 10, 0, tzinfo=ET))
    assert rth["state"] == STATE_RTH
    assert rth["early_close"] is False
    open_utc = datetime.fromisoformat(rth["official_open"]).astimezone(ZoneInfo("UTC"))
    close_utc = datetime.fromisoformat(rth["official_close"]).astimezone(ZoneInfo("UTC"))
    assert (open_utc.hour, open_utc.minute) == (14, 30)
    assert (close_utc.hour, close_utc.minute) == (21, 0)

    weekend = get_market_session(datetime(2026, 1, 17, 10, 0, tzinfo=ET))
    assert weekend["state"] == STATE_CLOSED


def test_service_is_injectable():
    class _Fake(NYSESessionService):
        def session_at(self, now=None):
            return {
                "exchange": EXCHANGE,
                "session_date": "2099-01-01",
                "state": STATE_PRE,
                "official_open": None,
                "official_close": None,
                "early_close": False,
                "source": "injected",
            }

    fake = _Fake()
    try:
        set_session_service(fake)
        sess = get_market_session()
        assert sess["source"] == "injected"
        assert sess["state"] == STATE_PRE
        # Per-call injection does not require the default
        local = NYSESessionService()
        real = get_market_session(datetime(2026, 9, 7, 12, 0, tzinfo=ET), service=local)
        assert real["state"] == STATE_CLOSED
    finally:
        set_session_service(None)
