"""ANCHOR: ZOMBIE_COMPUTE_BOUNDS_LQ2130 — portfolio-server stops piling up unbounded computes (synthetic fixtures only).

(a) the abandoned-compute watchdog logs a reaped request once, and says it still holds its slot;
(b) a cold jobs-health caller waits a bounded time and gets SnapshotBusy (the route's 503), never a second compute;
(c) /api/v2/overview skips the request semaphore only while its projection is fresh;
(d) a coalesced waiter whose leader is stuck gets a 503, it does not recompute.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from scripts.lib import jobs_health as JH
from scripts.lib import overview_projection as OP
from scripts.lib import request_coalesce as RC


# ── (b) jobs-health cold wait ────────────────────────────────────────────────────────────────────────────────
def test_cold_jobs_health_waiter_is_turned_away_not_queued(tmp_path, monkeypatch):
    monkeypatch.setattr(JH, "COLD_WAIT_SECONDS", 0.3)
    JH._CACHE.clear()
    reg = tmp_path / "lane_registry.json"
    reg.write_text("{}")
    held = threading.Event()
    release = threading.Event()

    def leader():  # stands in for the one compute that is running
        with JH._SINGLE:
            held.set()
            release.wait(10)

    t = threading.Thread(target=leader, daemon=True)
    t.start()
    assert held.wait(5)
    t0 = time.monotonic()
    try:
        with pytest.raises(JH.SnapshotBusy):
            JH.get_jobs_health({}, state_root=tmp_path, registry_path=reg)
        waited = time.monotonic() - t0
    finally:
        release.set()
        t.join(5)
    assert 0.25 <= waited < 3, waited
    assert JH._SINGLE.acquire(timeout=1), "the lock must not stay held after a refused waiter"
    JH._SINGLE.release()


# ── (c) overview exemption ───────────────────────────────────────────────────────────────────────────────────
def _write_projection(path: Path, built_at: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": OP.SCHEMA, "status": "ok", "started_at_epoch": built_at - 1,
                                "built_at_epoch": built_at, "built_at": "x", "code_identity": "i", "body": {"a": 1}}))


def test_is_fresh_follows_the_projection_age(tmp_path):
    p = tmp_path / "overview_projection.json"
    assert OP.is_fresh(p) is False                                   # missing
    _write_projection(p, time.time() - 10)
    assert OP.is_fresh(p) is True
    _write_projection(p, time.time() - (OP.MAX_AGE_S + 60))
    assert OP.is_fresh(p) is False                                   # aged: the 21:00-04:00 case
    _write_projection(p, time.time() + 3600)
    assert OP.is_fresh(p) is False                                   # from the future
    p.write_text("{not json")
    assert OP.is_fresh(p) is False                                   # corrupt: unknown is not fresh


def test_overview_skips_the_semaphore_only_while_the_projection_is_fresh(tmp_path, monkeypatch):
    import scripts.portfolio_server as ps
    p = tmp_path / "overview_projection.json"
    monkeypatch.setenv(OP.PATH_ENV, str(p))
    assert ps._sem_exempt_path("/api/v2/overview") is False          # no projection: takes a slot
    _write_projection(p, time.time() - 5)
    assert ps._sem_exempt_path("/api/v2/overview") is True
    assert ps._sem_exempt_path("/api/v2/overview/") is True
    _write_projection(p, time.time() - (OP.MAX_AGE_S + 5))
    assert ps._sem_exempt_path("/api/v2/overview") is False          # aged: computes inline, so it takes a slot
    assert ps._sem_exempt_path("/api/health") is True                # the others are unchanged
    assert ps._sem_exempt_path("/api/v2/jobs-health") is False


# ── (d) coalesce stuck leader ────────────────────────────────────────────────────────────────────────────────
def test_stuck_leader_gives_waiters_a_503_and_no_second_compute():
    co = RC.Coalescer(ttl=0.0, wait_s=0.3)
    started, release, calls = threading.Event(), threading.Event(), []

    def slow():
        calls.append(1)
        started.set()
        release.wait(10)
        return 200, {"ok": True}

    leader = threading.Thread(target=lambda: co.run("k", slow), daemon=True)
    leader.start()
    assert started.wait(5)
    try:
        with pytest.raises(RC.LeaderStuck):
            co.run("k", lambda: calls.append("second") or (200, {}))
    finally:
        release.set()
        leader.join(5)
    assert calls == [1], calls


def test_coalesce_get_maps_a_stuck_leader_to_503(monkeypatch):
    co = RC.Coalescer(ttl=0.0, wait_s=0.2)
    started, release, calls = threading.Event(), threading.Event(), []

    def slow():
        calls.append("lead")
        started.set()
        release.wait(10)
        return 200, {"ok": True}

    t = threading.Thread(target=lambda: RC.coalesce_get("/api/v2/overview", {}, slow, principal="p", coalescer=co),
                         daemon=True)
    t.start()
    assert started.wait(5)
    try:
        out = RC.coalesce_get("/api/v2/overview", {}, lambda: calls.append("waiter") or (200, {}),
                              principal="p", coalescer=co)
    finally:
        release.set()
        t.join(5)
    assert out[0] == 503 and out[1]["error"] == "coalesce_leader_stuck"
    assert calls == ["lead"], calls


# ── (a) watchdog logs a reaped compute once ──────────────────────────────────────────────────────────────────
def test_watchdog_reaps_and_logs_an_abandoned_compute_once(capsys):
    import scripts.portfolio_server as ps
    a, b = socket.socketpair()
    b.close()                                                         # the client went away
    t0 = time.time() - (ps._WATCHDOG_ABANDON_SEC + 60)
    with ps._INFLIGHT_LOCK:
        ps._INFLIGHT[999001] = ("/api/v2/jobs-health", t0, a)
    ps._REAPED.clear()
    try:
        now = time.time()
        assert ps._watchdog_pass(now) == 1
        assert ps._watchdog_pass(now + 5) == 0
        assert ps._watchdog_pass(now + 10) == 0
        out = capsys.readouterr().out
        assert out.count("reaped abandoned compute: /api/v2/jobs-health") == 1, out
        assert "keeps its request slot" in out
    finally:
        with ps._INFLIGHT_LOCK:
            ps._INFLIGHT.pop(999001, None)
        ps._watchdog_pass(time.time())                                # drops the entry from _REAPED
        a.close()
    assert not any(k[0] == 999001 for k in ps._REAPED)
