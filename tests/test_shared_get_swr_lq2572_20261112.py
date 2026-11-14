"""LQ-20261107-2572: a waiter never blocks on an in-flight build; last-good served with age; one build."""
import threading
import time
import types

import pytest

from scripts.lib import shared_get_swr as swr


@pytest.fixture
def operator_identity(monkeypatch):
    """LQ-20261114-3156: /cio/asks/tracked is an operator read and now refuses a non-operator BEFORE starting a build.
    These SWR tests are about the cache mechanism, so they ask as the operator the route is for."""
    try:
        from lib import cc_auth as auth  # the module ``_default_ctx`` resolves when scripts/ is on sys.path
    except ImportError:  # pragma: no cover
        import scripts.lib.cc_auth as auth
    monkeypatch.setattr(auth, "load_config",
                        lambda path=None: types.SimpleNamespace(allowed_logins=frozenset({"john@example.com"})))
    auth.set_request_principal("tailnet:john@example.com")
    auth.set_request_context("serve_proxy", {})
    yield
    auth.set_request_principal(None)
    auth.set_request_context(None, None)


@pytest.fixture(autouse=True)
def _clean():
    swr.clear()
    yield
    deadline = time.time() + 5
    while swr.inflight() and time.time() < deadline:
        time.sleep(0.02)
    swr.clear()


def _slow(calls, gate, result=None):
    def build():
        calls.append(1)
        gate.wait(10)
        return result if result is not None else {"n": len(calls)}
    return build


