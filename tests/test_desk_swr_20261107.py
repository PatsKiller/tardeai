"""ANCHOR: DESK_SWR_20261107 — desk reads serve the last good body and refresh in the background.

LQ-20261107-201. On 2026-11-07 the desk pages showed "unavailable": their reads took 16-44 s
warm (``/api/v2/defense/engine`` 44 s, ``/api/v2/portfolio/holdings`` 20 s) against a 30 s
browser limit, because every request recomputed the projection inside the request. Holdings
was also slow because ``cio_company_facts.load_snapshot`` re-parsed the whole ~400 MB
InstrumentRecord store on every call (4.2 s of a 4.5 s resolve).

Pinned here:
- a miss computes inline once; a fresh hit never computes;
- a stale hit is served at once, marked stale with its as_of, and starts exactly one
  background refresh; the refreshed body replaces it;
- errors and non-200 answers are never cached; a failed refresh keeps the last good body;
- a restart serves the persisted body (0600) instead of a cold compute, only to the same key;
- the facts snapshot is memoised per store file and recomputed after an append.

Hermetic: synthetic bodies and records, a fake clock and an inline spawner; no DB, no server.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import request_coalesce, stale_serve  # noqa: E402
from scripts.lib.stale_serve import StaleServe  # noqa: E402


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


def _counter(*bodies):
    calls = []

    def fn():
        calls.append(1)
        b = bodies[min(len(calls), len(bodies)) - 1]
        return b if isinstance(b, tuple) else (200, b)
    fn.calls = calls
    return fn


def _swr(tmp_path=None, **kw):
    clock, spawn = _Clock(), _Spawner()
    s = StaleServe(tmp_path, clock=clock, spawn=spawn, fresh_s=60, max_stale_s=3600, **kw)
    return s, clock, spawn


def test_miss_computes_inline_and_stamps_as_of():
    s, clock, spawn = _swr()
    fn = _counter({"ok": True, "v": 1})
    status, body = s.get("k", fn)
    assert status == 200 and body["v"] == 1 and len(fn.calls) == 1
    assert body["_swr"]["source"] == "computed" and body["_swr"]["stale"] is False
    assert body["_swr"]["as_of"].startswith("2030-")


def test_fresh_hit_never_computes():
    s, clock, spawn = _swr()
    fn = _counter({"ok": True, "v": 1})
    s.get("k", fn)
    clock.t += 59
    _, body = s.get("k", fn)
    assert len(fn.calls) == 1 and body["_swr"]["stale"] is False and body["_swr"]["age_s"] == 59
    assert spawn.jobs == [] or all(callable(j) for j in spawn.jobs)


def test_stale_hit_serves_at_once_and_refreshes_once_in_background():
    s, clock, spawn = _swr()
    fn = _counter({"ok": True, "v": 1}, {"ok": True, "v": 2})
    s.get("k", fn)
    spawn.run_all()  # the persist job (memory-only here)
    clock.t += 120
    _, b1 = s.get("k", fn)
    _, b2 = s.get("k", fn)  # a second caller while the refresh is pending
    assert b1["v"] == 1 and b1["_swr"]["stale"] is True and b1["_swr"]["refreshing"] is True
    assert b2["v"] == 1
    assert len(fn.calls) == 1  # nothing computed inside the request
    assert len(spawn.jobs) == 1  # exactly one refresh started
    spawn.run_all()
    _, b3 = s.get("k", fn)
    assert len(fn.calls) == 2 and b3["v"] == 2 and b3["_swr"]["stale"] is False


def test_errors_and_non_200_are_never_cached():
    s, clock, spawn = _swr()
    bad = _counter((503, {"ok": False, "error": "busy"}))
    assert s.get("k", bad) == (503, {"ok": False, "error": "busy"})
    s.get("k", bad)
    assert len(bad.calls) == 2
    falsy = _counter({"ok": False, "error": "x"})
    s.get("j", falsy)
    s.get("j", falsy)
    assert len(falsy.calls) == 2


def test_failed_refresh_keeps_last_good_and_names_the_error():
    s, clock, spawn = _swr()
    good = _counter({"ok": True, "v": 1})
    s.get("k", good)
    clock.t += 120

    def boom():
        raise TimeoutError("slow")
    s.get("k", good, boom)
    spawn.run_all()
    _, body = s.get("k", good, boom)
    assert body["v"] == 1 and body["_swr"]["last_refresh_error"] == "TimeoutError"
    assert s.stats["refresh_failed"] == 1


def test_restart_serves_the_persisted_body_instead_of_a_cold_compute(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get("tailnet:op|/api/v2/desks/agents?", _counter({"ok": True, "v": 1}))
    old_umask = os.umask(0o022)  # a permissive umask must not widen the cached holdings body
    try:
        spawn.run_all()
    finally:
        os.umask(old_umask)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert stat.S_IMODE(os.stat(files[0]).st_mode) == 0o600
    # A new process: empty memory, same directory.
    s2, clock2, spawn2 = _swr(tmp_path)
    clock2.t = clock.t + 300
    cold = _counter({"ok": True, "v": 2})
    _, body = s2.get("tailnet:op|/api/v2/desks/agents?", cold)
    assert cold.calls == [] and body["v"] == 1
    assert body["_swr"]["source"] == "disk" and body["_swr"]["stale"] is True and body["_swr"]["age_s"] == 300
    spawn2.run_all()
    assert len(cold.calls) == 1


def test_disk_copy_is_only_served_to_its_own_key(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get("tailnet:a|/api/v2/portfolio/holdings?", _counter({"ok": True, "who": "a"}))
    spawn.run_all()
    s2, _, _ = _swr(tmp_path)
    other = _counter({"ok": True, "who": "b"})
    _, body = s2.get("tailnet:b|/api/v2/portfolio/holdings?", other)
    assert body["who"] == "b" and len(other.calls) == 1
    # A file whose recorded key differs (hash collision, tampering) is ignored.
    f = next(tmp_path.glob("*.json"))
    doc = json.loads(f.read_text())
    doc["key"] = "tailnet:z|/x?"
    f.write_text(json.dumps(doc))
    s3, _, _ = _swr(tmp_path)
    again = _counter({"ok": True, "who": "a2"})
    assert s3.get("tailnet:a|/api/v2/portfolio/holdings?", again)[1]["who"] == "a2"


def test_too_old_disk_copy_is_recomputed_inline(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get("k", _counter({"ok": True, "v": 1}))
    spawn.run_all()
    s2, clock2, _ = _swr(tmp_path)
    clock2.t = clock.t + 3601
    fn = _counter({"ok": True, "v": 2})
    _, body = s2.get("k", fn)
    assert body["v"] == 2 and len(fn.calls) == 1 and body["_swr"]["source"] == "computed"


def test_each_caller_gets_its_own_top_level_and_data_dicts():
    s, clock, spawn = _swr()
    s.get("k", _counter({"ok": True, "data": {"__etag__": "e1", "rows": [1]}}))
    _, a = s.get("k", lambda: None)
    a["_serving"] = {"x": 1}
    a["data"].pop("__etag__")
    _, b = s.get("k", lambda: None)
    assert "_serving" not in b and b["data"]["__etag__"] == "e1"


def test_allowlist_covers_the_slow_desk_reads_and_ignores_cache_busters(monkeypatch):
    for p in ("/api/v2/desks/agents", "/api/v2/desks/defense", "/api/v2/desks/reentry",
              "/api/v2/defense/engine", "/api/v2/portfolio/holdings", "/api/v3/advisory", "/api/v3/cio/home"):
        assert stale_serve.is_swr_path(p), p
        assert p in request_coalesce.COALESCE_PATHS, p  # a cold compute is single-flight too
    assert not stale_serve.is_swr_path("/api/v2/orders")
    assert stale_serve.request_key("/x", {"_": "1", "a": "2"}, "p") == stale_serve.request_key("/x", {"a": "2"}, "p")
    assert stale_serve.request_key("/x", {}, "p1") != stale_serve.request_key("/x", {}, "p2")
    monkeypatch.setenv("TRADEAI_SWR", "0")
    assert not stale_serve.is_swr_path("/api/v2/desks/agents")


def test_server_routes_slow_reads_through_stale_serve_with_the_principal():
    src = (ROOT / "scripts" / "portfolio_server.py").read_text()
    fn = src[src.index("def _coalesce_get("):src.index("def _peer_closed(")]
    assert "_swr.is_swr_path(path)" in fn
    assert "set_request_principal(principal)" in fn  # the background refresh keeps the caller's identity
    assert "swr.get(_swr.request_key(path, query, principal), run, refresh)" in fn


# --------------------------------------------------------------- facts snapshot memo
def _record(guid, symbol, n):
    from scripts.lib.cio_company_facts import SCHEMA
    return {"subject_key": f"SEC:{guid}", "kind": "SECURITY", "security_guid": guid, "symbol": symbol,
            "research": {"company_facts": {"schema": SCHEMA, "security_guid": guid, "symbol": symbol,
                                           "status": "AVAILABLE", "summary": f"synthetic {n}"}}}


def test_facts_snapshot_is_memoised_until_the_store_changes(tmp_path, monkeypatch):
    from scripts.lib.data_broker import cio_company_facts as cf
    store = tmp_path / "data" / "cio" / "cio_instrument_records.jsonl"
    store.parent.mkdir(parents=True)
    tmp = store.with_suffix(".tmp")
    tmp.write_text(json.dumps(_record("g-1", "ZZQA", 1)) + "\n")
    os.replace(tmp, store)
    builds = []
    real = cf._build_snapshot
    monkeypatch.setattr(cf, "_build_snapshot", lambda records: builds.append(1) or real(records))
    monkeypatch.setattr(cf, "_SNAPSHOT_MEMO", {})
    a = cf.load_snapshot(tmp_path)
    b = cf.load_snapshot(tmp_path)
    assert len(builds) == 1 and a == b
    b["g-1"]["company_facts"]["summary"] = "mutated by a caller"  # b came from the memo
    assert cf.load_snapshot(tmp_path)["g-1"]["company_facts"].get("summary") != "mutated by a caller"
    with open(store, "a") as fh:  # an append is always seen
        fh.write(json.dumps(_record("g-2", "ZZQB", 2)) + "\n")
    c = cf.load_snapshot(tmp_path)
    assert len(builds) == 2 and set(c) == {"g-1", "g-2"}


def test_facts_snapshot_from_explicit_records_is_never_memoised(monkeypatch):
    from scripts.lib.data_broker import cio_company_facts as cf
    monkeypatch.setattr(cf, "_SNAPSHOT_MEMO", {})
    one = cf.load_snapshot(records=[_record("g-1", "ZZQA", 1)])
    two = cf.load_snapshot(records=[_record("g-2", "ZZQB", 2)])
    assert set(one) == {"g-1"} and set(two) == {"g-2"} and cf._SNAPSHOT_MEMO == {}
