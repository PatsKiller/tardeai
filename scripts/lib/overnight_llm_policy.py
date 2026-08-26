"""US-overnight LLM policy.

Operator 2026-08-21: gemma overnight is not a judgment lane. US overnight
hours are deterministic jobs + ChatGPT OAuth if an LLM is required.

READ_ONLY_ADVISORY. No broker / order / stop / 2FA.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
# Inclusive 22:00, exclusive 06:00 America/New_York.
OVERNIGHT_START_HOUR = 22
OVERNIGHT_END_HOUR = 6
LANE_CHATGPT = "chatgpt"
LANE_NONE = "none"
LANE_LOCAL = "local"


def _as_et(dt: Optional[datetime] = None) -> datetime:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


def is_us_overnight(dt: Optional[datetime] = None) -> bool:
    hour = _as_et(dt).hour
    return hour >= OVERNIGHT_START_HOUR or hour < OVERNIGHT_END_HOUR


def _overnight_pref() -> str:
    return os.getenv("US_OVERNIGHT_LLM", "chatgpt").strip().lower()


def overnight_chatgpt_enabled() -> bool:
    """US overnight judgmental LLM uses ChatGPT OAuth, not gemma.

    Default ON (operator 2026-08-21).
    Rollback: US_OVERNIGHT_LLM=gemma|local (allow local) or off|none (skip LLM).
    """
    return _overnight_pref() not in {
        "0", "off", "false", "no", "gemma", "local", "none",
    }


def overnight_llm_lane(dt: Optional[datetime] = None) -> str:
    """Lane for judgmental LLM. Deterministic jobs ignore this."""
    if not is_us_overnight(dt):
        return LANE_LOCAL
    raw = _overnight_pref()
    if raw in {"gemma", "local"}:
        return LANE_LOCAL
    if raw in {"0", "off", "false", "no", "none"}:
        return LANE_NONE
    return LANE_CHATGPT
