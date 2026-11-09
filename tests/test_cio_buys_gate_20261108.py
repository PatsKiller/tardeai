"""LQ-20261107-1311: the CIO synopsis states the buy gate (synthetic calendar, no real data)."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.cio_buys_gate import buys_block, first_gating_event  # noqa: E402

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
