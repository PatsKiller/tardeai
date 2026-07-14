"""Tests for social awareness-only scanner rows."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from social_awareness import (  # noqa: E402
    awareness_fields,
    build_catalyst_text,
    enrich_awareness_market_fields,
    is_social_awareness_row,
    tag_social_awareness_row,
)


def test_is_social_awareness_detects_missing_market_data():
    row = {"symbol": "QTEX", "source": "social", "source_detail": "stocktwits_premarket", "price": 0, "rvol": 0}
    assert is_social_awareness_row(row)


def test_is_social_awareness_false_when_finviz_present():
    row = {"symbol": "EHGO", "source": "social", "price": 2.16, "rvol": 59.5}
    assert not is_social_awareness_row(row)


def test_tag_applies_catalyst_and_pill():
    row = {"symbol": "AVAV", "source": "premarket_social", "social_stocktwits": 2}
    tag_social_awareness_row(row, catalyst_fallback="AVAV headline from Yahoo")
    assert row["awareness_status"] == "SOCIAL_AWARENESS"
    assert "AVAV headline" in row["catalyst"]
    assert row["not_tradeable"] is True
    assert "SOCIAL AWARENESS" in row["operator_pill"]


def test_build_catalyst_prefers_news():
    assert build_catalyst_text(news_title="Breaking news", mention_count=3) == "Breaking news"


def test_enrich_awareness_fills_from_enrichment_cache():
    row = {
        "symbol": "MCRP",
        "awareness_status": "SOCIAL_AWARENESS",
        "source_detail": "stocktwits_premarket",
        "price": 0,
        "rvol": 0,
    }
    enrich_awareness_market_fields(
        [row],
        PROJECT_ROOT,
        fetch_live_quotes=False,
    )
    assert float(row.get("rvol") or 0) > 0
    assert row.get("sector")
    assert row.get("float_m")
    assert row.get("awareness_status") == "SOCIAL_AWARENESS"