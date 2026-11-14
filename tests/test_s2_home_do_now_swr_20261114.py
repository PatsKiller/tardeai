"""S2 Home cold: the Do-now GET must never pay the ~5 s eight-probe build once a body exists.

Measured on the live server 2026-11-14 (scripts/s2_home_cold_rss.py, two runs): the first ``/api/v2/home/do-now``
after the 60 s cache expired took **5.05 s / 5.08 s**, while the warm read took 2.6-5.1 ms. The rebuild ran on the
request thread, so every Home open that arrived at an expired cache waited for it — the "no heavy rebuild in GET"
class the sprint exists to remove.

The fix (PATCH-S2-home-do-now-swr-...patch, api_v2.py only): an expired body is served as last-known-good — every
source in it carries its own as_of/age, so the older clock is visible — and exactly ONE daemon thread rebuilds the
cache. Only the first-ever call (no body at all) builds synchronously.

Red on a tree without the patch (the expired read would block for the fake build's full duration and return the NEW
body), green with it. Hermetic: the build is faked; no DB, no network, no server.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ANCHOR = "S2_PRODUCERS_PERF"


@pytest.fixture()
def api(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_HOME_DO_NOW_CACHE", {}, raising=True)
    # The single rebuild slot and its last-attempt record are module state too; reset them so one test cannot inherit a
    # held lock or a retry cooldown from another.
    monkeypatch.setattr(api_v2, "_HOME_DO_NOW_REFRESHING", __import__("threading").Lock(), raising=False)
    monkeypatch.setattr(api_v2, "_HOME_DO_NOW_REFRESH",
                        {"attempted_at": None, "failed_at": None, "error": None, "_failed_mono": None}, raising=False)
    return api_v2


def _seed(api, age_s: float, body: dict) -> None:
    api._HOME_DO_NOW_CACHE["v"] = (time.monotonic() - age_s, body)


def test_a_fresh_body_is_served_without_a_build(api, monkeypatch):
    called = []
    monkeypatch.setattr(api, "_home_do_now_build", lambda: called.append(1) or {"fresh": True}, raising=False)
    _seed(api, 5.0, {"cached": True})
    assert api._home_do_now({}) == {"cached": True}
    assert called == [], "a body younger than 60 s must not trigger a build"


def test_an_expired_body_is_served_immediately_and_rebuilt_behind_the_reader(api, monkeypatch):
    """The operator-facing property: the request does not wait for the rebuild, and the old body is what it gets."""
    calls = []

    def slow_build():  # plays the real builder, including its one documented side effect: it writes the cache
        calls.append(1)
        time.sleep(0.8)
        body = {"cached": False, "rebuilt": True}
        api._HOME_DO_NOW_CACHE["v"] = (time.monotonic(), body)
        return body

    monkeypatch.setattr(api, "_home_do_now_build", slow_build, raising=False)
    _seed(api, 120.0, {"cached": True})
    t0 = time.monotonic()
    body = api._home_do_now({})
    elapsed = time.monotonic() - t0
    assert body["cached"] is True, "an expired read must be answered with the last-known-good body"
    assert body["served"]["stale"] is True and body["served"]["age_s"] >= 120, "a stale read must say it is stale"
    assert elapsed < 0.2, f"the request waited {elapsed:.3f}s for the rebuild — the build is still on the read path"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and api._HOME_DO_NOW_CACHE["v"][1] != {"cached": False, "rebuilt": True}:
        time.sleep(0.02)
    assert calls == [1], "exactly one background rebuild"
    assert api._HOME_DO_NOW_CACHE["v"][1] == {"cached": False, "rebuilt": True}, "the rebuild did not land in the cache"


def test_a_poll_burst_on_an_expired_body_starts_exactly_one_rebuild(api, monkeypatch):
    calls = []

    def slow_build():
        calls.append(time.monotonic())
        time.sleep(0.5)
        body = {"rebuilt": True}
        api._HOME_DO_NOW_CACHE["v"] = (time.monotonic(), body)
        return body

    monkeypatch.setattr(api, "_home_do_now_build", slow_build, raising=False)
    _seed(api, 120.0, {"cached": True})
    burst = [api._home_do_now({}) for _ in range(3)]
    assert [b["cached"] for b in burst] == [True] * 3, "every reader in the burst is answered with last-known-good"
    assert all(b["served"]["stale"] is True for b in burst)
    time.sleep(1.2)  # let the single rebuild finish
    assert len(calls) == 1, f"a burst started {len(calls)} rebuilds — the refresh is not deduplicated"
    assert api._HOME_DO_NOW_CACHE["v"][1] == {"rebuilt": True}


def test_the_first_ever_call_builds_synchronously_and_caches(api, monkeypatch):
    def build():
        time.sleep(0.3)
        body = {"first": True}
        api._HOME_DO_NOW_CACHE["v"] = (time.monotonic(), body)
        return body

    monkeypatch.setattr(api, "_home_do_now_build", build, raising=False)
    api._HOME_DO_NOW_CACHE.clear()
    t0 = time.monotonic()
    body = api._home_do_now({})
    elapsed = time.monotonic() - t0
    assert body == {"first": True}
    assert elapsed >= 0.25, "with no body at all the first call must build (there is nothing to serve)"
    assert api._HOME_DO_NOW_CACHE["v"][1] == {"first": True}, "the first build must seed the cache"


def test_a_failed_background_rebuild_keeps_the_last_good_body_and_names_the_reason(api, monkeypatch, capsys):
    def boom():
        raise RuntimeError("synthetic rebuild failure")

    monkeypatch.setattr(api, "_home_do_now_build", boom, raising=False)
    _seed(api, 120.0, {"cached": True})
    assert api._home_do_now({})["cached"] is True
    time.sleep(0.3)
    out = capsys.readouterr().out
    assert "background rebuild failed" in out and "synthetic rebuild failure" in out, "a failed rebuild must be named"
    assert api._HOME_DO_NOW_CACHE["v"][1] == {"cached": True}, "a failed rebuild must not clear the last-good body"
    # and the slot is released, so the next expired read can try again
    assert api._HOME_DO_NOW_REFRESHING.acquire(blocking=False), "the refresh lock leaked after a failed rebuild"
    api._HOME_DO_NOW_REFRESHING.release()


def test_the_expired_path_cannot_call_build_inline_in_the_source():
    """Source teeth as well as behaviour: the FIRST-EVER path may build, the EXPIRED path may not."""
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    start = src.index("def _home_do_now(")
    end = src.index("def _home_do_now_build(", start)
    body = src[start:end]
    assert "_home_do_now_refresh_in_background()" in body, "the expired path must schedule the background rebuild"
    # the expired branch sits between its comment and the first-ever build call; it may return only a COPY of the cache
    expired = body[body.index("if hit:"):body.index("return _home_do_now_build()")]
    assert "_home_do_now_build()" not in expired, f"the expired path builds inline: {expired}"
    assert expired.count('return {**hit[1], "served"') == 1, "the expired path must answer with a copy of last-good"
    assert body.index("_home_do_now_refresh_in_background()") < body.index("return _home_do_now_build()")
    assert ANCHOR  # greppable anchor; see config/ci_gates/S2_PRODUCERS_PERF_20261114.json


# ── review 6888bda645 (cc-deepseek-2) F1/F2, 2026-11-14 ───────────────────────────────────────────────────────────────

def test_a_refresh_thread_that_cannot_start_frees_the_slot_and_the_read_still_answers(api, monkeypatch):
    """F1: `can't start new thread` used to leave the lock held forever and raise out of the route — one 500, then no
    rebuild ever again with no record. The slot must be free and the read must still return last-known-good."""
    import types
    import threading as _th

    class _NoThread:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(api, "threading", types.SimpleNamespace(Thread=_NoThread, Lock=_th.Lock), raising=False)
    _seed(api, 120.0, {"cached": True})
    body = api._home_do_now({})  # must not raise
    assert body["cached"] is True and body["served"]["stale"] is True, "the read must still be answered"
    assert "could not start" in (body["served"]["refresh"]["error"] or ""), "the failed start must be named on the wire"
    assert api._HOME_DO_NOW_REFRESHING.acquire(blocking=False), "the refresh slot leaked when the thread could not start"
    api._HOME_DO_NOW_REFRESHING.release()


def test_a_failed_rebuild_is_named_on_the_next_stale_read_and_the_cache_is_never_mutated(api, monkeypatch, capsys):
    """F2: a stale body must not be published as plain OK with a stale as_of and nothing else."""
    def boom():
        raise RuntimeError("synthetic rebuild failure")

    monkeypatch.setattr(api, "_home_do_now_build", boom, raising=False)
    _seed(api, 7200.0, {"cached": True, "as_of": "2026-11-14T13:00:00+00:00"})
    first = api._home_do_now({})
    assert first["served"]["age_s"] >= 7200, "the age of the served body must be on the wire"
    assert first["cached"] is True and first["as_of"] == "2026-11-14T13:00:00+00:00", "the old clock is still stated"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and api._HOME_DO_NOW_REFRESH.get("failed_at") is None:
        time.sleep(0.02)
    second = api._home_do_now({})
    refresh = second["served"]["refresh"]
    assert refresh["failed_at"] and "synthetic rebuild failure" in refresh["error"], \
        f"a failing Home refresh must name itself on the wire: {refresh}"
    assert refresh["attempted_at"] is not None
    assert "served" not in api._HOME_DO_NOW_CACHE["v"][1], "the cached body was mutated by serving it"
    capsys.readouterr()


def test_a_failed_rebuild_is_not_retried_before_the_cooldown(api, monkeypatch):
    """F2: retry at Home poll cadence is unbounded work against a broken build; the cooldown bounds it."""
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("synthetic rebuild failure")

    monkeypatch.setattr(api, "_home_do_now_build", boom, raising=False)
    _seed(api, 120.0, {"cached": True})
    api._home_do_now({})
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and len(calls) < 1:
        time.sleep(0.02)
    while api._HOME_DO_NOW_REFRESHING.locked():  # let the failed attempt record its clock
        time.sleep(0.02)
    for _ in range(3):
        api._home_do_now({})
    assert len(calls) == 1, f"a broken build was retried {len(calls)}x inside the cooldown"
    api._HOME_DO_NOW_REFRESH["_failed_mono"] = time.monotonic() - api._HOME_DO_NOW_RETRY_COOLDOWN_S - 1
    api._home_do_now({})
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and len(calls) < 2:
        time.sleep(0.02)
    assert len(calls) == 2, "past the cooldown a failed build must be retried (never stale-forever with no attempt)"
