"""LQ-20261107-219: /api/v2/jobs-health serves the last good body and refreshes in the background."""
import os
import threading
import time

import pytest

from scripts.lib import jobs_health as jh

REG = "registry.json"


def _result(tag):
    return {"rows": [{"lane_id": tag, "job": tag, "result": "failed", "market_hours_only": False, "scheduler": "cron"}],
            "tag": tag}


@pytest.fixture(autouse=True)
def _clean():
    jh._CACHE.clear()
    jh._REFRESHING.clear()
    yield
    jh._CACHE.clear()
    jh._REFRESHING.clear()


def _call(tmp_path):
    return jh.get_jobs_health({}, state_root=tmp_path, registry_path=tmp_path / REG)


def test_cold_computes_once_then_serves_fresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(jh, "_load", lambda *a: calls.append(1) or _result("a"))
    first = _call(tmp_path)
    second = _call(tmp_path)
    assert len(calls) == 1
    assert first["_swr"]["source"] == "computed" and second["_swr"]["source"] == "memory"
    assert second["_swr"]["stale"] is False


def test_stale_body_is_served_at_once_and_one_refresh_runs(tmp_path, monkeypatch):
    gate = threading.Event()
    calls = []

    def slow(*a):
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return _result("new" if len(calls) > 1 else "old")

    monkeypatch.setattr(jh, "_load", slow)
    _call(tmp_path)
    key = next(iter(jh._CACHE))
    t, res, as_of = jh._CACHE[key]
    jh._CACHE[key] = (t - 120, res, as_of)           # older than FRESH_S
    t0 = time.monotonic()
    a = _call(tmp_path)
    b = _call(tmp_path)
    assert time.monotonic() - t0 < 1.0                # nobody waited for the slow refresh
    assert a["tag"] == b["tag"] == "old"
    assert a["_swr"]["stale"] is True and a["_swr"]["refreshing"] is True
    assert len(calls) == 2                            # exactly one background refresh
    gate.set()
    for _ in range(50):
        if not jh._REFRESHING:
            break
        time.sleep(0.05)
    assert _call(tmp_path)["tag"] == "new"


def test_failed_refresh_keeps_last_good_body(tmp_path, monkeypatch):
    state = {"n": 0}

    def load(*a):
        state["n"] += 1
        if state["n"] > 1:
            raise RuntimeError("boom")
        return _result("good")

    monkeypatch.setattr(jh, "_load", load)
    _call(tmp_path)
    key = next(iter(jh._CACHE))
    t, res, as_of = jh._CACHE[key]
    jh._CACHE[key] = (t - 120, res, as_of)
    assert _call(tmp_path)["tag"] == "good"
    for _ in range(50):
        if not jh._REFRESHING:
            break
        time.sleep(0.05)
    assert _call(tmp_path)["tag"] == "good"


def test_restart_serves_the_disk_copy_without_computing_inline(tmp_path, monkeypatch):
    monkeypatch.setattr(jh, "_load", lambda *a: _result("disk"))
    _call(tmp_path)
    path = tmp_path / jh.LAST_GOOD_REL
    assert path.exists() and (path.stat().st_mode & 0o777) == 0o600
    jh._CACHE.clear()                                  # a restart
    gate = threading.Event()
    monkeypatch.setattr(jh, "_load", lambda *a: (gate.wait(5), _result("fresh"))[1])
    t0 = time.monotonic()
    body = _call(tmp_path)
    assert time.monotonic() - t0 < 1.0
    assert body["tag"] == "disk" and body["_swr"]["source"] == "disk"
    gate.set()
    for _ in range(50):
        if not jh._REFRESHING:
            break
        time.sleep(0.05)


def test_too_old_body_is_not_served(tmp_path, monkeypatch):
    monkeypatch.setattr(jh, "_load", lambda *a: _result("x"))
    _call(tmp_path)
    key = next(iter(jh._CACHE))
    t, res, as_of = jh._CACHE[key]
    jh._CACHE[key] = (t - jh.MAX_STALE_S - 10, res, as_of)
    monkeypatch.setattr(jh, "_load", lambda *a: _result("recomputed"))
    body = _call(tmp_path)
    assert body["tag"] == "recomputed" and body["_swr"]["source"] == "computed"


def test_explicit_now_bypasses_cache(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(jh, "_load", lambda *a: _result("t"))
    out = jh.get_jobs_health({}, state_root=tmp_path, registry_path=tmp_path / REG, now=datetime.now(timezone.utc))
    assert "_swr" not in out and not jh._CACHE
