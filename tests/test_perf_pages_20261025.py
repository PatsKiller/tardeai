"""ANCHOR: PERF_PAGES_20261025 — faster Watch, Portfolio and the Agents desk (batch 34).

Pins the per-request work removed from the slow pages without changing what they show:
* Watch: one batched decision projection / review read per page instead of per row; positive consumption-link
  answers cached (bounded, time-limited); single-flight gather(); one bars query for position facts.
* Agents desk: journal listing cached per directory (refreshed on directory mtime), parsed tails cached per
  (path, mtime, size) — bounded; same timeline as the full scan.
* api_v2: sys.path no longer grows by one entry per DB query; per-request memo for two-way curation; batched
  screener-pin sync; filtered symbol-cards get their own ETag; ?symbols= filters on finviz strip and prefs.
Hermetic: fakes and tmp files only — no DB, no network, no live state.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import desks_a  # noqa: E402
from lib import watchlist_intelligence as wi  # noqa: E402
from lib.data_broker import watch_domains, watch_position_facts, watch_prospects  # noqa: E402
from lib.rockville import live_projection as lp  # noqa: E402
from lib.cc_symbol_cards import apply_symbol_cards_query  # noqa: E402


# ── Watch: batched decision projection ─────────────────────────────────────────────────────────────────────────


def _fake_cards(symbols, include_held=True):
    cards, errors = [], []
    for s in symbols:
        if s == "BOOM":
            errors.append({"symbol": s, "error": "RuntimeError"})
            continue
        if s == "NOPKT":
            errors.append({"symbol": s, "error": "no_packet"})
        cards.append({"symbol": s, "company": f"{s} Inc", "held": s == "HELD", "packet_id": f"p-{s}",
                      "decision": {"primary_state": "WAIT" if s != "NOPKT" else "DATA_UNAVAILABLE",
                                   "proposal_allowed": False, "current_mechanics_visible": s == "HELD",
                                   "current_mechanics": {"entry": 1} if s == "HELD" else None},
                      "verification_stages": {"x": s}})
    return {"cards": cards, "errors": errors}


def test_build_live_symbols_matches_single_symbol_calls(monkeypatch):
    calls = []

    def fake(symbols, include_held=True):
        calls.append(list(symbols))
        return _fake_cards(symbols, include_held)

    monkeypatch.setattr(lp, "build_live_cards", fake)
    syms = ["AAA", "HELD", "BOOM", "NOPKT", "aaa"]
    single = {s.upper(): lp.build_live_symbol(s) for s in syms}
    calls.clear()
    batched = lp.build_live_symbols(syms)
    assert calls == [["AAA", "HELD", "BOOM", "NOPKT"]]  # one projection, de-duplicated, upper-cased
    assert batched == single
    assert batched["BOOM"]["ok"] is False and batched["BOOM"]["detail"] == {"symbol": "BOOM", "error": "RuntimeError"}


def test_decisions_for_equals_decision_for_and_falls_back(monkeypatch):
    monkeypatch.setattr(lp, "build_live_cards", _fake_cards)
    syms = ["AAA", "HELD", "BOOM", "NOPKT"]
    assert wi._decisions_for(syms) == {s: wi._decision_for(s) for s in syms}

    def broken(_symbols):
        raise RuntimeError("batch down")

    monkeypatch.setattr(lp, "build_live_symbols", broken)
    assert wi._decisions_for(syms) == {s: wi._decision_for(s) for s in syms}


# ── Watch: batched review reads ────────────────────────────────────────────────────────────────────────────────


class _Cur:
    def __init__(self, legacy, synth, log):
        self.legacy, self.synth, self.log, self._rows = legacy, synth, log, []

    def execute(self, sql, params):
        self.log.append(sql)
        batch = "ANY(" in sql
        if "watchlist_agent_results" in sql:
            wanted = set(params[0]) if batch else {params[0]}
            rows = [dict(r) for r in self.legacy if r["symbol"] in wanted]
            for r in rows:
                if batch:
                    r["batch_symbol"] = r["symbol"]
            self._rows = rows
        else:
            wanted = set(params[0]) if batch else {params[0]}
            rows = [dict(r) for r in self.synth if r["symbol"] in wanted]
            for r in rows:
                if batch:
                    r["batch_symbol"] = r["symbol"]
            self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def test_reviews_for_symbols_equals_per_symbol(monkeypatch):
    import db_adapter

    t0 = datetime(2026, 10, 25, tzinfo=timezone.utc)
    legacy = [
        {"symbol": "AAA", "agent": "maria", "model_used": "m", "summary": "s", "recommendation": "BUY",
         "full_narrative": "", "prompt_hash": "h", "started_at": t0, "completed_at": t0, "status": "complete", "id": 1},
        {"symbol": "BBB", "agent": "critic", "model_used": "m2", "summary": "s2", "recommendation": "HOLD",
         "full_narrative": "", "prompt_hash": "h2", "started_at": t0, "completed_at": t0, "status": "ok", "id": 2},
    ]
    synth = [{"symbol": "AAA", "recommendation": "BUY", "synthesis_narrative": "n", "model_used": "x",
              "updated_at": t0, "dual_consensus_json": None, "decision_safety": None}]
    log: list[str] = []

    class _Conn:
        def cursor(self):
            return _Cur(legacy, synth, log)

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(wi, "_load_intelligence_artifacts", lambda s: {})
    monkeypatch.setattr(wi, "_load_rockville_review", lambda s: None)
    syms = ["AAA", "BBB", "CCC"]
    single = {s: wi._reviews_for_symbol(s) for s in syms}
    n_single = len(log)
    log.clear()
    batched = wi._reviews_for_symbols(syms)
    assert batched == single
    assert n_single == 2 * len(syms) and len(log) == 2  # two queries per page, not two per symbol


# ── Watch: consumption-link cache (bounded, positives only) ────────────────────────────────────────────────────


def _artifact(rid):
    return {"authorization_event_id": "e", "process_id": "p", "provider": "x", "model": "m",
            "provider_request_id": rid, "input_hash": "i", "artifact_id": "a", "artifact_hash": "h",
            "started_at": "t", "completed_at": "t", "requested_policy": "r", "executed_policy": "r",
            "fallback_used": False}


def test_consumption_link_cache_positive_only_and_bounded(monkeypatch):
    watch_domains._CONSUMPTION_LINKS.clear()
    linked = {"r1"}
    lookups = []

    def fake_db(sql, params=None, fetch="all"):
        lookups.append(params[0])
        return {"id": 1, "success": True} if params[0] in linked else None

    monkeypatch.setattr(watch_domains, "_db_query", fake_db)
    assert watch_domains.authorize_review_artifact(_artifact("r1")) == (True, None)
    assert watch_domains.authorize_review_artifact(_artifact("r1")) == (True, None)
    assert lookups == ["r1"]  # linked id answered from the cache the second time
    assert watch_domains.authorize_review_artifact(_artifact("r2")) == (False, "CONSUMPTION_REQUEST_ID_UNLINKED")
    linked.add("r2")  # a consumption logged later is seen at once (negatives are never cached)
    assert watch_domains.authorize_review_artifact(_artifact("r2")) == (True, None)
    assert lookups == ["r1", "r2", "r2"]

    monkeypatch.setattr(watch_domains, "_CONSUMPTION_LINK_MAX", 3)
    for i in range(10):
        watch_domains._remember_consumption_link(f"x{i}")
    assert len(watch_domains._CONSUMPTION_LINKS) == 3 and "x9" in watch_domains._CONSUMPTION_LINKS

    monkeypatch.setattr(watch_domains, "_CONSUMPTION_LINK_TTL_S", -1.0)
    assert watch_domains._consumption_link_cached("x9") is False  # expired entries are dropped
    watch_domains._CONSUMPTION_LINKS.clear()


# ── Watch: single-flight gather ────────────────────────────────────────────────────────────────────────────────


def test_gather_single_flight(monkeypatch):
    builds = []

    def slow_build(query=None, *, db_query=None, now=None):
        builds.append(1)
        time.sleep(0.2)
        val = {"payload": {"n": len(builds)}}
        watch_prospects._CACHE.update(at=time.monotonic(), val=val)
        return val

    monkeypatch.setattr(watch_prospects, "_gather_build", slow_build)
    monkeypatch.setattr(watch_prospects, "_CACHE", {"at": 0.0, "val": None})
    out = []
    threads = [threading.Thread(target=lambda: out.append(watch_prospects.gather({}))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(builds) == 1 and len(out) == 6 and all(o is out[0] for o in out)
    watch_prospects.gather({"fresh": "1"})  # fresh still forces a rebuild
    assert len(builds) == 2


def test_position_facts_bars_batch_matches_per_symbol():
    rows = [{"batch_symbol": "AAA", "time": 1, "close": 10.0}, {"batch_symbol": "AAA", "time": 2, "close": 11.0},
            {"batch_symbol": "BBB", "time": 1, "close": 5.0}]
    seen = []

    def db(sql, params=None):
        seen.append((sql, params))
        return rows

    out = watch_position_facts._bars_batch(db, ["AAA", "BBB", "CCC"])
    assert out == {"AAA": [{"time": 1, "close": 10.0}, {"time": 2, "close": 11.0}], "BBB": [{"time": 1, "close": 5.0}],
                   "CCC": []}
    assert len(seen) == 1 and seen[0][1] == (["AAA", "BBB", "CCC"],)

    def broken(sql, params=None):
        raise RuntimeError("down")

    assert watch_position_facts._bars_batch(broken, ["AAA"]) is None  # caller falls back to the per-symbol reads


# ── Agents desk: journal listing + tail caches ─────────────────────────────────────────────────────────────────


def _journal(root: Path, agent: str, run: str, ts: datetime, mtime: float, **extra) -> Path:
    d = root / agent
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{run}.jsonl"
    p.write_text(json.dumps({"ts": ts.isoformat(), "agent_id": agent, "run_id": run, **extra}) + "\n")
    os.utime(p, (mtime, mtime))
    return p


@pytest.fixture()
def _clear_desk_caches():
    desks_a._LISTING.clear()
    desks_a._TAILS.clear()
    yield
    desks_a._LISTING.clear()
    desks_a._TAILS.clear()


def test_run_timeline_cached_equals_full_scan(tmp_path, monkeypatch, _clear_desk_caches):
    now = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
    for i in range(300):
        at = now - timedelta(hours=i)
        _journal(tmp_path, ("alex", "steph", "morgan")[i % 3], f"r{i:03d}", at, at.timestamp(),
                 retrieval_count=i % 2, model_error=desks_a.GATE_B_PLACEHOLDER if i % 5 == 0 else None)
    (tmp_path / "alex" / "notes.txt").write_text("x")

    def full_scan(root, *, now):
        monkeypatch.setattr(desks_a, "_cached_journal_listing", lambda r, n: None)
        try:
            return desks_a.run_timeline(root, now=now)
        finally:
            monkeypatch.undo()

    ref = full_scan(tmp_path, now=now)
    first = desks_a.run_timeline(tmp_path, now=now)
    assert first == ref

    stats = []
    real_stat = os.stat
    monkeypatch.setattr(desks_a.os, "stat", lambda p, *a, **k: stats.append(str(p)) or real_stat(p, *a, **k))
    second = desks_a.run_timeline(tmp_path, now=now)
    monkeypatch.setattr(desks_a.os, "stat", real_stat)
    assert second == ref
    # warm: the 300-file listing is not re-stat()ed; only the files the timeline opens (newest MAX_ROWS*3 plus the
    # ~26 h window) are re-checked for the tail cache
    assert len(stats) < 100

    # a new run file changes the directory mtime and is picked up
    later = now + timedelta(minutes=5)
    _journal(tmp_path, "alex", "r999", later, later.timestamp())
    os.utime(tmp_path / "alex", None)
    after = desks_a.run_timeline(tmp_path, now=later)
    assert after["runs"][0]["run_id"] == "r999" and after["by_agent"]["alex"] == ref["by_agent"]["alex"] + 1
    assert after == full_scan(tmp_path, now=later)


def test_desk_caches_are_bounded(tmp_path, monkeypatch, _clear_desk_caches):
    monkeypatch.setattr(desks_a, "_TAIL_CACHE_MAX", 5)
    monkeypatch.setattr(desks_a, "_LISTING_MAX_DIRS", 2)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    for i in range(12):
        p = _journal(tmp_path, f"a{i % 4}", f"r{i}", now, now.timestamp())
        desks_a._tail_records_cached(p)
    for i in range(4):
        desks_a._agent_dir_listing(tmp_path / f"a{i}")
    assert len(desks_a._TAILS) == 5 and len(desks_a._LISTING) == 2


# ── api_v2 ─────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api_v2():
    import scripts.api_v2 as mod

    return mod


def test_db_query_does_not_grow_sys_path(api_v2):
    """Perf regression: every _db_query used to sys.path.insert(0, scripts/) — 20k queries made each failed import
    ~170 ms. Now the entry is added at most once."""
    before = len(sys.path)
    for _ in range(500):
        api_v2._db_query("SELECT 1")
        api_v2._ensure_scripts_path()
    assert len(sys.path) <= before + 1
    assert sys.path.count(api_v2._SCRIPTS_DIR) <= 2


def test_two_way_curation_builds_plan_and_sectors_once(api_v2, monkeypatch):
    built = {"plan": 0, "sectors": 0}

    def plan(query=None):
        built["plan"] += 1
        return {"digest": "d", "position_decisions": [{"symbol": "AAA"}]}

    def sectors(query=None):
        built["sectors"] += 1
        return {"opportunities": [{"sector": "Tech"}], "count": 1}

    monkeypatch.setattr(api_v2, "_cio_capital_plan_build", plan)
    monkeypatch.setattr(api_v2, "_cio_sector_opportunities_build", sectors)
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])

    def two_uses():
        a = api_v2._cio_capital_plan()
        a["position_decisions"].append({"symbol": "MUTATED"})
        b = api_v2._cio_capital_plan()
        api_v2._cio_sector_opportunities()
        api_v2._cio_sector_opportunities()
        return b

    monkeypatch.setattr(api_v2, "_two_way_curation_health_body", lambda q=None: two_uses())
    b = api_v2._two_way_curation_health()
    assert built == {"plan": 1, "sectors": 1}
    assert b["position_decisions"] == [{"symbol": "AAA"}]  # callers get copies, never each other's mutations
    api_v2._cio_capital_plan()  # outside a request scope nothing is memoized
    assert built["plan"] == 2


def test_screener_pin_sync_batched(api_v2, monkeypatch):
    calls = []

    def fake_db(sql, params=None, fetch="all"):
        calls.append((" ".join(sql.split())[:40], params))
        if "SELECT symbol FROM screener_find_pins" in sql:
            return [{"symbol": "aaa"}, {"symbol": "BBB"}, {"symbol": "AAA"}, {"symbol": " ccc "}]
        if "DISTINCT ON (upper(wi.symbol))" in sql:
            return [{"sym": "AAA", "rec": "buy"}, {"sym": "CCC", "rec": "hold"}]
        if "INSERT INTO screener_find_pins" in sql:
            return [{"symbol": s} for s in params[0]]
        return None

    monkeypatch.setattr(api_v2, "_db_query", fake_db)
    api_v2._sync_all_screener_find_pins()
    inserts = [p for s, p in calls if s.startswith("INSERT INTO screener_find_pins")]
    assert len(inserts) == 1
    syms, cios, actives = inserts[0]
    # a repeated symbol keeps its LAST loop position (the later upsert wins), verdicts as the per-pin read
    assert syms == ["BBB", "AAA", "CCC"] and cios == ["", "BUY", "HOLD"] and actives == [False, True, False]
    assert sum(1 for s, _ in calls if "CREATE TABLE" in s) == 1

    calls.clear()

    def no_recs(sql, params=None, fetch="all"):
        calls.append(" ".join(sql.split())[:40])
        if "SELECT symbol FROM screener_find_pins" in sql:
            return [{"symbol": "AAA"}]
        if "DISTINCT ON" in sql:
            return None  # read failed -> per-pin fallback
        return {"rec": "BUY"} if "LIMIT 1" in sql else None

    monkeypatch.setattr(api_v2, "_db_query", no_recs)
    api_v2._sync_all_screener_find_pins()
    assert any(c.startswith("INSERT INTO screener_find_pins (symbol") for c in calls)


def test_filtered_symbol_cards_get_their_own_etag():
    full = {"cards": {"AAA": {}, "BBB": {}, "CCC": {}}, "__etag__": 'W/"sc-abc"'}
    a = apply_symbol_cards_query(full, {"symbols": "AAA,BBB"})
    b = apply_symbol_cards_query(full, {"symbols": "bbb,aaa"})
    c = apply_symbol_cards_query(full, {"symbols": "CCC"})
    assert set(a["cards"]) == {"AAA", "BBB"} and a["__etag__"] == b["__etag__"]
    assert len({full["__etag__"], a["__etag__"], c["__etag__"]}) == 3
    assert apply_symbol_cards_query(full, None)["__etag__"] == full["__etag__"]


def test_finviz_strip_symbols_filter(api_v2):
    out = {"ok": True, "map": {"AAA": {"x": 1}, "BBB": {"x": 2}}, "count": 2}
    assert api_v2._finviz_strip_filter(out, {}) is out
    f = api_v2._finviz_strip_filter(out, {"symbols": ["aaa,ZZZ"]})
    assert f["map"] == {"AAA": {"x": 1}} and f["count"] == 2 and out["map"].keys() == {"AAA", "BBB"}


def test_ui_prefs_symbols_filter_is_done_in_sql(api_v2, monkeypatch):
    seen = []

    def fake_db(sql, params=None, fetch="all"):
        seen.append((sql, params))
        return {"value": {"generated_at": "t", "symbols": {"AAA": 1}}, "updated_at": None}

    monkeypatch.setattr(api_v2, "_db_query", fake_db)
    out = api_v2._ui_prefs_get({"key": "portfolio.shared-symbol-context.v1", "symbols": "bbb, aaa,"})
    assert out["value"]["symbols"] == {"AAA": 1}
    sql, params = seen[-1]
    assert "jsonb_each(value->'symbols')" in sql and params == (["AAA", "BBB"], "portfolio.shared-symbol-context.v1")
    api_v2._ui_prefs_get({"key": "k"})
    assert seen[-1] == ("SELECT value, updated_at FROM ui_prefs WHERE key=%s", ("k",))
