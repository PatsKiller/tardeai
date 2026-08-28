"""GTC protective-stop quote freshness — last close usable through pre-market."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brokers.quote_time import (  # noqa: E402
    CLOSED_MAX_AGE_SEC,
    AFTER_HOURS_MAX_AGE_SEC,
    FRESH_MAX_AGE_SEC,
    classify_session,
    current_session,
    fresh_max_age_for,
    is_fresh,
)


EDT = timezone(timedelta(hours=-4))


def test_premarket_window_is_18h_not_60m():
    assert fresh_max_age_for("pre_market") == CLOSED_MAX_AGE_SEC
    assert fresh_max_age_for("closed") == CLOSED_MAX_AGE_SEC
    assert fresh_max_age_for("after_hours") == AFTER_HOURS_MAX_AGE_SEC
    assert fresh_max_age_for("regular") == FRESH_MAX_AGE_SEC


def test_finviz_1645_close_fresh_at_0850_premarket():
    quote = "2026-08-27 16:45:02"
    now = datetime(2026, 8, 28, 8, 50, 0, tzinfo=EDT)
    assert classify_session(quote) == "after_hours"
    assert current_session(now) == "pre_market"
    assert is_fresh(quote, now=now) is True


def test_same_print_stale_once_rth_opens():
    quote = "2026-08-27 16:45:02"
    now = datetime(2026, 8, 28, 10, 0, 0, tzinfo=EDT)
    assert current_session(now) == "regular"
    assert is_fresh(quote, now=now) is False


def test_two_day_old_print_stale_even_in_premarket():
    quote = "2026-08-26 16:45:02"
    now = datetime(2026, 8, 28, 8, 50, 0, tzinfo=EDT)
    assert current_session(now) == "pre_market"
    assert is_fresh(quote, now=now) is False
