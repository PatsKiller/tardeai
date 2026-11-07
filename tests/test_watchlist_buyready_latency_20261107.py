"""LQ-20261107-258: the watchlist and buy-ready reads no longer do their heavy work in the request.

Measured on build 64b126624 (2026-11-07): GET /api/v2/watchlist/items?sort=hermes 32.6 s cold,
GET /api/v2/buy-ready/packets 6-15 s. In-process profile of the same code:

- buy-ready: 9.3 of 9.7 s was ``options_desk_enterprise.load_desk_config()`` re-parsing
  assets/portfolio_intent.yaml once per packet (225 times) inside ``staleness()``.
- watchlist: per-row decision snapshots (12 s cold), ``attach_atr20_batch`` importing yfinance
  (5.5 s) and fetching up to 60 Yahoo histories, and the picked SQL (2-3 s).

Fixes pinned here:
1. the buy-ready index resolves the gate version and block max age once, with the same verdicts;
2. the watchlist request path takes ATR bars from the data broker's stored bars, never yfinance;
3. the watchlist is served stale-while-revalidate (stale_serve), capped at one hour stale, and
   every watchlist write invalidates it (and watch-curation), including a refresh or a
   single-flight compute that began before the write.

Hermetic: synthetic packets and bodies, a fake clock, an inline spawner; no DB, no network.
"""
from __future__ import annotations

import ast
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")]

from scripts.lib import buy_ready_packets_index as brpi  # noqa: E402
from scripts.lib import stale_serve  # noqa: E402
from scripts.lib.stale_serve import StaleServe  # noqa: E402

NOW = datetime(2026, 9, 28, 17, 30, tzinfo=timezone.utc)
WL = "/api/v2/watchlist/items"
CUR = "/api/v3/data-broker/watch-curation"


# ----------------------------------------------------------------------------- buy-ready

def _packet(sym, *, gate="2026-09-28.2", gen_age_h=1.0, qualified=True):
    gen = (NOW - timedelta(hours=gen_age_h)).isoformat()
    return {"schema": "BuyReadyInstitutionalPacket@v2", "symbol": sym, "saved_at": (NOW - timedelta(hours=2)).isoformat(),
            "equity": {"symbol": sym, "state": "BUY_READY", "price": 10.0, "entry_low": 9.5, "entry_high": 10.5,
                       "stop": 9.0, "target": 13.0, "rr": 2.0},
            "options_alt": {"status": "OPTIONS_ALT_OK"},
            "options_alternatives": {"status": "OK", "gate_version": gate, "generated_at": gen, "chain_as_of": gen,
                                     "alternatives": [{"strategy": "long_call", "qualified": qualified,
                                                       "earnings": {"in_blackout": False, "gate_version": gate}}]}}


def _write(d: Path, packets):
    d.mkdir(parents=True, exist_ok=True)
    for p in packets:
        (d / f"{p['symbol']}.json").write_text(json.dumps(p))


def _count_desk_config(monkeypatch, max_age_s=21600):
    import options_desk_enterprise as ode
    calls = []

    def fake():
        calls.append(1)
        return {"buy_ready_block_max_age_s": max_age_s}
    monkeypatch.setattr(ode, "load_desk_config", fake)
    return calls


def test_buy_ready_index_parses_the_desk_config_once_not_per_packet(tmp_path, monkeypatch):
    calls = _count_desk_config(monkeypatch)
    _write(tmp_path / "pk", [_packet(f"S{i:02d}") for i in range(12)])
    out = brpi.index_packets(tmp_path / "pk", now=NOW)
    assert out["count"] == 12
    assert len(calls) == 1, f"desk config parsed {len(calls)} times for 12 packets"


