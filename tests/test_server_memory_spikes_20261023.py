"""SERVER_MEMORY_SPIKES_20261023 — bounded reads behind the 2026-10-23 portfolio-server kills.

Measured on the live data (read-only, one call per route in a forked child, served build
53aa1b619; docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md):

* GET /api/v3/maturity/memory   +1,192 MB peak RSS (tail_jsonl read the 574 MB retrievals log whole)
* GET /api/v3/cio/brain         +1,207 MB (CIO memory summary counted that log with read_text)
* GET /api/v3/cio/observability +1,274 MB (builds brain)
* GET /api/v3/advisory          +314 MB, 27-45 s, 5 concurrent calls per page load
  (spine load_latest parsed the whole 26.5 MB spine once per row: 146x)
* GET /api/v2/watchlist/items   +192-211 MB, 41-49 s (3 full-history bar reads per row
  through a non-indexable ``upper(symbol)`` predicate, only to read the last bar's age)

These tests pin: equal results to the old full reads, bounded bytes, single-flight, and
invalidation. Hermetic: tmp files and fake DB cursors only.
"""
from __future__ import annotations

import builtins
import json
import os
import pathlib
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── byte accounting ───────────────────────────────────────────────────────────
class _Counter:
    def __init__(self) -> None:
        self.bytes: dict[str, int] = {}

    def add(self, path: str, n: int) -> None:
        self.bytes[path] = self.bytes.get(path, 0) + n


@pytest.fixture()
def read_counter(monkeypatch: pytest.MonkeyPatch) -> _Counter:
    """Count bytes read through Path.open / builtins.open per resolved path."""
    counter = _Counter()
    real_path_open = pathlib.Path.open

    class _Wrap:
        def __init__(self, fh, key):
            self._fh, self._key = fh, key

        def read(self, *a):
            data = self._fh.read(*a)
            counter.add(self._key, len(data))
            return data

        def __iter__(self):
            for line in self._fh:
                counter.add(self._key, len(line))
                yield line

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()
            return False

        def __getattr__(self, name):
            return getattr(self._fh, name)

    def path_open(self, mode="r", *a, **k):
        fh = real_path_open(self, mode, *a, **k)
        return _Wrap(fh, str(self)) if "r" in mode and "+" not in mode else fh

    monkeypatch.setattr(pathlib.Path, "open", path_open)
    return counter


def _write_jsonl(path: Path, rows, *, trailing_newline: bool = True) -> None:
    text = "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows)
    path.write_text(text + ("\n" if trailing_newline else ""), encoding="utf-8")


def _ref_tail(path: Path, n: int) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-n:]


def _ref_count(path: Path) -> int:
    return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())


# ── 1. tail_jsonl_lines / tail_jsonl ─────────────────────────────────────────
FIXTURES = [
    [{"i": i} for i in range(5)],
    [{"i": i, "pad": "x" * (i * 37 % 3000)} for i in range(400)],
    ["", "   ", json.dumps({"a": 1}), "", "not json", json.dumps({"b": 2}), "  "],
    [json.dumps({"long": "y" * 50_000})] + [json.dumps({"i": i}) for i in range(3)],
    [],
]


@pytest.mark.parametrize("rows", FIXTURES)
@pytest.mark.parametrize("window", [1024, 4096, 1 << 20])
@pytest.mark.parametrize("trailing", [True, False])
@pytest.mark.parametrize("n", [1, 3, 20, 1000])
def test_tail_lines_equal_full_read(tmp_path, rows, window, trailing, n):
    from scripts.lib.jsonl_bounded import tail_jsonl_lines

    p = tmp_path / "x.jsonl"
    _write_jsonl(p, rows, trailing_newline=trailing)
    assert tail_jsonl_lines(p, n, window=window, max_bytes=64 << 20) == _ref_tail(p, n)


