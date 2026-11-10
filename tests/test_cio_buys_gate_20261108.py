"""LQ-20261107-1311: the CIO synopsis states the buy gate (synthetic calendar, no real data)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.cio_buys_gate import buys_block, event_passed, first_gating_event  # noqa: E402

ET = ZoneInfo("America/New_York")
SUN = datetime(2031, 3, 9, 20, 0, tzinfo=ET)
MACRO = [
    {"date": "2031-03-13", "event": "Unemployment Insurance Weekly Claims", "time_et": "08:30"},
    {"date": "2031-03-11", "event": "Consumer Price Index", "time_et": "08:30"},
    {"date": "2031-03-14", "event": "Producer Price Index", "time_et": "08:30"},
]


def test_red_names_first_cpi():
    b = buys_block("RED", MACRO, SUN)
    assert b["gate"] == "NONE" and b["until"] == "CPI Tue 03-11 08:30 ET"
    assert b["line"].startswith("No new buys before CPI Tue 03-11")


def test_claims_do_not_gate():
    assert first_gating_event(MACRO[:1], SUN.date()) is None


def test_yellow_green_unknown():
    assert buys_block("YELLOW", MACRO, SUN)["gate"] == "SMALL_ONLY"
    assert buys_block("GREEN", [], SUN)["line"] == "Buys open, slowly"
    assert buys_block(None, MACRO, SUN)["gate"] == "UNKNOWN"


def test_past_or_far_events_ignored():
    far = [{"date": "2031-03-30", "event": "Consumer Price Index", "time_et": "08:30"}]
    assert buys_block("RED", far, SUN)["line"] == "No new buys while the tier is RED; protect gains with stops"


# LQ-20261107-1784 (grok-a/-9 review r3, minor C): the properties ``event_passed`` promises, pinned.
def test_event_passed_needs_a_timezone_and_places_a_utc_now_on_the_et_clock():
    naive = datetime(2031, 3, 11, 8, 31)
    assert event_passed("2031-03-11", "08:30", naive) is False, "a naive now cannot be placed on the clock"
    assert event_passed("2031-03-11", "08:30", None) is False
    assert event_passed("2031-03-11", "08:30", datetime(2031, 3, 11, 12, 35, tzinfo=timezone.utc)) is True  # 08:35 ET
    assert event_passed("2031-03-11", "08:30", datetime(2031, 3, 11, 12, 29, tzinfo=timezone.utc)) is False  # 08:29 ET


def test_a_date_only_row_is_passed_only_when_the_whole_day_is_behind():
    today_late = datetime(2031, 3, 11, 23, 59, tzinfo=ET)
    next_morning = datetime(2031, 3, 12, 0, 1, tzinfo=ET)
    assert event_passed("2031-03-11", None, today_late) is False
    assert event_passed("2031-03-11", "", today_late) is False
    assert event_passed("2031-03-11", None, next_morning) is True
