"""MEM-CONTAIN v2 independent re-review: tests for the four mutants that survived the author suite (B2-b, B3-e, CAP-d,
AUTH-c). Synthetic keys, principals and payloads only; every send is a recorder."""
import threading
import time

import pytest

from scripts.lib import shared_get_swr as swr


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SWR_SLOT_DIR", raising=False)
    monkeypatch.delenv("SWR_BUILD_LEASE_S", raising=False)
    monkeypatch.delenv("SWR_MAX_CONCURRENT_BUILDS", raising=False)
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (None, None))
    swr.clear()
    yield
    deadline = time.time() + 5
    while swr.running_builds() and time.time() < deadline:
        time.sleep(0.01)
    swr.clear()


# ── CAP-d: the default per-process build cap is 2 ─────────────────────────────────────────────────────────────
def test_cap_default_is_two():
    assert swr.max_concurrent_builds() == 2


def test_cap_default_refuses_the_third_concurrent_build():
    gate = threading.Event()
    try:
        swr.get("c1", 60, lambda: gate.wait(10) or {"c": 1})
        swr.get("c2", 60, lambda: gate.wait(10) or {"c": 2})
        assert swr.get("c3", 60, lambda: {"c": 3}).get("build_refused") == "REFUSED_CAP"
    finally:
        gate.set()


# ── B3-e: the lease never reaps a reservation whose thread has not launched yet ───────────────────────────────
def test_lease_skips_an_unlaunched_reservation(monkeypatch):
    monkeypatch.setenv("SWR_BUILD_LEASE_S", "0.05")
    with swr._LOCK:
        token, _ = swr._reserve("unlaunched", 60)
        assert token is not None
        swr._RUNNING[token]["started"] -= 10.0  # far past the lease, but still between _reserve and _launch
        docs = swr._reap_leases()
        assert token in swr._RUNNING and docs == []
        assert swr._INFLIGHT["unlaunched"]["token"] == token
        swr._RUNNING.pop(token, None)
        swr._INFLIGHT.pop("unlaunched", None)
    assert swr.stats()["abandoned_builds"] == 0  # stats() takes _LOCK: read it after releasing


# ── AUTH-c: the cio-card market-risk key is resolved on the request thread (principal is thread-local) ────────
def test_cio_card_market_risk_key_carries_the_request_principal(monkeypatch):
    import api_v2
    from lib import cc_auth

    seen = []

    def fake_build(mr_key=None):
        seen.append(mr_key)
        return {"built": True}
    monkeypatch.setattr(api_v2, "_home_cio_card_build", fake_build)
    cc_auth.set_request_principal("tailnet:synthetic-user")
    try:
        api_v2._home_cio_card()
        deadline = time.time() + 5
        while not seen and time.time() < deadline:
            time.sleep(0.01)
    finally:
        cc_auth.set_request_principal(None)
    assert seen and "principal=tailnet:synthetic-user" in seen[0]


# ── B2-b: a ready risk payload whose positions are null or absent is UNKNOWN, never "no position" ────────────
@pytest.mark.parametrize("data", [{"positions": None}, {"status": "OK"}])
def test_null_or_missing_positions_is_unknown(monkeypatch, data):
    import stop_alert_assembler as saa

    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": data} if p == "/api/v2/risk" else {})
    out = saa.assemble_stop_alert_data("SYNTH")
    assert out is not None and out["status"] == "UNKNOWN" and "positions" in out["reason"]
