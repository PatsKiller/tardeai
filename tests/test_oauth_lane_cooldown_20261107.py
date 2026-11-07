"""OAUTH_LANE_COOLDOWN_20261107 (LQ-20261107-236): cooldown after 429 / timeout on the OAuth proxies."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import oauth_lane_status as ols  # noqa: E402


@pytest.fixture
def cdfile(tmp_path, monkeypatch):
    p = tmp_path / "cooldown.json"
    monkeypatch.setattr(ols, "_COOLDOWN_FILE", p)
    return p


def test_classify_failure():
    assert ols.classify_failure("429 Client Error: Too Many Requests for url") == "rate_limited"
    assert ols.classify_failure("HTTPConnectionPool: Read timed out. (read timeout=40)") == "unreachable"
    assert ols.classify_failure("Max retries exceeded with url") == "unreachable"
    assert ols.classify_failure("AUTH_EXPIRED: session ended") is None
    assert ols.classify_failure("INPUT_LIMIT_EXCEEDED") is None
    assert ols.classify_failure(None) is None


def test_rate_limit_starts_cooldown_and_blocks_availability(cdfile, monkeypatch):
    monkeypatch.setattr(ols, "lane_status", lambda lane, **k: {"ready": True})
    assert ols.lane_available("chatgpt") is True
    entry = ols.note_failure("chatgpt", "429 Too Many Requests", now=1000.0)
    assert entry["kind"] == "rate_limited" and entry["until"] == 1120.0
    assert ols.cooldown_remaining("chatgpt", now=1050.0) == 70.0
    monkeypatch.setattr(ols.time, "time", lambda: 1050.0)
    assert ols.lane_available("chatgpt") is False
    assert ols.lane_available("grok") is True  # other lane untouched
    monkeypatch.setattr(ols.time, "time", lambda: 1121.0)
    assert ols.lane_available("chatgpt") is True


def test_repeated_failures_back_off_and_cap(cdfile):
    waits = []
    t = 1000.0
    for _ in range(8):
        e = ols.note_failure("grok", "Read timed out", now=t)
        waits.append(e["until"] - t)
        t = e["until"] - 1.0  # fail again just before it would have expired
    assert waits[0] == 60.0 and waits[1] == 120.0 and waits[2] == 240.0 and waits[3] == 480.0
    assert max(waits) <= ols.COOLDOWN_MAX_S


def test_success_clears_and_other_errors_ignored(cdfile):
    assert ols.note_failure("grok", "AUTH_EXPIRED", now=1.0) is None
    assert ols.note_failure("deepseek-flash", "429", now=1.0) is None
    ols.note_failure("grok", "429", now=1.0)
    assert ols.cooldown_remaining("grok", now=2.0) > 0
    ols.note_success("grok")
    assert ols.cooldown_remaining("grok", now=2.0) == 0.0


def test_unreadable_file_means_no_cooldown(cdfile):
    cdfile.write_text("{not json")
    assert ols.cooldown_remaining("grok", now=5.0) == 0.0


def test_gate_records_failure_and_success(cdfile, monkeypatch):
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lib" / "llm_consumption.py").read_text()
    assert "note_failure as _lane_note_failure" in src
    assert "note_success as _lane_note_success" in src
