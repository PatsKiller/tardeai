"""Tests for cio_youtube_research_queue — material-only Q>=70 filter."""
import importlib
import sys
import os
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

cq = importlib.import_module("cio_youtube_research_queue")


def _row(**kwargs):
    base = {
        "whiteboard_id": 1,
        "source_id": 100,
        "symbol": "SCHD",
        "wb_title": "Dividend ETF review",
        "wb_summary": "SCHD income outlook",
        "wb_quality": 80,
        "wb_status": "promoted",
        "wb_level": 3,
        "promoted_at": datetime.now(timezone.utc),
        "transcript_id": 100,
        "video_id": "abcdefghijk",
        "yt_title": "Dividend ETF review",
        "yt_summary": "SCHD income outlook",
        "yt_quality": 80,
        "strategy_tags": '["dividend_growth_compounder"]',
        "url": "https://www.youtube.com/watch?v=abcdefghijk",
        "channel_name": "Income Desk",
        "ingested_at": datetime.now(timezone.utc),
    }
    base.update(kwargs)
    return base


def test_filters_quality_below_70():
    rows = [
        _row(wb_quality=80, yt_quality=80, video_id="vidAAAAAAA1", source_id=1),
        _row(wb_quality=65, yt_quality=60, video_id="vidAAAAAAA2", source_id=2,
             whiteboard_id=2, transcript_id=2),
        _row(wb_quality=70, yt_quality=70, video_id="vidAAAAAAA3", source_id=3,
             whiteboard_id=3, transcript_id=3),
    ]
    items = cq.build_queue_items(rows, min_quality=70)
    assert all(i["quality_score"] >= 70 for i in items)
    assert len(items) == 2
    assert {i["video_id"] for i in items} == {"vidAAAAAAA1", "vidAAAAAAA3"}


def test_dedupes_by_video_id_and_source_id():
    rows = [
        _row(video_id="samevideoid1", source_id=10, whiteboard_id=1),
        _row(video_id="samevideoid1", source_id=11, whiteboard_id=2, transcript_id=11),
        _row(video_id="othervideoid", source_id=10, whiteboard_id=3, transcript_id=12),
    ]
    items = cq.build_queue_items(rows, min_quality=70)
    # First video_id wins; third row shares source_id=10 already seen → skipped
    assert len(items) == 1
    assert items[0]["video_id"] == "samevideoid1"


def test_queue_item_shape():
    items = cq.build_queue_items([_row()], min_quality=70)
    assert len(items) == 1
    it = items[0]
    for key in ("tickers_mentioned", "strategy_tags", "title", "summary",
                "quality_score", "asset_class", "url"):
        assert key in it
    assert it["quality_score"] >= 70
    assert it["url"].startswith("http")


def test_min_quality_constant():
    assert cq.MIN_QUALITY == 70
