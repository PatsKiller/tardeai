"""cio/pages and risk GETs are cached 60 s and single-flight (2026-11-07 CPU saturation)."""
import threading
import time

import scripts.api_v2 as api


def setup_function(_):
    api._SHARED_GET_CACHE.clear()


def test_concurrent_callers_share_one_build():
    calls = []

    def build():
        calls.append(1)
        time.sleep(0.2)
        return {"n": len(calls)}

    out = []
    ts = [threading.Thread(target=lambda: out.append(api._shared_get_cached("k", 60, build))) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1
    assert out == [{"n": 1}] * 5


def test_ttl_expiry_rebuilds_and_failure_not_cached(monkeypatch):
    calls = []

    def boom():
        calls.append("x")
        raise RuntimeError("db down")

    for _ in range(2):
        try:
            api._shared_get_cached("f", 60, boom)
        except RuntimeError:
            pass
    assert len(calls) == 2  # a failure is never served from cache

    api._shared_get_cached("t", 0.0, lambda: 1)
    assert api._shared_get_cached("t", 0.0, lambda: 2) == 2


def test_cio_pages_and_risk_routes_use_the_cache(monkeypatch):
    n = {"pages": 0, "risk": 0}

    import scripts.lib.w7_pages as w7

    def fake_pages(root, db_query=None):
        n["pages"] += 1
        return {"pages": n["pages"]}

    class R:
        def risk_payload(self, db_query=None):
            n["risk"] += 1
            return {"risk": n["risk"]}

    monkeypatch.setattr(w7, "page_payload", fake_pages)
    monkeypatch.setattr(api, "_cio_truth_readers", lambda: R())
    for _ in range(3):
        api._w7_cio_pages()
        api._risk_payload_cached()
    assert n == {"pages": 1, "risk": 1}