def _hammer(n, fn):
    """n concurrent waiters; returns (results, max seconds any waiter took)."""
    out, took = [], []
    start = threading.Barrier(n)

    def w():
        start.wait()
        t0 = time.monotonic()
        out.append(fn())
        took.append(time.monotonic() - t0)

    ts = [threading.Thread(target=w) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    return out, max(took)


def test_cold_waiters_get_unknown_building_fast_and_one_build():
    calls, gate = [], threading.Event()
    before = threading.active_count()
    out, worst = _hammer(20, lambda: swr.get("k", 60, _slow(calls, gate)))
    assert worst < 1.0
    assert all(o["status"] == "UNKNOWN" and o["reason"] == "building" for o in out)
    assert threading.active_count() <= before + 1  # exactly one builder thread, not 20
    assert len(calls) == 1
    gate.set()


def test_build_outlives_callers_and_result_is_stored():
    calls, gate = [], threading.Event()
    swr.get("k", 60, _slow(calls, gate))  # caller "reaped": it already returned
    gate.set()
    for _ in range(100):
        if not swr.inflight():
            break
        time.sleep(0.02)
    out = swr.get("k", 60, _slow(calls, gate))
    assert out["n"] == 1 and out["stale"] is False and out["age_s"] < 5 and out["as_of"]
    assert len(calls) == 1


def test_stale_waiters_get_last_good_with_age_while_rebuild_runs():
    calls, gate = [], threading.Event()
    gate.set()
    swr.get("k", 0.05, _slow(calls, gate))
    time.sleep(0.2)  # let first build land
    assert not swr.inflight()
    time.sleep(0.1)  # entry now older than ttl
    gate2 = threading.Event()
    calls2 = []
    out, worst = _hammer(20, lambda: swr.get("k", 0.05, _slow(calls2, gate2, {"n": 99})))
    assert worst < 1.0
    assert all(o["n"] == 1 and o["stale"] is True and o["age_s"] >= 0.1 for o in out)
    assert len(calls2) == 1
    gate2.set()


def test_failed_build_keeps_last_good_and_reports_error():
    ok = threading.Event()
    ok.set()
    swr.get("k", 0.01, _slow([], ok))
    time.sleep(0.2)

    def boom():
        raise RuntimeError("db down")

    time.sleep(0.05)
    swr.get("k", 0.01, boom)
    time.sleep(0.2)
    out = swr.get("k", 0.01, boom)
    assert out["n"] == 1 and out["stale"] is True and "db down" in out["last_build_error"]


def test_warm_starts_one_build_and_is_idempotent():
    calls, gate = [], threading.Event()
    assert swr.warm("k", 60, _slow(calls, gate)) is True
    assert swr.warm("k", 60, _slow(calls, gate)) is False
    gate.set()
    time.sleep(0.3)
    assert swr.warm("k", 60, _slow(calls, gate)) is False  # fresh
    assert swr.get("k", 60, _slow(calls, gate))["stale"] is False
    assert len(calls) == 1


def test_api_v2_opt_in_and_old_path_unchanged(monkeypatch):
    import scripts.api_v2 as api

    api._SHARED_GET_CACHE.clear()
    n = []
    assert api._shared_get_cached("old", 60, lambda: n.append(1) or {"a": 1}) == {"a": 1}  # blocking path
    # LQ-2600 (REVIEW-2606 F1): cio/pages reads the stored cio.pages product (LQ-2595). While that product is fresh
    # (OK/STALE) this process builds nothing, so the SWR cache holds no cio_pages key and the boot warm starts
    # nothing. A miss computes on the SWR thread (LQ-2743): tests/test_cio_pages_fallback_lq2743_20261112.py.
    from scripts.lib.cc_products import cio_pages_route as cpr

    served, queries = [], []
    fresh = {"stored": True, "_product": {"status": "OK"}}
    monkeypatch.setattr(cpr, "serve_cio_pages", lambda **kw: served.append(kw) or fresh)
    monkeypatch.setattr(cpr, "make_pg_fetch_row", lambda q: queries.append(q) or "fetch_row")
    monkeypatch.setattr(cpr, "production_hot", lambda: "hot")
    swr.clear()
    assert api._w7_cio_pages() == fresh
    assert served == [{"fetch_row": "fetch_row", "hot": "hot"}]
    assert queries == [api._db_query_raising]  # a store error must raise (UNKNOWN), never read as "no row"
    assert api.warm_swr_caches() == [] and not swr.inflight()


def test_asks_tracked_route_serves_last_good_tuple(monkeypatch, operator_identity):
    import scripts.api_v2 as api
    from scripts.lib import cio_ask_api as caa

    gate = threading.Event()
    monkeypatch.setattr(caa, "handle", lambda *a, **k: (gate.wait(10), (200, {"ok": True, "data": {"tracked": [1]}}))[1])
    t0 = time.monotonic()
    st, body = api._asks_tracked_cached("/api/v2/cio/asks/tracked", "GET", None, {})
    assert time.monotonic() - t0 < 1.0 and body["data"]["reason"] == "building"
    gate.set()
    time.sleep(0.3)
    st, body = api._asks_tracked_cached("/api/v2/cio/asks/tracked", "GET", None, {})
    assert st == 200 and body["data"]["tracked"] == [1] and body["data"]["stale"] is False


# ---- REVIEW-2580 (LQ-2584) ------------------------------------------------------------------------------
def _wait_idle():
    for _ in range(200):
        if not swr.inflight():
            return
        time.sleep(0.02)


def test_r1_cold_failure_reports_the_error_and_backs_off():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db down")

    swr.get("k", 60, boom)  # first poll starts the build
    _wait_idle()
    outs = [swr.get("k", 60, boom) for _ in range(5)]
    assert len(calls) == 1, "a persistent failure must not start a build per poll"
    for o in outs:
        assert o["status"] == "UNKNOWN" and o["reason"] == "build_failed"
        assert "db down" in o["last_build_error"] and o["last_build_error_at"]


def test_r1_retry_after_backoff_then_recovers(monkeypatch):
    monkeypatch.setattr(swr, "MIN_BACKOFF_S", 0.05)
    state = {"fail": True, "n": 0}

    def b():
        state["n"] += 1
        if state["fail"]:
            raise RuntimeError("x")
        return {"v": 1}

    swr.get("k", 0.05, b)
    _wait_idle()
    time.sleep(0.1)
    state["fail"] = False
    swr.get("k", 0.05, b)  # backoff over -> retry
    _wait_idle()
    out = swr.get("k", 0.05, b)
    assert out["v"] == 1 and state["n"] == 2 and "last_build_error" not in out


def test_r2_running_build_is_visible_and_stuck_build_is_not_replaced(monkeypatch):
    # Operator 13 Nov 2026 (containment point 3): a stuck build keeps its duplicate exclusion until it truly ends.
    monkeypatch.setattr(swr, "STUCK_FACTOR", 1.0)  # stuck after max(ttl, 1) s = 1 s here
    hang, calls = threading.Event(), []

    def hung():
        calls.append("hung")
        hang.wait(10)
        return {"v": "old"}

    swr.get("k", 0.01, hung)
    time.sleep(0.05)
    first = swr.get("k", 0.01, hung)
    assert first["reason"] in ("building", "build_stuck") and "build_running_s" in first
    time.sleep(1.1)
    out = swr.get("k", 0.01, lambda: calls.append("new") or {"v": "new"})
    assert out["reason"] == "build_stuck" and out.get("build_refused") == "REFUSED_DUPLICATE"
    assert calls == ["hung"] and swr.running_builds() == 1  # no second build of the key was started
    hang.set()
    _wait_idle()
    assert swr.get("k", 60, lambda: {"v": "x"})["v"] == "old"  # the stuck build's own result lands when it ends
    assert "new" not in calls


def test_r2_stale_payload_shows_build_running_and_stuck(monkeypatch):
    monkeypatch.setattr(swr, "STUCK_FACTOR", 1.0)
    ok = threading.Event()
    ok.set()
    swr.get("k", 0.01, _slow([], ok))
    _wait_idle()
    time.sleep(0.05)
    hang = threading.Event()
    swr.get("k", 0.01, _slow([], hang))
    time.sleep(1.1)
    out = swr.get("k", 0.01, _slow([], hang))
    assert out["stale"] is True and out["build_stuck"] is True and out["build_running_s"] >= 1.0
    hang.set()


def test_n1_http_error_tuple_is_a_failure_not_last_good():
    good = (200, {"ok": True, "data": {"tracked": [1]}})
    swr.get("k", 0.01, lambda: good)
    _wait_idle()
    time.sleep(0.05)
    swr.get("k", 0.01, lambda: (500, {"ok": False}))
    _wait_idle()
    out = swr.get("k", 0.01, lambda: (500, {"ok": False}))
    assert out == good  # default annotate leaves non-dict payloads untouched
    assert swr._ERRORS["k"]["error"].endswith("HTTP 500")


def test_r3_asks_tracked_through_the_route_handler(monkeypatch, operator_identity):
    import scripts.api_v2 as api
    from scripts.lib import cio_ask_api as caa

    swr.clear()
    gate = threading.Event()
    monkeypatch.setattr(caa, "handle", lambda *a, **k: (gate.wait(10), (200, {"ok": True, "data": {"tracked": [7]}}))[1])
    t0 = time.monotonic()
    st, body = api.handle("/api/v2/cio/asks/tracked", "GET")
    assert time.monotonic() - t0 < 1.0 and st == 200
    assert body["data"]["status"] == "UNKNOWN" and body["data"]["reason"] == "building" and body["data"]["tracked"] is None
    gate.set()
    _wait_idle()
    st, body = api.handle("/api/v2/cio/asks/tracked", "GET")
    d = body["data"]
    assert st == 200 and d["tracked"] == [7] and d["stale"] is False and "age_s" in d and d["cache_as_of"]


def test_r3_asks_tracked_cold_failure_through_the_route_handler(monkeypatch, operator_identity):
    import scripts.api_v2 as api
    from scripts.lib import cio_ask_api as caa

    swr.clear()
    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(caa, "handle", boom)
    api.handle("/api/v2/cio/asks/tracked", "GET")
    _wait_idle()
    st, body = api.handle("/api/v2/cio/asks/tracked", "GET")
    assert body["data"]["reason"] == "build_failed" and "store down" in body["data"]["last_build_error"]