def test_tail_reads_bounded_bytes_on_large_log(tmp_path, read_counter):
    from scripts.lib.jsonl_bounded import tail_jsonl_lines

    big = tmp_path / "aif_memory_retrievals.jsonl"
    line = json.dumps({"retrieval": "r", "query": "q" * 80, "memory_ids": ["m1", "m2"]})
    with big.open("w", encoding="utf-8") as fh:
        for i in range(200_000):
            fh.write(line[:-1] + f', "i": {i}}}\n')
    assert big.stat().st_size > 20_000_000
    read_counter.bytes.clear()
    out = [json.loads(x) for x in tail_jsonl_lines(big, 20)]
    assert [r["i"] for r in out] == list(range(199_980, 200_000))
    assert read_counter.bytes.get(str(big), 0) <= 512 * 1024, read_counter.bytes


def test_tail_byte_cap_returns_short_not_whole_file(tmp_path):
    from scripts.lib.jsonl_bounded import tail_jsonl_lines

    p = tmp_path / "x.jsonl"
    _write_jsonl(p, [json.dumps({"i": i, "pad": "z" * 1000}) for i in range(5000)])
    got = tail_jsonl_lines(p, 4000, window=4096, max_bytes=64 * 1024)
    assert 0 < len(got) < 4000
    assert got == _ref_tail(p, len(got))


# ── 2. count_jsonl_lines: streamed + incremental ─────────────────────────────
def test_count_equals_reference_and_is_incremental(tmp_path, read_counter):
    from scripts.lib import jsonl_bounded as adm

    p = tmp_path / "r.jsonl"
    _write_jsonl(p, ["", json.dumps({"a": 1}), "   ", json.dumps({"b": 2})], trailing_newline=False)
    adm._LINE_COUNT_CACHE.clear()
    assert adm.count_jsonl_lines(p) == 2 == _ref_count(p)
    with p.open("a", encoding="utf-8") as fh:  # completes the open line, then more
        fh.write("\n" + json.dumps({"c": 3}) + "\n\n  \n" + json.dumps({"d": 4}) + "\n")
    counted_before = p.stat().st_size
    read_counter.bytes.clear()
    got = adm.count_jsonl_lines(p)
    incremental = read_counter.bytes.get(str(p), 0)
    assert got == 4 == _ref_count(p)
    assert 0 < incremental < counted_before  # only bytes appended since the last count
    before = p.stat().st_size
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"e": 5}) + "\n")
    read_counter.bytes.clear()
    got = adm.count_jsonl_lines(p)
    assert read_counter.bytes.get(str(p), 0) == p.stat().st_size - before
    assert got == 5 == _ref_count(p)
    read_counter.bytes.clear()
    assert adm.count_jsonl_lines(p) == 5  # unchanged file: no read at all
    assert read_counter.bytes.get(str(p), 0) == 0


def test_count_split_line_across_appends(tmp_path):
    from scripts.lib import jsonl_bounded as adm

    p = tmp_path / "r.jsonl"
    p.write_text('{"a":', encoding="utf-8")
    assert adm.count_jsonl_lines(p) == 1 == _ref_count(p)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(' 1}\n   \n{"b": 2}\n')
    assert adm.count_jsonl_lines(p) == 2 == _ref_count(p)


def test_count_recounts_on_replace_and_truncate(tmp_path):
    from scripts.lib import jsonl_bounded as adm

    p = tmp_path / "r.jsonl"
    _write_jsonl(p, [{"i": i} for i in range(100)])
    assert adm.count_jsonl_lines(p) == 100
    tmp = tmp_path / "r.tmp"
    _write_jsonl(tmp, [{"i": i} for i in range(7)])
    os.replace(tmp, p)  # new inode
    assert adm.count_jsonl_lines(p) == 7
    p.write_text(json.dumps({"z": 1}) + "\n", encoding="utf-8")  # truncate in place
    assert adm.count_jsonl_lines(p) == 1