def test_buy_ready_verdicts_are_identical_with_the_hoisted_inputs(tmp_path, monkeypatch):
    _count_desk_config(monkeypatch, max_age_s=3 * 3600)
    packets = [_packet("OK1"), _packet("OLDGATE", gate="2026-01-01.1"), _packet("NOGATE", gate=None),
               _packet("AGED", gen_age_h=5.0), _packet("NONE", qualified=False)]
    hoisted = {p["symbol"]: brpi.index_packet(p, proposals=[], dropped=[], now=NOW, view_kw=brpi.staleness_inputs())["options_alt"]
               for p in packets}
    per_packet = {p["symbol"]: brpi.index_packet(p, proposals=[], dropped=[], now=NOW)["options_alt"] for p in packets}
    assert hoisted == per_packet
    assert hoisted["OK1"]["status"] == "OPTIONS_ALT_OK" and hoisted["OK1"]["qualified_count"] == 1
    assert hoisted["OLDGATE"]["status"] == "STALE_PRE_FIX" and hoisted["OLDGATE"]["qualified_count"] == 0
    assert hoisted["NOGATE"]["status"] == "STALE_PRE_FIX"
    assert hoisted["AGED"]["status"] == "STALE_CHAIN" and hoisted["AGED"]["qualified_count"] == 0


def test_an_unreadable_desk_config_falls_back_to_per_packet_resolution(monkeypatch):
    import options_desk_enterprise as ode

    def broken():
        raise OSError("portfolio_intent.yaml unreadable")
    monkeypatch.setattr(ode, "load_desk_config", broken)
    assert brpi.staleness_inputs() == {}   # staleness() then resolves (and fails closed) per packet, as before


# ----------------------------------------------------------------------------- watchlist ATR

def test_watchlist_atr_never_reaches_yfinance(tmp_path, monkeypatch):
    import watchlist_volatility as wv
    monkeypatch.setattr(wv, "ATR20_CACHE_PATH", tmp_path / "atr20_cache.json")

    def yf_path(_symbol):
        raise AssertionError("the request path called the yfinance-first fetch")
    monkeypatch.setattr(wv, "_fetch_atr20", yf_path)
    fake_planner = types.ModuleType("watchlist_entry_planner")
    broker_calls: list[str] = []

    def bars_data_broker(symbol, days=70):
        broker_calls.append(symbol)
        return None if symbol == "NOBARS" else [{"high": 11.0, "low": 10.0, "close": 10.5}] * 60

    def bars(*_a, **_k):
        raise AssertionError("_bars (yfinance first) was called")
    fake_planner._bars_data_broker = bars_data_broker
    fake_planner._bars = bars
    monkeypatch.setitem(sys.modules, "watchlist_entry_planner", fake_planner)
    monkeypatch.setitem(sys.modules, "yfinance", None)   # importing it would raise

    items = [{"symbol": "AAA", "price": 10.5}, {"symbol": "NOBARS", "price": 5.0}]
    wv.attach_atr20_batch(items, max_fetch=5)
    assert broker_calls == ["AAA", "NOBARS"]
    assert items[0]["atr_20"] == 1.0 and items[0]["atr_20_pct"] == 9.52
    assert "atr_20" not in items[1]
    cached = json.loads((tmp_path / "atr20_cache.json").read_text())
    assert set(cached["AAA"]) == {"atr_20", "ts"}
    assert set(cached["NOBARS"]) == {"miss_ts"}       # a miss is recorded, never a fake value


