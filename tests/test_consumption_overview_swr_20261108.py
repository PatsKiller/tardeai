"""ANCHOR: CONSUMPTION_OVERVIEW_SWR_20261108 — /v3/consumption serves the last good overview body and
refreshes behind it (LQ-20261107-822).

On 2026-11-08 the page sweep measured ``/api/v2/consumption/overview`` at 3.8-4.3 s normally and 16.9 s
at load average 27, with no cache of any kind: every GET recomputed the whole body inside the request.
Profiled read-only on the served head (f32d0a0eb), the cold compute is dominated by
``lib.anthropic_monitoring._events`` re-parsing the 114 MB ``provider_cost/events.jsonl`` (617-1262 ms of
CPU per miss), plus ``CreditBook._read`` on the 8.5 MB credit journal (223 ms) and the four
``llm_consumption_log`` aggregates (70-210 ms). ``_events`` memoises on a whole-file fingerprint, and the
file is appended continuously, so in the live server that parse repeated on nearly every request.

The fix is the LQ-20261107-201 / LQ-20261107-219 pattern already in production: the route joins
``stale_serve.DEFAULT_SWR_PATHS`` (last good body served at once, one background refresh) and
``request_coalesce.DEFAULT_COALESCE_PATHS`` (single-flight identical callers).

Pinned here:
- the route is on both allowlists, with a 300 s staleness cap (a spend page, not a price page);
- a warm body is served from memory without recomputing;
- a stale body is served at once, marked stale with its as_of, and starts exactly one refresh, whose
  result replaces it;
- an error answer is never cached, so the page keeps the real failure;
- a body older than the 5 minute cap is recomputed inline even though the global window is 6 h;
- the operator's own consumption writes (process-mode, stop-advisory, run-manual, caller-priorities)
  drop the cached body, so the next read computes with the write in it;
- two identical callers share one compute.

Hermetic: synthetic bodies, a fake clock and an inline spawner; no DB, no server, no network.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import request_coalesce, stale_serve  # noqa: E402
from lib.stale_serve import StaleServe  # noqa: E402

ROUTE = "/api/v2/consumption/overview"
STALE_CAP_S = 300.0


class _Clock:
    def __init__(self, t=1_900_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _Spawner:
    """Collects background work so the test decides when it runs."""

    def __init__(self):
        self.jobs = []

    def __call__(self, fn):
        self.jobs.append(fn)

    def run_all(self):
        jobs, self.jobs = self.jobs, []
        for fn in jobs:
            fn()


def _body(tag: str, *, status: int = 200) -> tuple:
    return status, {"ok": status == 200, "overview": {"by_lane": {"anthropic": tag}},
                    "lanes": [], "insights": [], "tag": tag}


def _dispatch(*tags, status: int = 200):
    calls = []

    def fn():
        calls.append(1)
        tag = tags[min(len(calls), len(tags)) - 1]
        return _body(tag, status=status)
    fn.calls = calls
    return fn


def _svc(tmp_path, clock, spawner) -> StaleServe:
    return StaleServe(tmp_path / "swr", fresh_s=60.0, max_stale_s=6 * 3600.0,
                      clock=clock, spawn=spawner)


# ── the allowlist entries ────────────────────────────────────────────────────────────────────────────
def test_route_is_on_the_swr_allowlist():
    assert ROUTE in stale_serve.DEFAULT_SWR_PATHS
    assert stale_serve.is_swr_path(ROUTE)
    assert stale_serve.is_swr_path(ROUTE + "?_=1712345678901"), "a cache-buster must not fall off the allowlist"
    assert stale_serve.is_swr_path(ROUTE + "/")


def test_the_route_is_bounded_to_five_minutes_of_staleness():
    assert stale_serve.PATH_MAX_STALE_S[ROUTE] == STALE_CAP_S
    assert STALE_CAP_S < stale_serve.MAX_STALE_S, "a spend page never borrows the global 6 h window"


def test_route_is_coalesced():
    assert ROUTE in request_coalesce.DEFAULT_COALESCE_PATHS
    assert request_coalesce.request_key(ROUTE, {}, "tailnet:operator") is not None


def test_neighbouring_routes_are_not_pulled_in():
    """The write-invalidation marker is the consumption subtree only."""
    assert "/api/v2/consumption/overview" in stale_serve.WRITE_INVALIDATES
    assert "/api/v2/watchlist/items" in stale_serve.WRITE_INVALIDATES, "the watchlist mapping still stands"


# ── serving behaviour ────────────────────────────────────────────────────────────────────────────────
def test_warm_body_is_served_without_recomputing(tmp_path):
    clock, spawner = _Clock(), _Spawner()
    svc, fn = _svc(tmp_path, clock, spawner), _dispatch("a")
    first = svc.get("p|" + ROUTE + "?", fn)
    second = svc.get("p|" + ROUTE + "?", fn)
    assert len(fn.calls) == 1, "a warm hit must not recompute"
    assert first[1]["_swr"]["source"] == "computed" and first[1]["_swr"]["stale"] is False
    assert second[1]["_swr"]["stale"] is False
    assert svc.stats["fresh"] == 1 and svc.stats["computed"] == 1
    assert second[1]["tag"] == "a"


def test_stale_body_served_at_once_with_one_refresh(tmp_path):
    clock, spawner = _Clock(), _Spawner()
    svc = _svc(tmp_path, clock, spawner)
    fn = _dispatch("old", "new")
    svc.get("p|" + ROUTE + "?", fn)
    spawner.run_all()  # drain the initial persist job so only refreshes are counted below
    clock.advance(120)  # past fresh_s (60 s), inside the 300 s cap
    a = svc.get("p|" + ROUTE + "?", fn)
    b = svc.get("p|" + ROUTE + "?", fn)
    assert a[1]["tag"] == b[1]["tag"] == "old", "nobody waits for the refresh"
    assert a[1]["_swr"]["stale"] is True and a[1]["_swr"]["age_s"] == 120.0
    assert a[1]["_swr"]["refreshing"] is True
    assert len(spawner.jobs) == 1, "exactly one background refresh"
    assert len(fn.calls) == 1
    spawner.run_all()
    assert svc.get("p|" + ROUTE + "?", fn)[1]["tag"] == "new"


def test_error_is_never_cached(tmp_path):
    clock, spawner = _Clock(), _Spawner()
    svc = _svc(tmp_path, clock, spawner)
    bad = _dispatch("boom", status=500)
    assert svc.get("p|" + ROUTE + "?", bad)[0] == 500
    assert svc.get("p|" + ROUTE + "?", bad)[0] == 500
    assert len(bad.calls) == 2, "a failed answer must reach the page again, not be pinned"


def test_body_older_than_the_cap_is_recomputed_inline(tmp_path):
    clock, spawner = _Clock(), _Spawner()
    svc = _svc(tmp_path, clock, spawner)
    fn = _dispatch("old", "new")
    svc.get("p|" + ROUTE + "?", fn)
    clock.advance(STALE_CAP_S + 1)  # 5 min + 1 s, well inside the 6 h global window
    out = svc.get("p|" + ROUTE + "?", fn)
    assert len(fn.calls) == 2, "past the cap the body is recomputed, not served stale"
    assert out[1]["tag"] == "new" and out[1]["_swr"]["stale"] is False


def test_a_consumption_write_drops_the_cached_body(tmp_path):
    clock, spawner = _Clock(), _Spawner()
    svc = _svc(tmp_path, clock, spawner)
    fn = _dispatch("before", "after")
    svc.get("p|" + ROUTE + "?", fn)
    clock.advance(1)
    hit = stale_serve.invalidate_for_write("/api/v2/consumption/process-mode", server=svc)
    assert hit == [ROUTE]
    out = svc.get("p|" + ROUTE + "?", fn)
    assert len(fn.calls) == 2, "a read after the write computes with it"
    assert out[1]["tag"] == "after"


def test_an_unrelated_write_does_not_drop_it(tmp_path):
    clock, spawner = _Clock(), _Spawner()
    svc = _svc(tmp_path, clock, spawner)
    fn = _dispatch("a")
    svc.get("p|" + ROUTE + "?", fn)
    hit = stale_serve.invalidate_for_write("/api/v2/watchlist/items", server=svc)
    assert ROUTE not in hit, "a watchlist write does not drop the consumption body"
    svc.get("p|" + ROUTE + "?", fn)
    assert len(fn.calls) == 1


# ── the real server wiring ───────────────────────────────────────────────────────────────────────────
def test_server_get_path_serves_the_last_good_body(tmp_path, monkeypatch):
    """portfolio_server._coalesce_get is what turns the allowlist entry into a served body."""
    import portfolio_server
    from lib import cc_auth, request_coalesce as rc

    clock, spawner = _Clock(), _Spawner()
    svc = _svc(tmp_path, clock, spawner)
    monkeypatch.setattr(stale_serve, "_DEFAULT", svc)
    monkeypatch.setattr(cc_auth, "current_principal", lambda: "tailnet:operator")
    monkeypatch.setattr(cc_auth, "set_request_principal", lambda _p: None)
    monkeypatch.setattr(rc, "COALESCE_PATHS", frozenset())  # isolate SWR from the 2 s single-flight window

    fn = _dispatch("a")
    first = portfolio_server._coalesce_get(ROUTE, {}, fn)
    second = portfolio_server._coalesce_get(ROUTE, {}, fn)
    assert first[0] == 200 and second[0] == 200
    assert len(fn.calls) == 1, "the second page load is served from the cache"
    assert second[1]["_swr"]["stale"] is False
    assert svc.stats["fresh"] == 1 and svc.stats["computed"] == 1


def test_two_callers_share_one_compute():
    """The coalesce entry: identical in-flight callers do not each pay the ~1 s cold compute."""
    calls = []
    started = threading.Event()
    gate = threading.Event()

    def fn():
        calls.append(1)
        started.set()
        gate.wait(5)
        return (200, {"ok": True})

    c = request_coalesce.Coalescer(ttl=0.0, wait_s=5.0)
    out = {}

    def leader():
        out["a"] = request_coalesce.coalesce_get(ROUTE, {}, fn, principal="tailnet:operator", coalescer=c)

    t = threading.Thread(target=leader)
    t.start()
    assert started.wait(5), "the leader started its compute"
    gate.set()  # release it only after the follower is in flight
    assert request_coalesce.coalesce_get(ROUTE, {}, fn, principal="tailnet:operator", coalescer=c) == (200, {"ok": True})
    t.join(5)
    assert out["a"] == (200, {"ok": True})
    assert len(calls) == 1, "the second caller joined the first compute"