def test_count_chunk_boundaries(tmp_path, monkeypatch):
    from scripts.lib import jsonl_bounded as adm

    monkeypatch.setattr(adm, "COUNT_CHUNK_BYTES", 7)
    p = tmp_path / "r.jsonl"
    _write_jsonl(p, ["", json.dumps({"abc": "d" * 20}), "  ", "x", "", json.dumps({"q": 1})], trailing_newline=False)
    adm._LINE_COUNT_CACHE.clear()
    assert adm.count_jsonl_lines(p) == _ref_count(p) == 3


def test_cio_memory_summary_never_reads_retrievals_whole(tmp_path, monkeypatch):
    from scripts import api_v3_cio as cio

    cdir = tmp_path / "data" / "cio"
    cdir.mkdir(parents=True)
    _write_jsonl(cdir / "aif_memory_retrievals.jsonl", [{"i": i} for i in range(1234)])
    monkeypatch.setattr(cio, "PROJECT_ROOT", tmp_path)
    real_read_text = pathlib.Path.read_text

    def guarded(self, *a, **k):
        assert self.name != "aif_memory_retrievals.jsonl", "whole-file read of the retrievals log"
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", guarded)
    out = cio.get_memory_summary_v1()
    assert out["retrieval_receipts"] == 1234, out


