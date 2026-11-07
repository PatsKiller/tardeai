"""ANCHOR: WATCH_CURATION_SWR_20261107 — /v3/watch serves the last good curation body and refreshes behind it.

LQ-20261107-227. On 2026-11-07 the 14:43 ET page sweep measured "watch-curation aborted at 30 s" on
/v3/watch and /v3/watch-legacy: the endpoint was PENDING 24 s and the page still read "Loading your
watchlist…" at 25 s. The composition behind it (``lib.site_payload_reads.read_curation`` →
``lib.data_broker.watch_prospects.gather``) costs 8-11 s warm on this host, past the browser's 30 s
client limit once the sweep's own load is added.

The fix is the LQ-20261107-201 pattern (``scripts/lib/stale_serve.py``) applied at the data-broker
route: a last good body is served at once and ONE background refresh recomputes it.

Pinned here:
- a warm body is served from memory without recomputing;
- a stale body is served at once, marked stale with its as_of, and starts exactly one refresh;
- a failed read (the payload-gap ValueError) is never cached, so the page keeps the real error;
- the cache key carries the identity, so one operator's watchlist is never served to another, and an
  identity-less request (local listener, page walk) has its own bucket;
- a restart serves the persisted body instead of a cold 8-11 s compute;
- an explicitly requested body older than the limit is recomputed inline;
- the review-status read is not cached as if it were the curation body;
- the real resolver returns the module and the request principal, and returns nothing when SWR is off.

Hermetic: synthetic bodies, a fake clock and an inline spawner; no DB, no server, no network.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import api_v3_data_broker_watch as watchmod  # noqa: E402
from scripts.lib import stale_serve  # noqa: E402
from scripts.lib.stale_serve import StaleServe  # noqa: E402


class _Clock:
    def __init__(self, t=1_900_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


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


def _body(symbol: str, *, ok: bool = True, status: str = "ok") -> dict:
    return {"ok": ok, "status": status, "generated_at": "2026-11-07T19:00:00+00:00",
            "my_watchlist": {"rows": [{"symbol": symbol}], "count": 1}, "suggests": {"rows": [], "count": 0}}


@pytest.fixture()
def ctx(monkeypatch, tmp_path):
    """Route through a deterministic StaleServe and a fixed identity."""
    clock, spawner = _Clock(), _Spawner()
    svc = StaleServe(tmp_path / "swr", fresh_s=60.0, max_stale_s=3600.0, clock=clock, spawn=spawner)
    monkeypatch.setattr(stale_serve, "_DEFAULT", svc)
    monkeypatch.setattr(watchmod, "_swr_context", lambda: (stale_serve, "tailnet:operator", _noop))
    return svc, clock, spawner


def _noop(_principal):
    pass


def _reader(monkeypatch, fn):
    """Patch the composition behind the route; count the calls the route makes."""
    calls = []

    def wrapped(query):
        calls.append(dict(query))
        return fn(len(calls))

    monkeypatch.setattr("lib.site_payload_reads.read_curation", wrapped)
    return calls


def test_a_warm_body_is_served_without_recomputing(ctx, monkeypatch):
    svc, clock, _ = ctx

    def slow(_n):
        time.sleep(0.2)
        return _body("NVDA")

    calls = _reader(monkeypatch, slow)
    first = watchmod.get_curation({"view": "mine"})
    t0 = time.perf_counter()
    second = watchmod.get_curation({"view": "mine"})
    elapsed = time.perf_counter() - t0

    assert first["my_watchlist"]["rows"][0]["symbol"] == "NVDA"
    assert second["my_watchlist"]["rows"][0]["symbol"] == "NVDA"
    assert len(calls) == 1, "a warm body must not recompute"
    assert elapsed < 0.1, "the warm serve must not wait on the 0.2 s composition"
    assert second["_swr"]["stale"] is False
    assert second["_swr"]["age_s"] == 0.0
    assert second["_swr"]["refreshing"] is False
    assert svc.stats["computed"] == 1


def test_a_stale_body_is_served_at_once_and_one_refresh_runs(ctx, monkeypatch):
    svc, clock, spawner = ctx
    calls = _reader(monkeypatch, lambda n: _body("NVDA" if n == 1 else "AMD"))

    watchmod.get_curation({"view": "mine"})
    after_first = len(spawner.jobs)  # the persist job the first serve scheduled
    clock.t += 90  # past fresh_s, inside max_stale_s
    served = watchmod.get_curation({"view": "mine"})

    assert served["my_watchlist"]["rows"][0]["symbol"] == "NVDA", "the stale body is served, not waited on"
    assert served["_swr"]["stale"] is True
    assert served["_swr"]["refreshing"] is True
    assert served["_swr"]["age_s"] == 90.0
    assert len(spawner.jobs) - after_first == 1, "exactly one refresh per key"

    again = watchmod.get_curation({"view": "mine"})
    assert len(spawner.jobs) - after_first == 1, "a second caller must not start another refresh"
    assert again["_swr"]["refreshing"] is True

    spawner.run_all()  # the refresh finishes
    assert len(calls) == 2
    after = watchmod.get_curation({"view": "mine"})
    assert after["my_watchlist"]["rows"][0]["symbol"] == "AMD"
    assert after["_swr"]["stale"] is False


def test_a_failed_read_is_never_cached(ctx, monkeypatch):
    def unavailable(_n):
        raise ValueError("Curation payload unavailable: watch_prospects projection missing")

    calls = _reader(monkeypatch, unavailable)
    with pytest.raises(ValueError, match="payload unavailable"):
        watchmod.get_curation({"view": "mine"})
    with pytest.raises(ValueError):
        watchmod.get_curation({"view": "mine"})
    assert len(calls) == 2, "an error must not be served from the cache"


def test_an_unavailable_status_is_never_cached(ctx, monkeypatch):
    """read_curation can also answer 200 with status=unavailable; that is the same failure, not a body."""
    calls = _reader(monkeypatch, lambda n: {"ok": False, "status": "unavailable",
                                            "payload_gap": {"reason": "no projection"}})
    with pytest.raises(ValueError):
        watchmod.get_curation({})
    with pytest.raises(ValueError):
        watchmod.get_curation({})
    assert len(calls) == 2


def test_the_key_carries_the_identity(ctx, monkeypatch):
    svc, _, _ = ctx
    seen = []

    def per_identity(principal):
        watchmod._swr_context = lambda: (stale_serve, principal, _noop)

    calls = _reader(monkeypatch, lambda n: _body("NVDA" if n == 1 else "AMD"))

    per_identity("tailnet:first")
    first = watchmod.get_curation({})
    per_identity("tailnet:second")
    second = watchmod.get_curation({})

    seen.extend(r["my_watchlist"]["rows"][0]["symbol"] for r in (first, second))
    assert seen == ["NVDA", "AMD"], "one identity must never be served another's body"
    assert len(calls) == 2


def test_an_identity_less_request_has_its_own_bucket(ctx, monkeypatch):
    calls = _reader(monkeypatch, lambda n: _body("NVDA"))
    watchmod._swr_context = lambda: (stale_serve, "", _noop)

    watchmod.get_curation({})
    watchmod.get_curation({})  # same anonymous bucket, served warm
    assert len(calls) == 1

    watchmod._swr_context = lambda: (stale_serve, "tailnet:operator", _noop)
    watchmod.get_curation({})  # a different identity: its own body
    assert len(calls) == 2


def test_a_restart_serves_the_persisted_body(ctx, monkeypatch):
    svc, clock, spawner = ctx
    calls = _reader(monkeypatch, lambda n: _body("NVDA"))
    watchmod.get_curation({})
    spawner.run_all()  # the persist job the serve scheduled
    assert len(calls) == 1

    # A new process: same store dir, empty memory.
    restarted = StaleServe(svc.store_dir, fresh_s=60.0, max_stale_s=3600.0, clock=clock, spawn=_Spawner())
    monkeypatch.setattr(stale_serve, "_DEFAULT", restarted)
    served = watchmod.get_curation({})
    assert served["my_watchlist"]["rows"][0]["symbol"] == "NVDA"
    assert served["_swr"]["source"] == "disk"
    assert len(calls) == 1, "a restart must not compute inline"


def test_a_body_older_than_the_limit_is_recomputed(ctx, monkeypatch):
    svc, clock, _ = ctx
    calls = _reader(monkeypatch, lambda n: _body(f"SYM{n}"))
    watchmod.get_curation({})
    clock.t += 3601  # past max_stale_s
    served = watchmod.get_curation({})
    assert served["my_watchlist"]["rows"][0]["symbol"] == "SYM2"
    assert served["_swr"]["source"] == "computed"
    assert len(calls) == 2


def test_the_review_status_read_is_not_cached_as_curation(ctx, monkeypatch):
    svc, _, _ = ctx
    calls = _reader(monkeypatch, lambda n: _body("NVDA"))
    reviews = []

    def review_status(query):
        reviews.append(dict(query))
        return {"ok": True, "rows": []}

    monkeypatch.setattr("lib.data_broker.watch_review_status.review_status", review_status)
    out = watchmod.get_curation({"review_status": "1", "symbols": "NVDA,AMD"})
    assert out == {"ok": True, "rows": []}
    assert reviews == [{"review_status": "1", "symbols": "NVDA,AMD"}]
    assert calls == [], "the review-status projection is not the curation body"
    assert svc.stats["computed"] == 0


def test_the_real_resolver_returns_the_module_and_the_principal(monkeypatch):
    from lib import stale_serve as production_module  # the module the route itself imports

    monkeypatch.delenv("TRADEAI_SWR", raising=False)
    mod, principal, setter = watchmod._swr_context()
    assert mod is production_module
    assert isinstance(principal, str)
    assert callable(setter)


def test_the_real_resolver_is_off_when_swr_is_off(monkeypatch):
    monkeypatch.setenv("TRADEAI_SWR", "0")
    assert watchmod._swr_context() == (None, "", None)
