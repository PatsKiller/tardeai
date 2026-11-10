"""Finviz news times are US Eastern wall-clock: the epoch must be the Eastern instant, in both DST regimes."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_news  # noqa: E402 -- path set above


def _ts(date_str: str) -> int:
    (art,) = finviz_news._parse_finviz_news_response(
        [{"date": date_str, "headline": "Synthetic Co beats", "url": "https://example.com/a"}], "SYN", 24)
    return art["datetime"]


def test_winter_time_is_utc_minus_5():
    assert _ts("Nov-10-26 09:00AM") == int(datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc).timestamp())


def test_summer_time_is_utc_minus_4():
    assert _ts("Jul-01-26 09:00AM") == int(datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc).timestamp())


def test_iso_export_format_is_eastern_too():
    assert _ts("2026-11-10 16:05:00") == int(datetime(2026, 11, 10, 21, 5, tzinfo=timezone.utc).timestamp())