# ── 3. /api/v3/maturity/memory: bounded page, single-flight, invalidation ────
def _memory_root(tmp_path: Path, n: int) -> Path:
    cdir = tmp_path / "data" / "cio"
    cdir.mkdir(parents=True)
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        rows.append({
            "memory_id": f"m{i:05d}", "status": "ACTIVE", "memory_type": "EPISODIC",
            "subject": f"s{i}", "content": "c", "created_at": (base + timedelta(minutes=i)).isoformat(),
            "contradicts": ["m00000"] if i % 50 == 0 else None,
        })
    _write_jsonl(cdir / "aif_memory.jsonl", rows)
    with (cdir / "aif_memory_retrievals.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(60_000):
            fh.write(json.dumps({"i": i, "q": "w" * 60}) + "\n")
    return cdir


@pytest.fixture()
def maturity_api(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.delenv("TRADEAI_CIO_DIR", raising=False)
    from scripts import api_v3_maturity as api

    api._MEMORY_VIEW_CACHE.clear()
    yield api
    api._MEMORY_VIEW_CACHE.clear()


def test_memory_view_bounded_newest_first(tmp_path, maturity_api, read_counter):
    cdir = _memory_root(tmp_path, 1500)
    status, body = maturity_api.handle_get("memory", {"limit": ["40"]})
    assert status == 200 and body["ok"] is True
    assert len(body["records"]) == 40 and body["records_total"] == 1500 and body["records_truncated"] is True
    assert body["records"][0]["memory_id"] == "m01499" and body["records"][-1]["memory_id"] == "m01460"
    assert sum(body["counts"].values()) == 1500  # counts stay whole
    assert body["contradictions_total"] == 30
    assert [r["i"] for r in body["retrieval_receipts"]] == list(range(59_980, 60_000))
    assert read_counter.bytes.get(str(cdir / "aif_memory_retrievals.jsonl"), 0) <= 512 * 1024
    # default and max limits
    maturity_api._MEMORY_VIEW_CACHE.clear()
    assert len(maturity_api.handle_get("memory", {})[1]["records"]) == 200
    maturity_api._MEMORY_VIEW_CACHE.clear()
    assert len(maturity_api.handle_get("memory", {"limit": "999999"})[1]["records"]) == 1000


def test_memory_view_single_flight_and_invalidation(tmp_path, maturity_api, monkeypatch):
    cdir = _memory_root(tmp_path, 30)
    calls = []
    real = maturity_api._build_memory_view

    def slow(limit):
        calls.append(limit)
        time.sleep(0.2)
        return real(limit)

    monkeypatch.setattr(maturity_api, "_build_memory_view", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(maturity_api.handle_get("memory", {}))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and len(results) == 8
    assert all(r[1]["records_total"] == 30 for r in results)
    results[0][1]["records"].clear()  # callers get independent copies
    assert maturity_api.handle_get("memory", {})[1]["records"]
    assert len(calls) == 1
    with (cdir / "aif_memory.jsonl").open("a", encoding="utf-8") as fh:  # operator action rewrites the store
        fh.write(json.dumps({"memory_id": "m99999", "status": "DISPUTED", "created_at": "2026-12-01T00:00:00+00:00"}) + "\n")
    body = maturity_api.handle_get("memory", {})[1]
    assert len(calls) == 2 and body["records_total"] == 31 and body["records"][0]["memory_id"] == "m99999"


# ── 4. security research spine: offset index == full scan ────────────────────
def _spine_row(sym: str, n: int, pad: int = 200) -> dict:
    return {"symbol": sym, "n": n, "thesis": {"summary": "t" * pad}}


def test_spine_index_matches_full_scan_through_appends_and_rewrites(tmp_path, read_counter):
    from scripts.lib.cross_asset import security_research_spine as S

    p = tmp_path / "spine.jsonl"
    rows = []
    for i in range(300):
        rows.append(json.dumps(_spine_row(["AAPL", "msft", "NVDA", "V"][i % 4], i)))
        if i % 37 == 0:
            rows.append("{broken json")
        if i % 53 == 0:
            rows.append("   ")
    rows.append(json.dumps(["not", "a", "dict"]))
    _write_jsonl(p, rows)
    syms = ["AAPL", "aapl", "MSFT", "NVDA", "V", "ZZZZ", ""]

    def check():
        for s in syms:
            assert S.load_latest(s, path=p) == S._load_latest_scan(str(s).upper().strip(), p), s

    S._SPINE_INDEX.clear()
    check()
    # Bounded lookups once indexed: one line plus the head guard, never the file.
    read_counter.bytes.clear()
    S.load_latest("NVDA", path=p)
    assert read_counter.bytes.get(str(p), 0) <= S._HEAD_BYTES + 1 + 1024, read_counter.bytes
    # Append (incl. a partial, unterminated line that is later completed).
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_spine_row("V", 1000)) + "\n")
        fh.write(json.dumps(_spine_row("AAPL", 1001))[:-5])
    check()
    # Complete the open AAPL line (a writer finishing its append).
    text = p.read_text(encoding="utf-8")
    p.write_text(text[: text.rfind("\n") + 1] + json.dumps(_spine_row("AAPL", 1001)) + "\n", encoding="utf-8")
    check()
    assert S.load_latest("AAPL", path=p)["n"] == 1001
    # In-place rewrite that grows past the old size (same inode).
    rows2 = [json.dumps(_spine_row("NVDA", 5000 + i, pad=900)) for i in range(400)]
    with p.open("r+", encoding="utf-8") as fh:
        fh.seek(0)
        fh.write("\n".join(rows2) + "\n")
        fh.truncate()
    check()
    assert S.load_latest("NVDA", path=p)["n"] == 5399 and S.load_latest("V", path=p) is None
    # Replace via os.replace (new inode), smaller.
    tmp = tmp_path / "spine.tmp"
    _write_jsonl(tmp, [_spine_row("V", 7)])
    os.replace(tmp, p)
    check()
    assert S.load_latest("V", path=p)["n"] == 7


def test_spine_concurrent_reads_are_consistent(tmp_path):
    from scripts.lib.cross_asset import security_research_spine as S

    p = tmp_path / "spine.jsonl"
    _write_jsonl(p, [_spine_row(f"S{i % 50}", i) for i in range(2000)])
    S._SPINE_INDEX.clear()
    errors = []

    def worker(k):
        for j in range(50):
            sym = f"S{(k + j) % 50}"
            got = S.load_latest(sym, path=p)
            if got is None or got["n"] != 1950 + (k + j) % 50:
                errors.append((sym, got and got["n"]))

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


# ── 5. advisory desk: single-flight shared composition ───────────────────────
def test_advisory_desk_single_flight_ttl_force_and_file_invalidation(tmp_path, monkeypatch):
    import scripts.api_v3_advisory as adv

    desk_file = tmp_path / "advisory_desk_latest.json"
    desk_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(adv, "CACHE_FILE", desk_file)
    monkeypatch.setattr(adv, "OPINIONS_CACHE", tmp_path / "advisory_opinion_cache.json")
    adv._DESK_VIEW_CACHE.clear()
    calls = []

    def fake(*, force=False, row_class=None):
        calls.append((force, row_class))
        time.sleep(0.2)
        return {"ok": True, "rows": [{"symbol": "AAA", "row_class": row_class}], "n": len(calls)}

    monkeypatch.setattr(adv, "_get_advisory_desk_uncached", fake)
    out = []
    threads = [threading.Thread(target=lambda: out.append(adv.get_advisory_desk())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and len(out) == 8 and all(o["n"] == 1 for o in out)
    out[0]["stamp"] = "x"  # top level is per caller
    assert "stamp" not in adv.get_advisory_desk()
    assert len(calls) == 1
    adv.get_advisory_desk(row_class="holding")  # separate view per class
    assert len(calls) == 2
    adv.get_advisory_desk(force=True)
    assert len(calls) == 3
    time.sleep(0.01)
    desk_file.write_text('{"rewritten": true}', encoding="utf-8")  # desk run rewrote the cache
    adv.get_advisory_desk()
    assert len(calls) == 4
    monkeypatch.setattr(adv, "_DESK_VIEW_TTL_S", 0.0)
    adv.get_advisory_desk()
    assert len(calls) == 5
    adv._DESK_VIEW_CACHE.clear()


def test_advisory_desk_failures_are_not_cached(tmp_path, monkeypatch):
    import scripts.api_v3_advisory as adv

    monkeypatch.setattr(adv, "CACHE_FILE", tmp_path / "d.json")
    monkeypatch.setattr(adv, "OPINIONS_CACHE", tmp_path / "o.json")
    adv._DESK_VIEW_CACHE.clear()
    calls = []
    monkeypatch.setattr(adv, "_get_advisory_desk_uncached",
                        lambda **k: calls.append(1) or {"ok": False, "error": "x"})
    adv.get_advisory_desk()
    adv.get_advisory_desk()
    assert len(calls) == 2
    adv._DESK_VIEW_CACHE.clear()


# ── 6. technical freshness: one indexed row instead of the full history ──────
NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)


class _FakeCursor:
    def __init__(self, bars, log):
        self.bars, self.log, self._res = bars, log, []

    def execute(self, sql, params):
        self.log.append(" ".join(sql.split()))
        if "LIMIT 1" in sql:
            sym, tf, cutoff = params
            rows = sorted((b for b in self.bars if b[0] == sym and b[1] == tf and b[2] <= cutoff), key=lambda b: b[2])
            self._res = [(rows[-1][2],)] if rows else []
        else:
            sym, tf = params
            rows = sorted((b for b in self.bars if b[0].upper() == sym and b[1] == tf), key=lambda b: b[2])
            self._res = [(b[2], 1.0, 2.0, 0.5, 1.5, 100, "test") for b in rows]

    def fetchall(self):
        return list(self._res)

    def fetchone(self):
        return self._res[0] if self._res else None


class _FakeConn:
    def __init__(self, bars):
        self.bars, self.log = bars, []

    def cursor(self):
        return _FakeCursor(self.bars, self.log)

    def rollback(self):
        pass

    def commit(self):
        pass


def _old_state(ti, symbol, conn, timeframes=("daily", "weekly")):
    states = []
    for tf in timeframes:
        try:
            meta = ti.load_bars(symbol, tf, conn, allow_fetch=False).get("meta") or {}
        except Exception:
            meta = {}
        states.append(str(meta.get("freshness_state") or "UNAVAILABLE"))
    if all(s == "UNAVAILABLE" for s in states):
        return "UNAVAILABLE"
    if "STALE" in states:
        return "STALE"
    if "UNAVAILABLE" in states:
        return "PARTIAL"
    return "CURRENT"


def _daily(sym, last_day_offset, n=300):
    end = datetime(2026, 10, 23, tzinfo=timezone.utc) - timedelta(days=last_day_offset)
    return [(sym, "daily", end - timedelta(days=i)) for i in range(n)]


@pytest.mark.parametrize("rth", [True, False])
@pytest.mark.parametrize("case", ["current", "stale", "none", "lowercase_only", "forming_only"])
def test_freshness_state_matches_full_history_path(monkeypatch, rth, case):
    pytest.importorskip("pandas")  # technical_intelligence imports pandas; CI installs only pytest + pyyaml
    import technical_intelligence as ti
    import packet_invalidation as pi

    monkeypatch.setattr(ti, "_now", lambda: NOW)
    monkeypatch.setattr(pi, "is_us_cash_rth", lambda *a, **k: rth)
    bars = {
        "current": _daily("NVDA", 1),
        "stale": _daily("NVDA", 9),
        "none": [],
        "lowercase_only": _daily("nvda", 1),
        "forming_only": [("NVDA", "daily", NOW - timedelta(hours=2))],
    }[case]
    expected = _old_state(ti, "NVDA", _FakeConn(bars))
    conn = _FakeConn(bars)
    assert ti.technical_freshness_state("nvda", conn) == expected
    if case in ("current", "stale"):
        # one indexed query (exact symbol, LIMIT 1), no full-history read
        assert len(conn.log) == 1 and "symbol = %s" in conn.log[0] and "LIMIT 1" in conn.log[0], conn.log


def test_freshness_state_reads_one_indexed_row_source():
    """Pandas-free pin (CI): freshness asks for the last closed bar by exact symbol, LIMIT 1."""
    src = (ROOT / "scripts" / "technical_intelligence.py").read_text(encoding="utf-8")
    fn = src[src.index("def technical_freshness_state("):src.index("def _bar_closed(")]
    assert "_last_closed_bar_state(symbol, base_tf, conn)" in fn
    # the full-history read runs only as the fallback after the indexed read found no row
    assert fn.index("native_states[base_tf] = _last_closed_bar_state(") < fn.index(
        "if state is None:\n                meta = load_bars(symbol, tf, conn, allow_fetch=False)")
    helper = fn[fn.index("def _last_closed_bar_state("):]
    assert "WHERE symbol = %s AND timeframe = %s AND bar_time <= %s" in helper
    assert "ORDER BY bar_time DESC LIMIT 1" in helper and "upper(symbol)" not in helper


# ── 7. watchdog: post-kill verify polls instead of one early probe ───────────
def test_watchdog_verify_polls_after_kill():
    import subprocess

    sh = ROOT / "scripts" / "portfolio_server_watchdog.sh"
    text = sh.read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0
    tail = text[text.index('log "UNRESPONSIVE after ${FAILS} probes'):]
    assert "VERIFY_SEC" in tail and "while [" in tail
    assert "# brief verify\nsleep 6\n" not in text
    verify = int(text.split("VERIFY_SEC=", 1)[1].split()[0])
    fails = int(text.split("FAILS=", 1)[1].split()[0])
    timeout = int(text.split("TIMEOUT=", 1)[1].split()[0])
    # worst case run (probes + sleeps + SIGTERM wait + verify) must finish inside the 2-min cron period
    assert fails * (timeout + 5) + 5 + verify < 120


# ── 8. client: the Memory panel asks for a bounded page ──────────────────────
def test_memory_panel_requests_bounded_page():
    tsx = (ROOT / "apps/command-center-v3/src/pages/MaturityPanels.tsx").read_text(encoding="utf-8")
    assert "'/api/v3/maturity/memory?limit=40', 120_000" in tsx


def test_data_store_inventory_row_count_is_streamed(tmp_path, monkeypatch):
    from scripts.lib import data_store_inventory as inv

    p = tmp_path / "lineage.jsonl"
    _write_jsonl(p, ["", json.dumps({"a": 1}), "  ", json.dumps({"b": 2}), json.dumps({"c": 3})])
    real_read_text = pathlib.Path.read_text

    def guarded(self, *a, **k):
        assert self != p, "whole-file read of a JSONL store"
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", guarded)
    assert inv._row_count(p, "jsonl") == 3
    assert inv._row_count(p, "json") == 1
    assert inv._row_count(tmp_path / "missing.jsonl", "jsonl") is None


# ── 9. identical heavy GETs coalesce (single-flight) ─────────────────────────
def test_coalesce_single_flight_copies_and_errors():
    from scripts.lib import request_coalesce as rc

    co = rc.Coalescer(ttl=0.5, wait_s=5)
    calls = []
    shared = {"ok": True, "data": {"rows": [1, 2, 3], "__etag__": "e1"}, "n": 0}

    def slow():
        calls.append(1)
        time.sleep(0.3)
        return 200, shared

    out = []
    threads = [threading.Thread(target=lambda: out.append(
        rc.coalesce_get("/api/v2/watchlist/items", {"sort": "hermes", "_": str(time.time_ns())}, slow, coalescer=co)))
        for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and len(out) == 8 and co.stats["computed"] == 1
    # Callers mutate their own top level and data dict the way json_response does.
    for status, body in out:
        body["_serving"] = {"x": 1}
        body["data"].pop("__etag__", None)
    assert "_serving" not in shared and shared["data"]["__etag__"] == "e1"
    # Reused inside the TTL, recomputed after it.
    rc.coalesce_get("/api/v2/watchlist/items", {"sort": "hermes"}, slow, coalescer=co)
    assert len(calls) == 1
    time.sleep(0.55)
    rc.coalesce_get("/api/v2/watchlist/items", {"sort": "hermes"}, slow, coalescer=co)
    assert len(calls) == 2
    # Different query -> different computation.
    rc.coalesce_get("/api/v2/watchlist/items", {"sort": "name"}, slow, coalescer=co)
    assert len(calls) == 3

    def boom():
        calls.append("e")
        time.sleep(0.1)
        raise RuntimeError("db down")

    errs = []

    def call_boom():
        try:
            rc.coalesce_get("/api/v2/paper-proposals", {}, boom, coalescer=co)
        except RuntimeError as exc:
            errs.append(str(exc))

    threads = [threading.Thread(target=call_boom) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errs == ["db down"] * 4 and calls.count("e") == 1
    with pytest.raises(RuntimeError):  # errors are never cached
        rc.coalesce_get("/api/v2/paper-proposals", {}, boom, coalescer=co)
    assert calls.count("e") == 2


def test_coalesce_only_allowlisted_reads(monkeypatch):
    from scripts.lib import request_coalesce as rc

    assert rc.request_key("/api/v2/watchlist/items/", {"_": "1", "a": ["x", "y"]}) == "|/api/v2/watchlist/items?a=x,y"
    assert rc.request_key("/api/v2/watchlist/items", {}, "tailnet:a") != rc.request_key("/api/v2/watchlist/items", {}, "service-token")
    assert rc.request_key("/api/v2/coordination/release-train/stop", {}) is None
    assert rc.request_key("/api/v2/inference/ensemble", {"target_id": "1"}) is None
    co = rc.Coalescer(ttl=10)
    n = []
    for _ in range(3):
        rc.coalesce_get("/api/v2/ops/controls/state", {}, lambda: n.append(1) or (200, {}), coalescer=co)
    assert len(n) == 3  # not on the allowlist: every call computes
    monkeypatch.setenv("TRADEAI_COALESCE_GET", "0")
    assert rc.request_key("/api/v2/watchlist/items", {}) is None


def test_server_dispatch_uses_coalescer():
    src = (ROOT / "scripts" / "portfolio_server.py").read_text(encoding="utf-8")
    assert "_v2_result = _coalesce_get(" in src
    assert 'lambda: _v2_handle(path, method="GET", query=_v2_query)' in src
