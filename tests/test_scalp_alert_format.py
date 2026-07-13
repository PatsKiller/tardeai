"""Tests for scalp Telegram meta line formatting (country + source)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from scalp_alert_format import (  # noqa: E402
    format_scalp_meta_line,
    format_source_label,
    meta_line_from_ticker,
    resolve_source_fields,
)


def test_format_source_social_with_detail():
    assert "Social Reddit" in format_source_label("social", "Reddit")
    assert format_source_label("screener", "") == "📊 Finviz"


def test_format_meta_line_country_and_source():
    line = format_scalp_meta_line(
        source="screener",
        country="United States",
        symbol="EHGO",
    )
    assert "📊 Finviz" in line
    assert "🇺🇸" in line
    assert "United States" in line


def test_resolve_source_fields_social():
    src, detail = resolve_source_fields({
        "_source": "social",
        "source_lists": "reddit,stocktwits",
        "country": "USA",
        "symbol": "EHGO",
    })
    assert src == "social"
    assert "reddit" in detail.lower()


def test_meta_line_from_ticker_screener():
    line = meta_line_from_ticker({
        "symbol": "EHGO",
        "_source": "screener",
        "country": "United States",
    })
    assert "Finviz" in line
    assert "United States" in line