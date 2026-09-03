"""Tests for aegis_transcript_discovery — DB preferred; Brave failure does not crash."""

import importlib
import sys
import os

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

atd = importlib.import_module("aegis_transcript_discovery")

from scripts.lib import brave_research_router as _R  # noqa: E402


class _StubRouter:
    """Stands in for the governed router.

    Deliberately a stub rather than the real module with a patched transport:
    the real ``search()`` writes metrics and cache under the **production**
    state root when called without ``root=``, and a unit test must never do
    that. The stub reuses the real enums so status handling is exercised for
    real.
    """

    Purpose = _R.Purpose
    Priority = _R.Priority
    Status = _R.Status
    ATTRIBUTION = _R.ATTRIBUTION

    def __init__(self, status=_R.Status.OK, results=None):
        self._status = status
        self._results = results or []
        self.calls = []

    def search(self, query, **kw):
        self.calls.append((query, kw))
        return _R.Outcome(
            status=self._status,
            results=list(self._results),
            reason="stub",
            query=query,
            purpose=str(kw.get("purpose", "")),
        )

    def record_adoption(self, *a, **k):
        pass


def test_db_preferred_before_brave(monkeypatch):
    """fetch_youtube_transcripts returns DB rows even when Brave would fail."""
    db_rows = [
        {
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
        }
    ]
    monkeypatch.setattr(
        atd, "fetch_db_youtube_transcripts", lambda symbols, max_per_symbol=2, lookback_days=14: list(db_rows)
    )
    # Brave is unreachable: the router reports TRANSPORT_ERROR rather than an
    # empty result, and the DB rows must still come through.
    stub = _StubRouter(status=_R.Status.TRANSPORT_ERROR)
    monkeypatch.setattr(atd, "_brave_router", lambda: stub)

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
    monkeypatch.setattr(atd, "fetch_db_youtube_transcripts", lambda *a, **k: [])
    stub = _StubRouter(status=_R.Status.TRANSPORT_ERROR)
    monkeypatch.setattr(atd, "_brave_router", lambda: stub)

    # Should return [] (no invented data), not raise
    discovery = atd.fetch_brave_discovery(["AAPL"], atd.PORTFOLIO_THEMES)
    assert discovery == []

    yt = atd.fetch_youtube_transcripts(["AAPL"], max_per_symbol=1)
    assert yt == []


def test_fetch_db_maps_real_rows_only(monkeypatch):
    """Empty title/summary/body rows are skipped — never invent."""
    monkeypatch.setattr(
        atd,
        "_db_query",
        lambda *a, **k: [
            {
                "video_id": "x",
                "title": "",
                "channel_name": "",
                "url": "",
                "summary": "",
                "transcript_text": "",
                "quality_score": 50,
                "strategy_tags": None,
                "ingested_at": None,
            },
            {
                "video_id": "realvid00001",
                "title": "V analysis",
                "channel_name": "Desk",
                "url": "https://www.youtube.com/watch?v=realvid00001",
                "summary": "Visa earnings",
                "transcript_text": "Visa beat estimates",
                "quality_score": 80,
                "strategy_tags": None,
                "ingested_at": None,
            },
        ],
    )
    rows = atd.fetch_db_youtube_transcripts(["V"], max_per_symbol=5)
    assert len(rows) == 1
    assert rows[0]["title"] == "V analysis"
    assert rows[0]["source_name"] == "youtube_transcripts_db"


def test_is_network_error():
    assert atd._is_network_error(OSError("Network is unreachable"))
    assert atd._is_network_error(requests.exceptions.ConnectionError("Failed to establish a new connection"))
    assert not atd._is_network_error(ValueError("bad json"))


def test_discovery_never_bypasses_the_router(monkeypatch):
    """No Brave traffic may leave this module except through the router."""
    src = open(os.path.join(PROJECT_ROOT, "scripts", "aegis_transcript_discovery.py")).read()
    assert "api.search.brave.com" not in src
    assert "X-Subscription-Token" not in src
    assert "BRAVE_SEARCH_API_KEY" not in src


def test_router_unavailable_denies_rather_than_falling_through(monkeypatch):
    """An unimportable router must DENY, never reach the provider directly."""
    monkeypatch.setattr(atd, "fetch_db_youtube_transcripts", lambda *a, **k: [])
    monkeypatch.setattr(atd, "_brave_router", lambda: None)
    monkeypatch.setenv("AEGIS_BRAVE_ENABLED", "1")
    assert atd.fetch_brave_discovery(["AAPL"], atd.PORTFOLIO_THEMES) == []
    assert atd.fetch_youtube_transcripts(["AAPL"], max_per_symbol=1) == []


def test_discovery_results_carry_search_discovery_attribution(monkeypatch):
    monkeypatch.setenv("AEGIS_BRAVE_ENABLED", "1")
    stub = _StubRouter(
        status=_R.Status.OK,
        results=[
            _R.Result(title="T", url="https://example.com/a", description="d", source_domain="example.com"),
        ],
    )
    monkeypatch.setattr(atd, "_brave_router", lambda: stub)
    recs = atd.fetch_brave_discovery(["AAPL"], [])
    assert recs, "stubbed router returned a result but discovery produced none"
    assert all(r.get("attribution") == "SEARCH_DISCOVERY" for r in recs)
