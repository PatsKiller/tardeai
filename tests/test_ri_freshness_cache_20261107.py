"""LQ-20261107-218: freshness_report serves a last-good copy and refreshes it in the background. Synthetic only."""
import threading

import pytest

from scripts.lib import research_intelligence as ri


@pytest.fixture(autouse=True)
def _reset():
    ri._FRESHNESS_CACHE.update(fn=None, ts=0.0, data=None, refreshing=False)
    yield
    ri._FRESHNESS_CACHE.update(fn=None, ts=0.0, data=None, refreshing=False)


def _stub(monkeypatch, calls, gate=None):
    def compute(*, db_query):
        calls.append(1)
        if gate is not None:
            gate.wait(5)
        return {"ok": True, "n": len(calls)}

    monkeypatch.setattr(ri, "_freshness_report_compute", compute)


def _q(sql):  # distinct reader callable
    return []


def test_second_call_is_served_from_cache(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    a = ri.freshness_report(db_query=_q)
    b = ri.freshness_report(db_query=_q)
    assert len(calls) == 1 and a["n"] == b["n"] == 1
    assert b["_cache"]["stale"] is False


def test_stale_copy_served_at_once_and_refreshed_once(monkeypatch):
    calls = []
    gate = threading.Event()
    _stub(monkeypatch, calls)
    ri.freshness_report(db_query=_q)
    ri._FRESHNESS_CACHE["ts"] -= ri._FRESHNESS_TTL_S + 5
    gate_calls = []
    release = threading.Event()

    def slow(*, db_query):
        gate_calls.append(1)
        release.wait(5)
        return {"ok": True, "n": 99}

    monkeypatch.setattr(ri, "_freshness_report_compute", slow)
    r1 = ri.freshness_report(db_query=_q)
    r2 = ri.freshness_report(db_query=_q)
    assert r1["n"] == 1 and r1["_cache"]["stale"] is True and r2["n"] == 1  # last good, no wait
    release.set()
    for t in threading.enumerate():
        if t.name == "ri-freshness-refresh":
            t.join(5)
    assert len(gate_calls) == 1  # one refresh, not one per request
    assert ri.freshness_report(db_query=_q)["n"] == 99
    gate.set()


def test_failed_refresh_keeps_last_good(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    ri.freshness_report(db_query=_q)
    ri._FRESHNESS_CACHE["ts"] -= ri._FRESHNESS_TTL_S + 5

    def boom(*, db_query):
        raise RuntimeError("db down")

    monkeypatch.setattr(ri, "_freshness_report_compute", boom)
    ri.freshness_report(db_query=_q)
    for t in threading.enumerate():
        if t.name == "ri-freshness-refresh":
            t.join(5)
    assert ri.freshness_report(db_query=_q)["n"] == 1
    assert ri._FRESHNESS_CACHE["refreshing"] is False


def test_error_result_is_not_cached(monkeypatch):
    monkeypatch.setattr(ri, "_freshness_report_compute", lambda *, db_query: {"ok": False, "error": "x"})
    assert ri.freshness_report(db_query=_q)["ok"] is False
    assert ri._FRESHNESS_CACHE["data"] is None


def test_other_reader_does_not_see_cached_data(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    ri.freshness_report(db_query=_q)
    ri.freshness_report(db_query=lambda sql: [])
    assert len(calls) == 2


def test_use_cache_false_always_computes(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    ri.freshness_report(db_query=_q)
    ri.freshness_report(db_query=_q, use_cache=False)
    assert len(calls) == 2
