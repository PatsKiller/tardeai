"""US overnight: ChatGPT OAuth, not gemma."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.overnight_llm_policy import (
    LANE_CHATGPT,
    LANE_LOCAL,
    LANE_NONE,
    is_us_overnight,
    overnight_llm_lane,
)

ET = ZoneInfo("America/New_York")


def test_us_overnight_hours():
    assert is_us_overnight(datetime(2026, 8, 21, 22, 0, tzinfo=ET)) is True
    assert is_us_overnight(datetime(2026, 8, 21, 2, 0, tzinfo=ET)) is True
    assert is_us_overnight(datetime(2026, 8, 21, 6, 0, tzinfo=ET)) is False
    assert is_us_overnight(datetime(2026, 8, 21, 14, 0, tzinfo=ET)) is False


def test_overnight_lane_is_chatgpt(monkeypatch):
    monkeypatch.delenv("US_OVERNIGHT_LLM", raising=False)
    night = datetime(2026, 8, 21, 23, 0, tzinfo=ET)
    assert overnight_llm_lane(night) == LANE_CHATGPT
    day = datetime(2026, 8, 21, 14, 0, tzinfo=ET)
    assert overnight_llm_lane(day) == LANE_LOCAL


def test_rollback_to_gemma(monkeypatch):
    monkeypatch.setenv("US_OVERNIGHT_LLM", "gemma")
    night = datetime(2026, 8, 21, 23, 0, tzinfo=ET)
    assert overnight_llm_lane(night) == LANE_LOCAL


def test_off_skips_judgmental_llm(monkeypatch):
    monkeypatch.setenv("US_OVERNIGHT_LLM", "off")
    night = datetime(2026, 8, 21, 23, 0, tzinfo=ET)
    assert overnight_llm_lane(night) == LANE_NONE