def test_every_atr_attempt_spends_budget_and_a_recent_miss_is_not_retried(tmp_path, monkeypatch):
    """Before LQ-258 only a hit spent budget: 200 symbols without bars meant 200 bar reads
    (19.5 s) on every request. Now at most max_fetch reads, and a miss waits out the TTL."""
    import watchlist_volatility as wv
    monkeypatch.setattr(wv, "ATR20_CACHE_PATH", tmp_path / "atr20_cache.json")
    calls: list[str] = []

    def no_bars(symbol):
        calls.append(symbol)
        return None
    monkeypatch.setattr(wv, "_fetch_atr20_data_broker", no_bars)
    items = [{"symbol": f"S{i:03d}", "price": 10.0} for i in range(200)]
    wv.attach_atr20_batch(items, max_fetch=30)
    assert len(calls) == 30
    calls.clear()
    wv.attach_atr20_batch(items, max_fetch=30)
    assert len(calls) == 30 and not set(calls) & {f"S{i:03d}" for i in range(30)}

    # past the miss TTL the symbol is asked again
    cache = json.loads((tmp_path / "atr20_cache.json").read_text())
    old = (datetime.now(timezone.utc) - timedelta(hours=wv.ATR20_MISS_TTL_H, minutes=1)).isoformat()
    cache["S000"]["miss_ts"] = old
    (tmp_path / "atr20_cache.json").write_text(json.dumps(cache))
    calls.clear()
    wv.attach_atr20_batch(items[:1], max_fetch=30)
    assert calls == ["S000"]


# ----------------------------------------------------------------------------- SWR + invalidation

