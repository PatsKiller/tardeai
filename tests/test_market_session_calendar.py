"""Computed NYSE calendar vs published holiday schedules (2025–2027).

Guards the algorithmic replacement of the hardcoded US_HOLIDAYS_2026 set, which was
missing Juneteenth and would have treated every 2027 holiday as a trading day.
"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_session import (
    current_market_session,
    is_trading_day,
    market_early_closes,
    market_holidays,
)

ET = ZoneInfo("America/New_York")


def test_2025_holidays_match_published_nyse_schedule():
    assert market_holidays(2025) == {
        "2025-01-01",  # New Year's Day (Wed)
        "2025-01-20",  # MLK
        "2025-02-17",  # Washington's Birthday
        "2025-04-18",  # Good Friday
        "2025-05-26",  # Memorial Day
        "2025-06-19",  # Juneteenth (Thu)
        "2025-07-04",  # Independence Day (Fri)
        "2025-09-01",  # Labor Day
        "2025-11-27",  # Thanksgiving
        "2025-12-25",  # Christmas (Thu)
    }


def test_2026_holidays_include_juneteenth_and_observed_july4():
    hols = market_holidays(2026)
    assert "2026-06-19" in hols, "Juneteenth was missing from the old hardcoded set"
    assert "2026-07-03" in hols, "July 4 2026 is a Saturday — observed Friday"
    assert "2026-07-04" not in hols
    # the rest of the old (correct) 2026 entries survive
    assert {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
            "2026-05-25", "2026-09-07", "2026-11-26", "2026-12-25"} <= hols
    assert len(hols) == 10


def test_2027_holidays_exist_no_year_cliff():
    hols = market_holidays(2027)
    assert "2027-01-01" in hols        # Friday
    assert "2027-07-05" in hols        # July 4 is a Sunday → observed Monday
    assert "2027-12-24" in hols        # Christmas is a Saturday → observed Friday
    assert "2027-06-18" in hols        # Juneteenth is a Saturday → observed Friday
    assert "2027-03-26" in hols        # Good Friday (Easter 2027-03-28)
    assert len(hols) == 10


def test_early_closes():
    assert market_early_closes(2025) == {"2025-07-03", "2025-11-28", "2025-12-24"}
    # 2026: July 3 is a FULL closure (observed holiday), not an early close;
    # Christmas Eve (Thu) and day-after-Thanksgiving remain.
    assert market_early_closes(2026) == {"2026-11-27", "2026-12-24"}
    # 2027: Dec 24 is the observed Christmas closure, so no Christmas Eve early close.
    assert market_early_closes(2027) == {"2027-11-26"}


def test_session_on_2026_07_03_is_holiday():
    noon = datetime(2026, 7, 3, 12, 0, tzinfo=ET)
    assert current_market_session(noon) == "holiday"
    assert not is_trading_day(noon)


def test_session_on_juneteenth_2026_is_holiday():
    noon = datetime(2026, 6, 19, 12, 0, tzinfo=ET)
    assert current_market_session(noon) == "holiday"


def test_early_close_session_windows():
    black_friday = datetime(2026, 11, 27, 12, 0, tzinfo=ET)
    assert current_market_session(black_friday) == "regular"
    after_early_close = datetime(2026, 11, 27, 14, 0, tzinfo=ET)
    assert current_market_session(after_early_close) == "afterhours"


def test_regular_trading_day():
    d = datetime(2026, 7, 2, 12, 0, tzinfo=ET)   # Thursday before the holiday
    assert current_market_session(d) == "regular"
    assert is_trading_day(d)
