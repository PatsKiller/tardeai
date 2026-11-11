"""ANCHOR: JOBS_HISTORY_SINGLEFLIGHT_LQ1890 — a cold jobs-history body is built once, not once per caller.

2026-11-11: after the 11:54 fold restarted the dashboard, a browser load sent several concurrent
``/api/v2/jobs-history`` requests at a ``None`` cache. ``snapshot()`` computed inline on every one of
them (the wrapper journal reaped those computes after 484–682 s), the 64 request slots starved into
``503 server_busy`` and the accumulated builds drove the process past its cgroup MemoryMax (SIGKILL,
2.5 GiB peak). The cold path is now single-flight: one caller builds, the others wait for that body,
and a caller whose bounded wait runs out gets ``SnapshotBusy`` (the API's 503) rather than starting a
second build. Stale-while-revalidate is unchanged.

Hermetic: ``_load`` is monkeypatched; no database, registry, journal or host state is read.
"""
import threading
import time

import pytest

from scripts.lib import jobs_history as J


def _reset_caches():
    # getattr-with-default so the same file also runs against the pre-fix module (fail-before run).
    J._CACHE.clear()
    for name in ("_COLD", "_REFRESHING"):
        getattr(J, name, set()).clear()


@pytest.fixture(autouse=True)
def clean_caches():
    _reset_caches()
    yield
    _reset_caches()


def _registry(tmp_path):
    path = tmp_path / "lane_registry.json"
    path.write_text('{"lanes": []}', encoding="utf-8")
    return path


def _snapshot(tmp_path, registry):
    return J.snapshot(state_root=tmp_path, registry_path=registry)


def _run_threads(target, n, timeout=15):
    start = threading.Barrier(n)
    errors, results = [], []

    def wrapped():
        start.wait(timeout=5)
        try:
            results.append(target())
        except Exception as exc:  # noqa: BLE001 — the test inspects what surfaced
            errors.append(exc)

    threads = [threading.Thread(target=wrapped) for _ in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "a caller never returned"
    return results, errors


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── fail-before: N concurrent cold callers -> N builds ────────────────────────────────────────────────────────────

def test_concurrent_cold_callers_share_one_build(tmp_path, monkeypatch):
    """Eight callers hit a cold cache together: one ``_load``; every caller gets that body.

    On the pre-fix code this is 8 builds (measured: eight concurrent computes on 2026-11-11), which is
    what starved the request slots and the cgroup.
    """
    registry = _registry(tmp_path)
    builds, lock = [], threading.Lock()

    def fake_load(root, registry_path, now, **extra):
        with lock:
            builds.append(time.monotonic())
        time.sleep(0.6)  # a real cold build measured ~20 s; the ordering is what matters here
        return {"rows": [], "build_number": len(builds), "computed_at": now.isoformat()}

    monkeypatch.setattr(J, "_load", fake_load)
    results, errors = _run_threads(lambda: _snapshot(tmp_path, registry), 8)

    assert not errors, errors
    assert len(builds) == 1, f"{len(builds)} builds for 8 concurrent cold callers"
    assert len(results) == 8
    assert all(r["build_number"] == 1 for r in results), "a caller got a body from a different build"
    assert all(r is results[0] for r in results), "the waiters must serve the leader's body, not a copy"


def test_a_waiter_that_cannot_wait_gets_busy_not_a_second_build(tmp_path, monkeypatch):
    """A bounded wait that runs out raises ``SnapshotBusy``; it never starts a competing build."""
    registry = _registry(tmp_path)
    monkeypatch.setattr(J, "COLD_WAIT_SECONDS", 0.2)
    gate, builds = threading.Event(), []

    def slow_load(root, registry_path, now, **extra):
        builds.append(time.monotonic())
        gate.wait(10)
        return {"rows": [], "build_number": len(builds)}

    monkeypatch.setattr(J, "_load", slow_load)
    first, first_errors = [], []
    leader = threading.Thread(target=lambda: first.append(_snapshot(tmp_path, registry)))
    leader.start()
    assert _wait_for(lambda: bool(J._COLD)), "the leader never registered as building"

    started = time.monotonic()
    with pytest.raises(J.SnapshotBusy) as busy:
        _snapshot(tmp_path, registry)
    waited = time.monotonic() - started
    assert 0.1 <= waited < 5, waited
    assert "jobs history is computing its first body" in str(busy.value)
    assert len(builds) == 1, "the busy caller added a build"

    gate.set()
    leader.join(10)
    assert not leader.is_alive() and not first_errors
    assert _wait_for(lambda: bool(J._CACHE))
    served = _snapshot(tmp_path, registry)
    assert served["rows"] == [] and len(builds) == 1, "the finished body must be reused"


def test_a_failed_leader_releases_the_flag_and_exactly_one_retry_builds(tmp_path, monkeypatch):
    """A leader that raises does not leave the key 'building' forever; exactly one retry rebuilds it."""
    registry = _registry(tmp_path)
    attempts, lock = [], threading.Lock()

    def flaky_load(root, registry_path, now, **extra):
        with lock:
            attempts.append(time.monotonic())
            attempt = len(attempts)
        if attempt == 1:
            time.sleep(0.2)
            raise RuntimeError("synthetic cold-build failure")
        time.sleep(0.2)
        return {"rows": [], "attempt": attempt}

    monkeypatch.setattr(J, "_load", flaky_load)
    results, errors = _run_threads(lambda: _snapshot(tmp_path, registry), 6)

    assert len(attempts) == 2, f"{len(attempts)} builds: the failed build must be retried exactly once"
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError), errors
    assert len(results) == 5
    assert all(r["attempt"] == 2 for r in results)
    assert not J._COLD, "the leader flag survived a failed build"


# ── unchanged behaviour ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_warm_body_is_served_without_a_build(tmp_path, monkeypatch):
    registry = _registry(tmp_path)
    builds = []
    monkeypatch.setattr(J, "_load", lambda *a, **k: builds.append(1) or {"rows": []})
    assert _snapshot(tmp_path, registry)["rows"] == []
    assert _snapshot(tmp_path, registry)["rows"] == []
    assert len(builds) == 1


def test_stale_while_revalidate_is_unchanged(tmp_path, monkeypatch):
    """A stale body is served at once and one background refresh runs — the cold path's fix must not alter it."""
    registry = _registry(tmp_path)
    release, builds = threading.Event(), []

    def load(root, registry_path, now, **extra):
        builds.append(time.monotonic())
        if len(builds) == 1:
            return {"rows": [], "version": 1}
        release.wait(10)
        return {"rows": [], "version": 2}

    monkeypatch.setattr(J, "_load", load)
    assert _snapshot(tmp_path, registry)["version"] == 1

    key = next(iter(J._CACHE))
    stamp, body = J._CACHE[key]
    J._CACHE[key] = (stamp - 120, body)  # older than CACHE_SECONDS

    assert _snapshot(tmp_path, registry)["version"] == 1, "a stale body is served immediately"
    assert _wait_for(lambda: len(builds) == 2), "the background refresh did not start"
    assert _snapshot(tmp_path, registry)["version"] == 1, "a second stale read must not start a second refresh"
    release.set()
    assert _wait_for(lambda: J._CACHE[key][1].get("version") == 2), "the refresh never landed"
    assert len(builds) == 2
