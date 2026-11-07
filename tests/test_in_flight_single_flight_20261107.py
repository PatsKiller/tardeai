"""LQ-20261107-308: /api/v2/ops/in-flight never runs gh on the request path; concurrent callers share one build."""
import threading
import time

import pytest

from scripts.lib import deploy_in_flight as dif


def _payload(tag):
    return {"schema": dif.SCHEMA, "prs": [], "count": 0, "status": "OK", "freshness": "OK", "reason": None, "tag": tag}


@pytest.fixture(autouse=True)
def _clean():
    dif.clear_cache()
    yield
    dif.clear_cache()


def _get():
    return dif.handle(dif.ROUTE, "GET", {}, None)[1]["data"]


def test_concurrent_cold_requests_share_one_build(monkeypatch):
    calls = []

    def slow(_db):
        calls.append(1)
        time.sleep(0.4)
        return _payload("x")
    monkeypatch.setattr(dif, "build", slow)
    out = []
    ts = [threading.Thread(target=lambda: out.append(_get())) for _ in range(3)]
    t0 = time.monotonic()
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1
    assert all(o["tag"] == "x" for o in out)
    print("3 parallel cold calls took %.2fs, builds=%d" % (time.monotonic() - t0, len(calls)))


def test_stale_is_served_instantly_while_refresh_runs(monkeypatch):
    monkeypatch.setattr(dif, "build", lambda _d: _payload("old"))
    _get()
    time.sleep(0.05)
    dif._CACHE[dif.ROUTE] = (time.monotonic() - 120, dif._CACHE[dif.ROUTE][1])
    gate = threading.Event()

    def slow(_d):
        gate.wait(5)
        return _payload("new")
    monkeypatch.setattr(dif, "build", slow)
    t0 = time.monotonic()
    d = _get()
    elapsed = time.monotonic() - t0
    assert d["tag"] == "old" and d["cache"] == "STALE_REFRESHING"
    assert elapsed < 0.2, elapsed
    gate.set()
    for _ in range(50):
        if _get()["tag"] == "new":
            break
        time.sleep(0.05)
    assert _get()["tag"] == "new"
    print("stale served in %.4fs while a 5s build ran in the background" % elapsed)


def test_failed_refresh_keeps_last_good_marked_stale(monkeypatch):
    monkeypatch.setattr(dif, "build", lambda _d: _payload("good"))
    _get()
    dif._CACHE[dif.ROUTE] = (time.monotonic() - 120, dif._CACHE[dif.ROUTE][1])

    def boom(_d):
        raise RuntimeError("gh 504")
    monkeypatch.setattr(dif, "build", boom)
    _get()
    for _ in range(50):
        d = _get()
        if d.get("freshness") == "STALE":
            break
        time.sleep(0.05)
    assert d["tag"] == "good" and d["freshness"] == "STALE" and "gh 504" in d["refresh_error"]


def test_cold_timeout_answers_warming_not_empty(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(dif, "COLD_WAIT_S", 0.1)
    monkeypatch.setattr(dif, "build", lambda _d: (gate.wait(5), _payload("late"))[1])
    d = _get()
    assert d["freshness"] == "UNAVAILABLE" and d["prs"] is None and d["cache"] == "WARMING"
    gate.set()
