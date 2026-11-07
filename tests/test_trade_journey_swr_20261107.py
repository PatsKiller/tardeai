"""ANCHOR: TRADE_JOURNEY_SWR_20261107 — TradeInView serves the last good journey body and refreshes behind it.

LQ-20261107-217. ``/v3/trade-in-view`` sat on "Loading trade journeys…" until the browser gave up: the journey
projection is rebuilt inline on every request (11.4 s warm, 19.5 s cold on 2026-11-07). ``scripts/lib/stale_serve.py``
(LQ-20261107-201) now serves the previous body at once and refreshes in the background; this suite pins the wiring in
``scripts/api_v3_trade_journey.py``:

- a second call inside the fresh window never recomputes;
- a stale body is served at once, marked stale, and starts exactly **one** background refresh — a second stale
  caller while that refresh is in flight starts none;
- the refreshed body replaces the stale one (fresh again after the refresh lands);
- ``?fresh=1`` and ``TRADEAI_SWR=0`` bypass the layer, and a distinct query is a distinct entry;
- an ``ok: False`` body is never cached;
- the list body persists to disk (its own ``trade_journey_last_good`` store beside the server's SWR store) and is
  served after a restart; the per-trade detail body is memory-only and bounded, so one trade cannot mint a file per
  visit;
- without ``lib.stale_serve`` the module computes exactly as it did before (no cache, no error).

Hermetic: the projection is a counting fake, the clock and the background spawner are fakes, the store is a tmp
path. No database, no network, no broker, no production state (AGENTS.md §24.6).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.api_v3_trade_journey as aj  # noqa: E402
from lib.data_broker import trade_journey as tjm  # noqa: E402
from lib import stale_serve  # noqa: E402  -- the module the route resolves (and portfolio_server's too)


class _Clock:
    def __init__(self, t=1_900_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Spawner:
    """Collects background work so a test decides when it runs."""

    def __init__(self):
        self.jobs = []

    def __call__(self, fn):
        self.jobs.append(fn)

    def run_all(self):
        jobs, self.jobs = self.jobs, []
        for fn in jobs:
            fn()
        return len(jobs)


@pytest.fixture()
def journey(tmp_path, monkeypatch):
    """The route module with a tmp state root, no env kill switch, and no server carried between tests."""
    aj._reset()
    monkeypatch.delenv("TRADEAI_SWR", raising=False)
    monkeypatch.setattr(stale_serve, "default_store_dir", lambda: tmp_path / "swr_last_good")
    yield aj
    aj._reset()


@pytest.fixture()
def calls(monkeypatch):
    """A counting projection. ``detail`` counts under its own key so the two routes are measured apart."""
    counter = {"list": 0, "detail": 0}

    def list_trade_journeys(query=None):
        counter["list"] += 1
        return {"ok": True, "schema": "TradeJourneyList@v1", "journeys": [], "call": counter["list"],
                "days": (query or {}).get("days")}

    def detail_trade_journey(trade_id, query=None):
        counter["detail"] += 1
        return {"ok": True, "schema": "TradeJourney@v1", "trade_id": trade_id, "call": counter["detail"]}

    monkeypatch.setattr(tjm, "list_trade_journeys", list_trade_journeys)
    monkeypatch.setattr(tjm, "detail_trade_journey", detail_trade_journey)
    return counter


def _inject(kind, store, clock, spawn, *, fresh_s=60.0, max_stale_s=3600.0, max_entries=64):
    server = stale_serve.StaleServe(store, fresh_s=fresh_s, max_stale_s=max_stale_s, max_entries=max_entries,
                                    clock=clock, spawn=spawn)
    if kind == "list":
        aj._LIST_SWR = server
    else:
        aj._DETAIL_SWR = server
    return server


def test_a_second_call_inside_the_fresh_window_never_recomputes(journey, calls, tmp_path):
    clock, spawn = _Clock(), _Spawner()
    _inject("list", tmp_path / "list", clock, spawn)

    first = aj.get_list({"days": "30"})
    assert calls["list"] == 1
    assert first["_swr"]["stale"] is False and first["_swr"]["source"] == "computed"
    assert isinstance(first, dict), "the route returns a body, not a (status, body) tuple"

    clock.t += 30  # inside FRESH_S
    second = aj.get_list({"days": "30"})
    assert calls["list"] == 1, "a fresh body must not be recomputed"
    assert second["journeys"] == [] and second["_swr"]["stale"] is False
    assert second["_swr"]["age_s"] == 30.0


def test_a_stale_body_is_served_at_once_and_starts_exactly_one_refresh(journey, calls, tmp_path):
    clock, spawn = _Clock(), _Spawner()
    _inject("list", tmp_path / "list", clock, spawn)
    aj.get_list({"days": "30"})
    spawn.run_all()  # only the persistence of the first body
    assert calls["list"] == 1

    clock.t += 120  # past FRESH_S, inside MAX_STALE_S
    stale = aj.get_list({"days": "30"})
    assert calls["list"] == 1, "a stale body is served without recomputing in the request"
    assert stale["_swr"]["stale"] is True and stale["_swr"]["refreshing"] is True
    assert stale["_swr"]["source"] == "computed" and stale["call"] == 1
    assert len(spawn.jobs) == 1, "one background refresh"

    aj.get_list({"days": "30"})  # a second stale caller while the refresh is in flight
    assert len(spawn.jobs) == 1, "a second caller must not start a second refresh"

    clock.t += 1
    spawn.run_all()  # the refresh now runs, then persists its body
    assert calls["list"] == 2

    fresh_again = aj.get_list({"days": "30"})
    assert calls["list"] == 2, "the refreshed body is served fresh"
    assert fresh_again["call"] == 2 and fresh_again["_swr"]["stale"] is False


def test_fresh_query_bypasses_the_last_good_body(journey, calls, tmp_path):
    clock, spawn = _Clock(), _Spawner()
    _inject("list", tmp_path / "list", clock, spawn)
    aj.get_list({"days": "30"})
    assert calls["list"] == 1

    again = aj.get_list({"days": "30", "fresh": "1"})
    assert calls["list"] == 2, "?fresh=1 must recompute"
    assert again["call"] == 2 and "_swr" not in again, "a bypassed body is not stamped"


def test_tradeai_swr_zero_turns_the_layer_off(journey, calls, tmp_path, monkeypatch):
    clock, spawn = _Clock(), _Spawner()
    _inject("list", tmp_path / "list", clock, spawn)
    monkeypatch.setenv("TRADEAI_SWR", "0")

    aj.get_list({"days": "30"})
    aj.get_list({"days": "30"})
    assert calls["list"] == 2, "TRADEAI_SWR=0 must serve exactly as before, with no cache"


def test_two_queries_are_two_entries_and_the_cache_buster_is_not_one(journey, calls, tmp_path):
    clock, spawn = _Clock(), _Spawner()
    _inject("list", tmp_path / "list", clock, spawn)

    aj.get_list({"days": "30"})
    aj.get_list({"days": "90"})
    assert calls["list"] == 2, "days=30 and days=90 are different bodies"

    aj.get_list({"days": "30", "_": "one"})
    aj.get_list({"days": "30", "_": "two"})
    assert calls["list"] == 2, "the cache buster _ must not split the entry"


def test_an_ok_false_body_is_never_cached(journey, calls, tmp_path, monkeypatch):
    clock, spawn = _Clock(), _Spawner()
    _inject("list", tmp_path / "list", clock, spawn)
    monkeypatch.setattr(tjm, "list_trade_journeys", lambda query=None: {"ok": False, "error": "unavailable"})

    first = aj.get_list({"days": "30"})
    second = aj.get_list({"days": "30"})
    assert first == {"ok": False, "error": "unavailable"}
    assert second == {"ok": False, "error": "unavailable"}
    assert not (tmp_path / "list").exists() or not list((tmp_path / "list").glob("*.json"))


def test_the_list_body_survives_a_restart(journey, calls, tmp_path):
    clock, spawn = _Clock(), _Spawner()
    store = tmp_path / "trade_journey_last_good"
    _inject("list", store, clock, spawn)

    aj.get_list({"days": "30"})
    spawn.run_all()
    written = sorted(store.glob("*.json"))
    assert len(written) == 1, "the list body persists to its own store"
    assert written[0].stat().st_mode & 0o777 == 0o600

    # A new process: no memory, the same store.
    _inject("list", store, clock, spawn)
    clock.t += 30
    after_restart = aj.get_list({"days": "30"})
    assert calls["list"] == 1, "a restart serves the persisted body instead of recomputing"
    assert after_restart["_swr"]["source"] == "disk" and after_restart["call"] == 1


def test_the_detail_body_is_memory_only_and_bounded(journey, calls, tmp_path):
    clock, spawn = _Clock(), _Spawner()
    _inject("detail", None, clock, spawn, max_entries=4)

    aj.get_detail("open%3Aschwab_rollover_ira%3APFE")
    aj.get_detail("open%3Aschwab_rollover_ira%3APFE")
    aj.get_detail("open%3Aschwab_rollover_ira%3APFE")
    assert calls["detail"] == 1, "the detail body is cached in memory"
    assert aj._DETAIL_SWR.store_dir is None, "detail bodies are memory-only"
    assert not list(tmp_path.rglob("*.json")), "the detail route writes no cache file"

    detail = aj.get_detail("open%3Aschwab_rollover_ira%3APFE")
    assert detail["trade_id"] == "open:schwab_rollover_ira:PFE", "the trade id is percent-decoded"

    for i in range(6):  # more entries than the bound
        aj.get_detail(f"closed:trip:{i}")
    assert len(aj._DETAIL_SWR._mem) <= 4, "the memory-only detail cache stays bounded"


def test_the_layer_shares_the_servers_stale_serve_module(journey):
    """``lib/stale_serve.py`` and ``scripts/lib/stale_serve.py`` are two module objects for one file.

    The route (like portfolio_server's ``_coalesce_get``) resolves ``lib.stale_serve`` first. Pinning that here keeps
    one ``_DEFAULT`` singleton, one set of env-decided limits and one ``default_store_dir`` for both layers — a second
    module object would silently double the stores and ignore a patch applied to the other one.
    """
    from lib import stale_serve as lib_swr

    assert aj._swr() is lib_swr


def test_the_list_store_sits_beside_the_server_swr_store(journey, tmp_path):
    server = aj._server("list")
    assert server.store_dir == tmp_path / "trade_journey_last_good"
    assert server.store_dir.parent == tmp_path, "one runtime dir, not a second one"


def test_without_the_helper_the_route_behaves_as_before(journey, calls):
    aj._SWR_MODULE = False  # the tree does not carry scripts/lib/stale_serve.py
    aj._LIST_SWR = aj._DETAIL_SWR = None

    first = aj.get_list({"days": "30"})
    second = aj.get_list({"days": "30"})
    assert calls["list"] == 2, "no helper, no cache — exactly the pre-LQ-201 behaviour"
    assert "_swr" not in first and "_swr" not in second
    assert first["ok"] is True and second["ok"] is True


def test_an_unresolvable_state_root_serves_uncached_and_never_raises(journey, calls, monkeypatch):
    def _boom():
        raise RuntimeError("state root not configured")

    monkeypatch.setattr(stale_serve, "default_store_dir", _boom)

    first = aj.get_list({"days": "30"})
    second = aj.get_list({"days": "30"})
    assert calls["list"] == 2
    assert first["ok"] is True and "_swr" not in first and "_swr" not in second
