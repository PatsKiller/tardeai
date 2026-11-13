"""MEM-CONTAIN 2026-11-13 (TEMPORARY CONTAINMENT): the wired heavy GETs never build on the request thread, and keys
are separated by principal and query. Needs the api_v2 wiring patch (api_v2.py is claimed by another session)."""
import threading
import time

import pytest

from scripts.lib import shared_get_swr as swr


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SWR_SLOT_DIR", raising=False)
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (None, None))
    swr.clear()
    yield
    _wait_idle()
    swr.clear()


def _wait_idle(timeout=5):
    deadline = time.time() + timeout
    while swr.running_builds() and time.time() < deadline:
        time.sleep(0.01)


# ── api_v2 wiring ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(monkeypatch):
    import api_v2

    return api_v2


def _block_request_thread_build(monkeypatch, api, attr):
    """Replace a heavy builder with one that records the thread it ran on."""
    seen = []

    def fake(*a, **k):
        seen.append(threading.current_thread().name)
        return {"built": True, "links": {}, "state": "evaluated"}
    monkeypatch.setattr(api, attr, fake)
    return seen


@pytest.mark.parametrize("call,attr", [
    (lambda api: api._reports_analyst_links_swr({"limit": "500"}), "_reports_analyst_links"),
    (lambda api: api._market_risk_latest_swr(), "_market_risk_latest_projection"),
    (lambda api: api._home_cio_card(), "_home_cio_card_build"),
])
def test_wired_routes_never_build_on_the_request_thread(api, monkeypatch, call, attr):
    seen = _block_request_thread_build(monkeypatch, api, attr)
    me = threading.current_thread().name
    first = call(api)
    assert (first.get("status") == "UNKNOWN") or (first.get("state") == "not_evaluated")
    _wait_idle()
    assert seen and all(n.startswith("swr-build-") and n != me for n in seen)
    second = call(api)
    assert second.get("built") is True and second["cache_stale"] is False  # review B1: the cache freshness, never the payload's own


def test_risk_route_never_builds_on_the_request_thread(api, monkeypatch):
    seen = []

    class R:
        def risk_payload(self, db_query=None):
            seen.append(threading.current_thread().name)
            return {"positions": []}
    monkeypatch.setattr(api, "_cio_truth_readers", lambda: R())
    first = api._risk_payload_cached()
    assert first["status"] == "UNKNOWN" and first["positions"] is None
    _wait_idle()
    assert seen and seen[0].startswith("swr-build-")


def test_scope_keys_separate_principal_and_query(api, monkeypatch):
    from lib import cc_auth

    built = []

    def fake(q):
        built.append(dict(q))
        return {"links": {q["symbol"] or "*": cc_auth.current_principal()}}
    monkeypatch.setattr(api, "_reports_analyst_links", fake)
    keys = set()
    for principal in ("tailnet:alice", "service-token"):
        monkeypatch.setattr(cc_auth, "current_principal", lambda p=principal: p)
        for q in ({"limit": "500"}, {"limit": "300"}, {"symbol": "abc", "limit": "500"}):
            api._reports_analyst_links_swr(q)
            _wait_idle()
            keys.add(api._swr_scope_key("reports_analyst_links", symbol=(q.get("symbol") or "").upper(),
                                        limit=int(q["limit"])))
    assert len(keys) == 6 and len(built) == 6  # every (principal, symbol, limit) is its own entry and build
    monkeypatch.setattr(cc_auth, "current_principal", lambda: "tailnet:alice")
    a = api._reports_analyst_links_swr({"symbol": "abc", "limit": "500"})
    monkeypatch.setattr(cc_auth, "current_principal", lambda: "service-token")
    b = api._reports_analyst_links_swr({"symbol": "abc", "limit": "500"})
    assert a["stale"] is False and b["stale"] is False
    assert all("principal=tailnet:alice" in k or "principal=service-token" in k for k in keys)


def test_analyst_links_bad_limit_is_rejected_without_a_build(api, monkeypatch):
    seen = _block_request_thread_build(monkeypatch, api, "_reports_analyst_links")
    st, body = api._reports_analyst_links_swr({"limit": "lots"})
    assert st == 400 and body["ok"] is False and seen == [] and swr.running_builds() == 0
