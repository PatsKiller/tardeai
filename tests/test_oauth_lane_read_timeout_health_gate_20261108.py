"""OAUTH_LANE_READ_TIMEOUT_20261108 (LQ-20261107-978): one caller's read timeout must not silence a live lane.

Evidence, iris_run_log id 264 (2026-11-08T10:00:42-05, one weekly run)::

    "classify Social Security Post: CLOUD_GENERATION_FAILED_CLOSED: iris_taxonomy_agent:
     grok:ReadTimeout:HTTPConnectionPool(host='127.0.0.1', port=8645): Read timed out. (read timeout=30)"
    "classify Informed Investing: ... no governed cloud lane available"   (and five more)

The first item's 30 s budget expired two milliseconds after a keepalive ping on the SAME grok proxy
SUCCEEDED in 27.6 s (llm_consumption_log 10:00:04.040, duration 27639 ms). ``note_failure`` classified
the read timeout "unreachable", cooled grok for 60 s, and every later call in the run found no lane at
all (chatgpt is not authenticated). The proxy reported ``/health`` ready throughout — a read timeout is
the caller's deadline, not the lane's state.

The cooldown record itself is kept: a proxy that is really down fails the /health probe and still holds.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import oauth_lane_status as ols  # noqa: E402

# The exact error string iris_taxonomy_agent recorded (llm_consumption_log, 2026-11-08 10:00:04 ET).
IRIS_READ_TIMEOUT = ("HTTPConnectionPool(host='127.0.0.1', port=8645): "
                     "Read timed out. (read timeout=30)")


@pytest.fixture
def cdfile(tmp_path, monkeypatch):
    p = tmp_path / "cooldown.json"
    monkeypatch.setattr(ols, "_COOLDOWN_FILE", p)
    monkeypatch.setattr(ols, "_CACHE", {})
    return p


def _health(ready_map):
    return lambda lane, **k: {"lane": lane, "ready": bool(ready_map.get(lane))}


def test_read_timeout_does_not_hide_a_ready_lane(cdfile, monkeypatch):
    """FAIL before LQ-20261107-978: the timeout cooled grok, so the next caller saw no lane at all."""
    monkeypatch.setattr(ols, "lane_status", _health({"grok": True, "chatgpt": False}))
    monkeypatch.setattr(ols.time, "time", lambda: 1005.0)
    entry = ols.note_failure("grok", IRIS_READ_TIMEOUT, now=1000.0)
    assert entry["kind"] == "unreachable"  # the record is still honest…
    assert ols.cooldown_remaining("grok", now=1005.0) == 55.0
    assert ols.lane_available("grok") is True  # …but it no longer silences a live proxy
    assert ols.lanes_available() == {"grok": True, "chatgpt": False}


def test_down_proxy_still_holds_the_cooldown(cdfile, monkeypatch):
    """The override needs a READY /health: a proxy that stopped answering is still held out."""
    monkeypatch.setattr(ols, "lane_status", _health({"grok": False}))
    monkeypatch.setattr(ols.time, "time", lambda: 1005.0)
    ols.note_failure("grok", IRIS_READ_TIMEOUT, now=1000.0)
    assert ols.lane_available("grok") is False


def test_connection_refused_holds_even_if_health_stub_says_ready(cdfile, monkeypatch):
    """Only the readiness probe decides; the genuine-unreachable path is proven by test_down_proxy…"""
    monkeypatch.setattr(ols, "lane_status", _health({"grok": False}))
    monkeypatch.setattr(ols.time, "time", lambda: 1005.0)
    entry = ols.note_failure("grok", "Connection refused", now=1000.0)
    assert entry["kind"] == "unreachable"
    assert ols.lane_available("grok") is False


def test_rate_limit_cooldown_is_never_overridden(cdfile, monkeypatch):
    """LQ-20261107-236: /health reported ready through the whole chatgpt 429 streak — the cooldown exists
    precisely because a ready /health does not mean the lane can serve."""
    monkeypatch.setattr(ols, "lane_status", _health({"chatgpt": True}))
    monkeypatch.setattr(ols.time, "time", lambda: 1005.0)
    ols.note_failure("chatgpt", "429 Client Error: Too Many Requests for url", now=1000.0)
    assert ols.lane_available("chatgpt") is False


def test_no_cooldown_behaves_as_before(cdfile, monkeypatch):
    monkeypatch.setattr(ols, "lane_status", _health({"grok": True, "chatgpt": True}))
    assert ols.lanes_available() == {"grok": True, "chatgpt": True}


def test_expired_unreachable_cooldown_does_not_block(cdfile, monkeypatch):
    monkeypatch.setattr(ols, "lane_status", _health({"grok": True}))
    monkeypatch.setattr(ols.time, "time", lambda: 1200.0)
    ols.note_failure("grok", IRIS_READ_TIMEOUT, now=1000.0)
    assert ols.lane_available("grok") is True


def test_other_callers_keep_the_lane_after_one_cut(cdfile, monkeypatch):
    """The run's shape: one caller cut at its deadline, then six more asks — none may be refused."""
    health = {"grok": True, "chatgpt": False}
    monkeypatch.setattr(ols, "lane_status", _health(health))
    monkeypatch.setattr(ols.time, "time", lambda: 1000.0)
    ols.note_failure("grok", IRIS_READ_TIMEOUT, now=1000.0)
    assert [ols.lane_available("grok") for _ in range(6)] == [True] * 6