class _Clock:
    def __init__(self, t=1_900_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Spawner:
    def __init__(self):
        self.jobs = []

    def __call__(self, fn):
        self.jobs.append(fn)

    def run_all(self):
        jobs, self.jobs = self.jobs, []
        for fn in jobs:
            fn()


def _swr(tmp_path, **kw):
    clock, spawn = _Clock(), _Spawner()
    return StaleServe(tmp_path, clock=clock, spawn=spawn, fresh_s=60, max_stale_s=6 * 3600, **kw), clock, spawn


def _key(path=WL, who="op@example.test", **q):
    return stale_serve.request_key(path, q or {"sort": "hermes"}, who)


def _body(tag):
    return 200, {"ok": True, "data": {"items": [tag]}}


def test_watchlist_is_on_the_swr_allowlist_with_a_one_hour_stale_cap():
    assert WL in stale_serve.DEFAULT_SWR_PATHS
    assert stale_serve.PATH_MAX_STALE_S[WL] == 3600.0


def test_a_warm_watchlist_read_is_served_without_computing(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get(_key(), lambda: _body("v1"))
    spawn.run_all()
    clock.t += 30

    def boom():
        raise AssertionError("recomputed a fresh body")
    status, body = s.get(_key(), boom)
    assert status == 200 and body["data"]["items"] == ["v1"] and body["_swr"]["stale"] is False


def test_watchlist_older_than_the_cap_is_recomputed_inline(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get(_key(), lambda: _body("v1"))
    spawn.run_all()
    clock.t += 3601
    status, body = s.get(_key(), lambda: _body("v2"))
    assert body["data"]["items"] == ["v2"] and body["_swr"]["source"] == "computed"
    # another route keeps the layer-wide window
    other = stale_serve.request_key("/api/v2/desks/agents", {}, "op@example.test")
    s.get(other, lambda: _body("d1"))
    clock.t += 3601
    _, body = s.get(other, lambda: _body("d2"))
    assert body["data"]["items"] == ["d1"] and body["_swr"]["stale"] is True


def test_invalidate_drops_every_principal_and_query_and_the_next_read_computes(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    k1, k2 = _key(who="a@example.test"), _key(who="b@example.test", symbols="AAA")
    s.get(k1, lambda: _body("a1"))
    s.get(k2, lambda: _body("b1"))
    spawn.run_all()
    clock.t += 1
    s.invalidate(WL)
    _, b1 = s.get(k1, lambda: _body("a2"))
    _, b2 = s.get(k2, lambda: _body("b2"))
    assert b1["data"]["items"] == ["a2"] and b2["data"]["items"] == ["b2"]


def test_a_refresh_that_began_before_the_write_is_not_kept(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get(_key(), lambda: _body("v1"))
    spawn.run_all()
    clock.t += 120                                   # stale: serves v1, queues one refresh

    def slow_refresh():
        clock.t += 5
        s.invalidate(WL)                             # the operator's write lands mid-refresh
        clock.t += 5
        return _body("pre-write")
    s.get(_key(), lambda: _body("never"), slow_refresh)
    spawn.run_all()
    assert s.stats["dropped_pre_write"] == 1
    _, body = s.get(_key(), lambda: _body("post-write"))
    assert body["data"]["items"] == ["post-write"]


def test_an_inline_compute_overtaken_by_a_write_is_served_once_and_not_stored(tmp_path):
    s, clock, spawn = _swr(tmp_path)

    def racing():
        clock.t += 1
        s.invalidate(WL)
        clock.t += 1
        return _body("mid")
    _, body = s.get(_key(), racing)
    assert body["data"]["items"] == ["mid"]
    spawn.run_all()
    _, body = s.get(_key(), lambda: _body("after"))
    assert body["data"]["items"] == ["after"]


def test_invalidation_survives_a_restart_and_refuses_the_old_disk_copy(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get(_key(), lambda: _body("v1"))
    spawn.run_all()                                  # persisted 0600
    clock.t += 1
    s.invalidate(WL)
    s2, clock2, spawn2 = _swr(tmp_path)
    clock2.t = clock.t + 1
    _, body = s2.get(_key(), lambda: _body("fresh"))
    assert body["data"]["items"] == ["fresh"] and body["_swr"]["source"] == "computed"
    assert s2.invalidated_at(WL) == clock.t
    doc = json.loads((tmp_path / stale_serve.INVALIDATIONS_FILE).read_text())
    assert doc["paths"][WL] == clock.t


def test_a_disk_copy_from_before_this_change_still_serves_until_a_write(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    s.get(_key(), lambda: _body("v1"))
    spawn.run_all()
    f = next(p for p in tmp_path.glob("*.json") if p.name != stale_serve.INVALIDATIONS_FILE)
    doc = json.loads(f.read_text())
    doc.pop("started_at")                            # the shape LQ-201 wrote
    f.write_text(json.dumps(doc))
    s2, clock2, _ = _swr(tmp_path)
    clock2.t = clock.t + 10
    _, body = s2.get(_key(), lambda: _body("never"))
    assert body["data"]["items"] == ["v1"] and body["_swr"]["source"] == "disk"


def test_watch_writes_invalidate_the_watchlist_and_curation_and_others_do_not(tmp_path):
    s, clock, spawn = _swr(tmp_path)
    for post in ("/api/v2/watchlist/star", "/api/v2/watchlist/submit", "/api/v2/watch/directives/update",
                 "/api/v2/discovery/add-to-watchlist", "/api/v2/prospects/add-to-watchlist",
                 "/api/v2/hermes/watchlist-lifecycle/override", "/api/v3/watch/commands/run",
                 "/api/v2/watch/two-way-curation", "/api/v2/screener/find-pins"):
        assert stale_serve.invalidate_for_write(post, s) == [WL, CUR], post
    assert stale_serve.invalidate_for_write("/api/v2/ops/notes", s) == []
    assert s.invalidated_at("/api/v2/desks/agents") is None


def test_server_invalidates_after_every_post_and_keys_single_flight_on_the_last_write():
    src = (ROOT / "scripts" / "portfolio_server.py").read_text()
    tree = ast.parse(src)
    do_post = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
    finals = [n for n in ast.walk(do_post) if isinstance(n, ast.Try)]
    called = {c.func.id for t in finals for stmt in t.finalbody for c in ast.walk(stmt)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_swr_invalidate_after_write" in called, "do_POST must invalidate in its finally block"
    coalesce = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_coalesce_get")
    seg = ast.get_source_segment(src, coalesce)
    assert "swr.invalidated_at(path)" in seg and 'principal=f"{principal}#inv{cut!r}"' in seg
    assert "swr.get(_swr.request_key(path, query, principal), run_after_writes, refresh)" in seg
