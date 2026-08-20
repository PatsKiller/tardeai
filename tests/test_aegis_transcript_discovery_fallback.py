"""Tests for aegis_transcript_discovery — DB preferred; Brave failure does not crash."""
import importlib
import sys
import os

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

atd = importlib.import_module("aegis_transcript_discovery")


def test_db_preferred_before_brave(monkeypatch):
    """fetch_youtube_transcripts returns DB rows even when Brave would fail."""
    db_rows = [{
        "symbol": "SCHD",
        "source_family": "youtube",
        "source_name": "youtube_transcripts_db",
        "channel": "https://www.youtube.com/watch?v=dbvid123456",
        "title": "SCHD analysis",
        "summary": "dividend outlook",
        "stance": "neutral",
        "notable_themes": ["dividend"],
        "confidence": 0.55,
        "video_id": "dbvid123456",
        "quality_score": 72,
    }]
    monkeypatch.setattr(atd, "fetch_db_youtube_transcripts",
                        lambda symbols, max_per_symbol=2, lookback_days=14: list(db_rows))
    monkeypatch.setattr(atd, "BRAVE_KEY", "fake-key")

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("Network is unreachable")

    monkeypatch.setattr(atd.requests, "get", boom)

    # Pretend transcript API is importable so Brave path is attempted
    import types
    fake_mod = types.ModuleType("youtube_transcript_api")
    class FakeAPI:
        @staticmethod
        def get_transcript(*a, **k):
            return []
    fake_mod.YouTubeTranscriptApi = FakeAPI
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)

    records = atd.fetch_youtube_transcripts(["SCHD", "VTI"], max_per_symbol=1)
    assert len(records) >= 1
    assert records[0]["source_name"] == "youtube_transcripts_db"
    assert records[0]["title"] == "SCHD analysis"


def test_brave_network_failure_does_not_crash(monkeypatch):
    monkeypatch.setattr(atd, "fetch_db_youtube_transcripts",
                        lambda *a, **k: [])
    monkeypatch.setattr(atd, "BRAVE_KEY", "fake-key")

    def boom(*a, **k):
        raise OSError("Network is unreachable")

    monkeypatch.setattr(atd.requests, "get", boom)

    # Should return [] (no invented data), not raise
    discovery = atd.fetch_brave_discovery(["AAPL"], atd.PORTFOLIO_THEMES)
    assert discovery == []

    yt = atd.fetch_youtube_transcripts(["AAPL"], max_per_symbol=1)
    assert yt == []


def test_fetch_db_maps_real_rows_only(monkeypatch):
    """Empty title/summary/body rows are skipped — never invent."""
    monkeypatch.setattr(atd, "_db_query", lambda *a, **k: [{
        "video_id": "x", "title": "", "channel_name": "", "url": "",
        "summary": "", "transcript_text": "", "quality_score": 50,
        "strategy_tags": None, "ingested_at": None,
    }, {
        "video_id": "realvid00001", "title": "V analysis", "channel_name": "Desk",
        "url": "https://www.youtube.com/watch?v=realvid00001",
        "summary": "Visa earnings", "transcript_text": "Visa beat estimates",
        "quality_score": 80, "strategy_tags": None, "ingested_at": None,
    }])
    rows = atd.fetch_db_youtube_transcripts(["V"], max_per_symbol=5)
    assert len(rows) == 1
    assert rows[0]["title"] == "V analysis"
    assert rows[0]["source_name"] == "youtube_transcripts_db"


def test_is_network_error():
    assert atd._is_network_error(OSError("Network is unreachable"))
    assert atd._is_network_error(requests.exceptions.ConnectionError("Failed to establish a new connection"))
    assert not atd._is_network_error(ValueError("bad json"))
