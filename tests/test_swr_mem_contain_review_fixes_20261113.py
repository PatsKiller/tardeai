"""MEM-CONTAIN review fixes (REVIEW-MEM-CONTAIN-20261113-independent): B1 market-risk freshness, B3 build lease,
N1 memory guard over non-reclaimable memory, N5 no disk/proc I/O under the SWR lock, N6 same-process duplicate
detail + surfaced stuck-replacement refusal. Synthetic payloads and temporary slot dirs only."""
import threading
import time

import pytest

from scripts.lib import shared_get_swr as swr

_REAL_CGROUP_MEMORY = swr.cgroup_memory


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SWR_SLOT_DIR", raising=False)
    monkeypatch.delenv("SWR_BUILD_LEASE_S", raising=False)
    monkeypatch.setenv("SWR_MEMORY_GUARD_PCT", "85")
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (None, None))
    swr.clear()
    yield
    _wait(lambda: swr.running_builds() == 0)
    swr.clear()


def _wait(pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _idle():
    _wait(lambda: swr.running_builds() == 0)


# ── B1: the projection's own freshness fields are never overwritten by cache metadata ─────────────────────────
def test_b1_market_risk_engine_stale_survives_a_fresh_cache(monkeypatch):
    import api_v2

    proj = {"state": "stale", "tier": "RED", "as_of": "2026-01-02T09:00:00+00:00", "stale": True, "age_hours": 6.5,
            "reason": None}
    monkeypatch.setattr(api_v2, "_market_risk_latest_projection", lambda: dict(proj))
    api_v2._market_risk_latest_swr()
    _idle()
    out = api_v2._market_risk_latest_swr()
    assert out["state"] == "stale" and out["stale"] is True and out["as_of"] == proj["as_of"]
    assert out["reason"] is None and "status" not in out
    assert out["cache_stale"] is False and out["cache_as_of"] and out["cache_age_s"] is not None


def test_b1_market_risk_evaluated_red_stays_not_stale_after_cache_ttl(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_MARKET_RISK_TTL_S", 0.05)
    proj = {"state": "evaluated", "tier": "RED", "as_of": "2026-01-02T20:00:00+00:00", "stale": False}
    monkeypatch.setattr(api_v2, "_market_risk_latest_projection", lambda: dict(proj))
    api_v2._market_risk_latest_swr()
    _idle()
    time.sleep(0.06)
    out = api_v2._market_risk_latest_swr()
    # bannerVisible() needs !stale: an evaluated RED must keep stale False whatever the cache age is
    assert out["state"] == "evaluated" and out["stale"] is False and out["as_of"] == proj["as_of"]
    assert out["cache_stale"] is True


def test_b1_market_risk_handler_serves_engine_freshness(monkeypatch):
    import api_v2

    proj = {"state": "stale", "tier": "ORANGE", "as_of": "2026-01-02T09:00:00+00:00", "stale": True}
    monkeypatch.setattr(api_v2, "_market_risk_latest_projection", lambda: dict(proj))
    api_v2._market_risk_latest_swr()
    _idle()
    st, body = api_v2.handle("/api/v2/market-risk/latest", "GET", None, {})
    assert st == 200 and body["data"]["stale"] is True and body["data"]["as_of"] == proj["as_of"]


def test_b1_stale_red_stays_red_and_stale_through_cache_age_and_failed_rebuilds(monkeypatch):
    """Operator 2026-11-13: RED whose data went stale renders RED and visibly stale at the API; neither cache age nor a
    failing rebuild clears the warning (last-good RED stays served, the engine's stale stays True)."""
    import api_v2

    monkeypatch.setattr(api_v2, "_MARKET_RISK_TTL_S", 0.05)
    proj = {"state": "stale", "tier": "RED", "score": 83, "as_of": "2026-01-02T09:00:00+00:00", "stale": True}
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("synthetic engine read failure")
        return dict(proj)
    monkeypatch.setattr(api_v2, "_market_risk_latest_projection", build)
    api_v2._market_risk_latest_swr()
    _idle()
    for _ in range(3):
        time.sleep(0.06)
        st, body = api_v2.handle("/api/v2/market-risk/latest", "GET", None, {})
        _idle()
        d = body["data"]
        assert st == 200 and d["tier"] == "RED" and d["score"] == 83
        assert d["state"] == "stale" and d["stale"] is True and d["as_of"] == proj["as_of"]
        assert d["cache_stale"] is True and d.get("status") != "UNKNOWN"
    assert calls["n"] >= 2  # rebuilds were attempted and failed; the warning never cleared
    st, body = api_v2.handle("/api/v2/market-risk/latest", "GET", None, {})
    assert "last_build_error" in body["data"] and body["data"]["tier"] == "RED"


@pytest.mark.parametrize("fail", [False, True])
def test_b1_missing_market_risk_is_unknown_never_a_calm_tier(monkeypatch, fail):
    """MISSING risk (nothing built yet, or the first build failed) renders UNKNOWN: no tier, stale, a reason."""
    import api_v2

    def build():
        if fail:
            raise RuntimeError("synthetic engine read failure")
        time.sleep(0.3)
        return {"state": "evaluated", "tier": "GREEN", "as_of": "2026-01-02T09:00:00+00:00", "stale": False}
    monkeypatch.setattr(api_v2, "_market_risk_latest_projection", build)
    st, body = api_v2.handle("/api/v2/market-risk/latest", "GET", None, {})
    if fail:
        _idle()
        st, body = api_v2.handle("/api/v2/market-risk/latest", "GET", None, {})
    d = body["data"]
    assert st == 200 and d["status"] == "UNKNOWN" and d["state"] == "not_evaluated" and d["stale"] is True
    assert "tier" not in d and d["as_of"] is None
    assert d["reason"] == ("build_failed" if fail else "building")


@pytest.mark.parametrize("call,attr", [
    (lambda api: api._reports_analyst_links_swr({"limit": "500"}), "_reports_analyst_links"),
    (lambda api: api._home_cio_card(), "_home_cio_card_build"),
])
def test_b1_other_bounded_routes_never_clobber_payload_fields(monkeypatch, call, attr):
    import api_v2

    own = {"as_of": "2026-01-02T08:00:00+00:00", "stale": True, "state": "x", "status": "OK", "age_s": 7}
    monkeypatch.setattr(api_v2, attr, lambda *a, **k: dict(own))
    call(api_v2)
    _idle()
    out = call(api_v2)
    for k, v in own.items():
        assert out[k] == v
    assert out["cache_stale"] is False and out["cache_as_of"]


def test_b1_risk_route_never_clobbers_payload_fields(monkeypatch):
    import api_v2

    class R:
        def risk_payload(self, db_query=None):
            return {"positions": [], "as_of": "2026-01-02T08:00:00+00:00", "stale": True}
    monkeypatch.setattr(api_v2, "_cio_truth_readers", lambda: R())
    api_v2._risk_payload_cached()
    _idle()
    out = api_v2._risk_payload_cached()
    assert out["as_of"] == "2026-01-02T08:00:00+00:00" and out["stale"] is True and out["cache_stale"] is False


def test_b1_routes_without_own_fields_still_carry_top_level_freshness(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_reports_analyst_links", lambda *a, **k: {"links": {}, "count": 0})
    api_v2._reports_analyst_links_swr({"limit": "5"})
    _idle()
    out = api_v2._reports_analyst_links_swr({"limit": "5"})
    assert out["stale"] is False and out["as_of"] == out["cache_as_of"] and out["age_s"] == out["cache_age_s"]


# ── B3: a hung build is released after the lease ──────────────────────────────────────────────────────────────
def test_b3_two_hung_builds_no_longer_starve_every_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SWR_SLOT_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("SWR_MAX_CONCURRENT_BUILDS", "2")
    monkeypatch.setenv("SWR_BUILD_LEASE_S", "0.5")
    released = []
    real_release = swr.release_slots

    def rec_release(fds):
        if fds:
            released.append(id(fds))
        real_release(fds)
    monkeypatch.setattr(swr, "release_slots", rec_release)
    gate = threading.Event()

    def hang():
        gate.wait(30)
        return {"late": True}
    assert swr.get("k1", 60, hang)["status"] == "UNKNOWN"
    assert swr.get("k2", 60, hang)["status"] == "UNKNOWN"
    assert swr.get("k3", 60, lambda: {"ok": 1}).get("build_refused") == "REFUSED_CAP"
    time.sleep(0.6)  # past the lease
    r3 = swr.get("k3", 60, lambda: {"ok": 1})
    assert r3.get("build_refused") is None and r3["reason"] == "building"
    assert _wait(lambda: swr.peek("k3", 60) == {"ok": 1})
    st = swr.stats()
    assert st["abandoned_builds"] == 2 and st["abandoned_total"] == 2
    out = capsys.readouterr().out
    assert out.count('"outcome": "ABANDONED_LEASE"') == 2
    # the hung threads return later: their slots are not released a second time, the late result still stores
    n_before = len(released)
    gate.set()
    assert _wait(lambda: swr.stats()["abandoned_builds"] == 0)
    assert len(released) == n_before and len(released) == len(set(released))
    assert swr.peek("k1", 60) == {"late": True}


def test_b3_lease_without_slot_pool_frees_the_process_cap(monkeypatch):
    monkeypatch.setenv("SWR_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("SWR_BUILD_LEASE_S", "0.3")
    gate = threading.Event()
    swr.get("a", 60, lambda: gate.wait(30) or {"a": 1})
    assert swr.get("b", 60, lambda: {"b": 1}).get("build_refused") == "REFUSED_CAP"
    time.sleep(0.35)
    swr.get("b", 60, lambda: {"b": 1})
    assert _wait(lambda: swr.peek("b", 60) == {"b": 1})
    assert swr.running_builds() == 0 and swr.stats()["abandoned_builds"] == 1
    # the abandoned key can build again (its in-flight mark went with the lease)
    swr.get("a", 60, lambda: {"a": 2})
    assert _wait(lambda: swr.peek("a", 60) == {"a": 2})
    gate.set()
    assert _wait(lambda: swr.stats()["abandoned_builds"] == 0)
    assert swr.peek("a", 60) == {"a": 2}  # the older abandoned build never overwrites the newer result


def test_b3_lease_default_is_300s(monkeypatch):
    monkeypatch.delenv("SWR_BUILD_LEASE_S", raising=False)
    assert swr.build_lease_s() == 300.0


# ── N1: page cache does not count against the memory guard ────────────────────────────────────────────────────
def _cg(tmp_path, current, high, stat=None):
    cg = tmp_path / "cg"
    cg.mkdir(exist_ok=True)
    (cg / "memory.current").write_text(f"{current}\n")
    (cg / "memory.high").write_text(f"{high}\n")
    if stat is not None:
        (cg / "memory.stat").write_text("".join(f"{k} {v}\n" for k, v in stat.items()))
    return cg


def test_n1_guard_uses_anon_plus_kernel_not_page_cache(tmp_path, monkeypatch):
    # live shape 2026-11-13 15:27 ET, rounded: current 2.28 GB = 85% of high, but 0.9 GB of it is file cache
    cg = _cg(tmp_path, 2_290_000_000, 2_684_354_560,
             {"anon": 1_280_000_000, "file": 900_000_000, "kernel": 100_000_000, "inactive_file": 600_000_000})
    monkeypatch.setattr(swr, "_CGROUP_DIR", [str(cg)])
    assert _REAL_CGROUP_MEMORY() == (1_380_000_000, 2_684_354_560)
    monkeypatch.setattr(swr, "cgroup_memory", _REAL_CGROUP_MEMORY)
    assert swr._memory_refusal() is None


def test_n1_guard_falls_back_to_current_minus_inactive_file(tmp_path, monkeypatch):
    cg = _cg(tmp_path, 2_000, 4_000, {"anon": 900, "inactive_file": 700})  # no "kernel" key (older kernels)
    monkeypatch.setattr(swr, "_CGROUP_DIR", [str(cg)])
    assert _REAL_CGROUP_MEMORY() == (1_300, 4_000)


def test_n1_guard_still_refuses_on_real_anon_pressure(tmp_path, monkeypatch):
    cg = _cg(tmp_path, 2_600_000_000, 2_684_354_560, {"anon": 2_350_000_000, "kernel": 50_000_000})
    monkeypatch.setattr(swr, "_CGROUP_DIR", [str(cg)])
    monkeypatch.setattr(swr, "cgroup_memory", _REAL_CGROUP_MEMORY)
    assert "anon+kernel" in (swr._memory_refusal() or "")


def test_n1_no_memory_stat_keeps_memory_current_and_fails_open_when_unreadable(tmp_path, monkeypatch):
    cg = _cg(tmp_path, 100, 200)
    monkeypatch.setattr(swr, "_CGROUP_DIR", [str(cg)])
    assert _REAL_CGROUP_MEMORY() == (100, 200)
    (cg / "memory.current").unlink()
    assert _REAL_CGROUP_MEMORY() == (None, None)


# ── N5: the request path does no disk / proc / cgroup I/O while holding the SWR lock ──────────────────────────
def test_n5_no_io_under_the_swr_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("SWR_SLOT_DIR", str(tmp_path / "slots"))
    held = []
    real_acquire, real_rss = swr.acquire_host_slots, swr.rss_kb

    def mem():
        held.append(("cgroup_memory", swr._LOCK.locked()))
        return None, None

    def acquire(key, cap):
        held.append(("acquire_host_slots", swr._LOCK.locked()))
        return real_acquire(key, cap)

    def rss():
        held.append(("rss_kb", swr._LOCK.locked()))
        return real_rss()
    monkeypatch.setattr(swr, "cgroup_memory", mem)
    monkeypatch.setattr(swr, "acquire_host_slots", acquire)
    monkeypatch.setattr(swr, "rss_kb", rss)
    swr.get("k", 60, lambda: {"v": 1})
    _wait(lambda: swr.peek("k", 60) is not None)
    names = {n for n, _ in held}
    assert {"cgroup_memory", "acquire_host_slots", "rss_kb"} <= names
    assert not [n for n, locked in held if locked]


def test_n5_concurrent_identical_requests_still_start_one_build(monkeypatch, tmp_path):
    monkeypatch.setenv("SWR_SLOT_DIR", str(tmp_path / "slots"))
    calls, gate = [], threading.Event()
    barrier, outs = threading.Barrier(20), []

    def build():
        calls.append(1)
        gate.wait(10)
        return {"v": 1}

    def req():
        barrier.wait()
        outs.append(swr.get("same", 60, build))
    ts = [threading.Thread(target=req) for _ in range(20)]
    [t.start() for t in ts]
    [t.join(5) for t in ts]
    assert len(outs) == 20 and len(calls) == 1
    assert not any(o.get("build_refused") for o in outs)
    gate.set()


# ── N6: a same-process duplicate says so, and the refusal of a stuck replacement is surfaced ──────────────────
def test_n6_stuck_replacement_refusal_is_named_and_surfaced(monkeypatch, tmp_path):
    monkeypatch.setenv("SWR_SLOT_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("SWR_MAX_CONCURRENT_BUILDS", "3")
    monkeypatch.setattr(swr, "STUCK_FACTOR", 0.2)  # stuck after 0.2 s at ttl 1
    gate = threading.Event()
    swr.get("k1", 1, lambda: gate.wait(30) or {"x": 1})
    time.sleep(0.25)
    r = swr.get("k1", 1, lambda: {"ok": 1})
    assert r["reason"] == "build_stuck" and r["build_refused"] == "REFUSED_DUPLICATE"
    assert "this process" in swr.stats()["refused"]["k1"]["detail"]
    gate.set()
