"""Tests for system_health_agent YouTube transcripts freshness check."""
import importlib
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

sha = importlib.import_module("system_health_agent")


class _FakeCur:
    def __init__(self, latest, daily_count):
        self._latest = latest
        self._daily = daily_count
        self._n = 0

    def execute(self, sql, params=None):
        self._n += 1
        self._last = sql

    def fetchone(self):
        if "MAX(ingested_at)" in self._last:
            return (self._latest,)
        if "COUNT(*)" in self._last:
            return (self._daily,)
        return (None,)


class _FakeConn:
    def __init__(self, latest, daily_count):
        self._latest = latest
        self._daily = daily_count

    def cursor(self):
        return _FakeCur(self._latest, self._daily)


def test_youtube_freshness_current_from_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sha, "PROJECT_ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "youtube_ingest.log"
    log.write_text("ok\n")
    now = datetime.now(timezone.utc)
    latest = now - timedelta(hours=2)
    conn = _FakeConn(latest, 12)
    result = sha.check_youtube_transcript_freshness(conn, now=now, max_db_age_hours=36)
    assert result["status"] == "CURRENT"
    assert result["daily_ingested_count"] == 12
    assert result["latest_ingest_at"] is not None
    assert "latest_ingest" in result["reason"]


def test_youtube_freshness_stale_from_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sha, "PROJECT_ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "youtube_ingest.log").write_text("old\n")
    now = datetime.now(timezone.utc)
    latest = now - timedelta(hours=72)
    conn = _FakeConn(latest, 0)
    result = sha.check_youtube_transcript_freshness(conn, now=now, max_db_age_hours=36)
    assert result["status"] == "STALE"
    assert result["db_age_hours"] >= 36
    assert "threshold" in result["reason"]


def test_youtube_freshness_missing_no_log_no_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sha, "PROJECT_ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    # No log file; conn returns None latest
    conn = _FakeConn(None, 0)
    result = sha.check_youtube_transcript_freshness(conn, now=datetime.now(timezone.utc))
    assert result["status"] == "MISSING"
    assert "log_missing" in result["reason"] or "no youtube" in result["reason"].lower() \
        or result["latest_ingest_at"] is None


def test_youtube_freshness_log_only_current(tmp_path, monkeypatch):
    monkeypatch.setattr(sha, "PROJECT_ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "youtube_ingest.log").write_text("ingest ok\n")
    # No DB connection — fall back to log age
    result = sha.check_youtube_transcript_freshness(
        None, now=datetime.now(timezone.utc), max_db_age_hours=36)
    assert result["status"] == "CURRENT"
    assert "log fresh" in result["reason"]


def test_monitored_components_includes_youtube_ingest():
    names = {c["component"] for c in sha.MONITORED_COMPONENTS}
    assert "youtube_transcript_ingest" in names
    yt = next(c for c in sha.MONITORED_COMPONENTS if c["component"] == "youtube_transcript_ingest")
    assert yt["log_file"] == "youtube_ingest.log"
