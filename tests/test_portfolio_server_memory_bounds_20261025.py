"""ANCHOR: PORTFOLIO_SERVER_MEMORY_BOUNDS_20261025 — portfolio-server memory: bound caches.

The 10 MB ticker_enrichment_cache.json was parsed into four private caches (~21 MB RSS each) and the
identity registry into two (lib.* and scripts.lib.* module copies). They now share one bounded,
stat-keyed store (scripts/lib/shared_json_cache.py); the request loop returns freed heap to the OS when it
goes idle (scripts/lib/malloc_relief.py). Hermetic: tmp files only, no network, no live state.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import malloc_relief, shared_json_cache as sjc  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_store(monkeypatch):
    monkeypatch.delenv("SHARED_JSON_CACHE_MAX_ENTRIES", raising=False)
    monkeypatch.delenv("SHARED_JSON_CACHE_MAX_BYTES", raising=False)
    sjc.clear()
    yield
    sjc.clear()


def _write(p: Path, obj) -> Path:
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _bump(p: Path, obj) -> None:
    """Rewrite with a guaranteed-different stamp (size and mtime_ns)."""
    st = p.stat()
    p.write_text(json.dumps(obj), encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_one_parse_per_file_and_shared_object(tmp_path):
    p = _write(tmp_path / "e.json", {"SPY": {"rsi": 50}})
    a = sjc.load_json(p)
    b = sjc.load_json(p)
    assert a is b
    st = sjc.stats()
    assert st["misses"] == 1 and st["hits"] == 1 and st["entries"] == 1


def test_symlink_and_real_path_share_one_entry(tmp_path):
    p = _write(tmp_path / "e.json", {"a": 1})
    link = tmp_path / "link.json"
    link.symlink_to(p)
    assert sjc.load_json(p) is sjc.load_json(link)
    assert sjc.stats()["entries"] == 1


def test_rewrite_is_picked_up_and_old_parse_released(tmp_path):
    p = _write(tmp_path / "e.json", {"v": 1})
    assert sjc.load_json(p)["v"] == 1
    _bump(p, {"v": 22})
    assert sjc.load_json(p)["v"] == 22
    assert sjc.stats()["entries"] == 1


def test_missing_unparsable_and_wrong_type_return_default(tmp_path):
    assert sjc.load_json(tmp_path / "nope.json", default={}) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert sjc.load_json(bad, default={}) == {}
    lst = _write(tmp_path / "list.json", [1, 2])
    assert sjc.load_json(lst, default={}) == {}
    assert sjc.stats()["entries"] <= 1  # the list parse may be retained, never an error


def test_entry_bound_evicts_least_recently_used(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_JSON_CACHE_MAX_ENTRIES", "2")
    files = [_write(tmp_path / f"f{i}.json", {"i": i}) for i in range(3)]
    sjc.load_json(files[0])
    sjc.load_json(files[1])
    sjc.load_json(files[0])  # f0 most recent
    sjc.load_json(files[2])  # evicts f1
    st = sjc.stats()
    assert st["entries"] == 2 and st["evictions"] == 1
    before = st["misses"]
    sjc.load_json(files[0])
    assert sjc.stats()["misses"] == before  # f0 still cached
    sjc.load_json(files[1])
    assert sjc.stats()["misses"] == before + 1  # f1 was evicted


def test_byte_budget_bounds_retained_bytes_and_skips_oversize(tmp_path, monkeypatch):
    big = _write(tmp_path / "big.json", {"x": "y" * 5000})
    small = [_write(tmp_path / f"s{i}.json", {"x": "y" * 1000}) for i in range(4)]
    monkeypatch.setenv("SHARED_JSON_CACHE_MAX_BYTES", "2500")
    assert sjc.load_json(big)["x"].startswith("y")  # parsed and returned...
    assert sjc.stats()["entries"] == 0 and sjc.stats()["oversize"] == 1  # ...but not retained
    for p in small:
        sjc.load_json(p)
    st = sjc.stats()
    assert st["bytes"] <= 2500 and st["entries"] == 2


def test_store_is_shared_across_duplicate_module_copies(tmp_path):
    """The server imports lib.X and scripts.lib.X as two modules; both must use one store."""
    spec = importlib.util.spec_from_file_location("lib_copy_shared_json_cache", sjc.__file__)
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    try:
        p = _write(tmp_path / "e.json", {"k": 1})
        assert copy is not sjc
        assert copy.load_json(p) is sjc.load_json(p)
        assert copy.stats()["entries"] == 1
    finally:
        sys.modules.pop("lib_copy_shared_json_cache", None)


def test_enrichment_readers_share_one_parse_and_refresh(tmp_path, monkeypatch):
    from scripts.lib import portfolio_benchmarks as pb
    import holding_family as hf

    p = _write(tmp_path / "ticker_enrichment_cache.json", {"SPY": {"perf_ytd": 10.0}})
    monkeypatch.setattr(pb, "ENRICH_PATH", p)
    monkeypatch.setattr(hf, "_ENRICH_PATH", p)
    a = pb._enrich()
    b = hf._state_json(hf._ENRICH_PATH, "_ENRICH_CACHE")
    assert a is b and a["SPY"]["perf_ytd"] == 10.0
    # The old lru_cache(maxsize=1) never refreshed; the shared cache follows a rewrite.
    _bump(p, {"SPY": {"perf_ytd": 12.5}})
    assert pb._enrich()["SPY"]["perf_ytd"] == 12.5
    assert sjc.stats()["entries"] == 1


def test_identity_registry_copies_share_one_parse(tmp_path, monkeypatch):
    from scripts.lib import identity_registry as ir

    reg = _write(tmp_path / "identity_registry.json", {"entities": {}, "by_symbol": {"AAA": "g1"}, "events": {}})
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(reg))
    spec = importlib.util.spec_from_file_location("lib_copy_identity_registry", ir.__file__)
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    try:
        ir._CACHE.clear()
        a = ir.load_cached()
        b = copy.load_cached()
        assert a is b and a["by_symbol"]["AAA"] == "g1"
        assert ir.load_cached() is a  # module-level stamp hit
        _bump(reg, {"entities": {}, "by_symbol": {"AAA": "g2"}, "events": {}})
        assert ir.load_cached()["by_symbol"]["AAA"] == "g2"
        assert len(ir._CACHE) == 1
    finally:
        sys.modules.pop("lib_copy_identity_registry", None)
        ir._CACHE.clear()


class _FakeTrim:
    def __init__(self):
        self.calls = 0

    def __call__(self, pad):
        assert pad == 0
        self.calls += 1
        return 1


@pytest.fixture
def fake_trim(monkeypatch):
    fake = _FakeTrim()
    monkeypatch.setitem(malloc_relief._STATE, "fn", fake)
    monkeypatch.setitem(malloc_relief._STATE, "resolved", True)
    monkeypatch.setitem(malloc_relief._STATE, "inflight", 0)
    monkeypatch.setitem(malloc_relief._STATE, "last_trim", -1e9)
    monkeypatch.setenv("PORTFOLIO_SERVER_MALLOC_TRIM_MIN_INTERVAL_SEC", "15")
    monkeypatch.delenv("PORTFOLIO_SERVER_MALLOC_TRIM", raising=False)
    return fake


def test_trim_only_when_idle_and_rate_limited(fake_trim):
    malloc_relief.note_request_start()
    malloc_relief.note_request_start()
    assert malloc_relief.note_request_end(now=100.0) is False  # one still in flight
    assert fake_trim.calls == 0
    assert malloc_relief.note_request_end(now=100.0) is True  # went idle
    assert fake_trim.calls == 1
    malloc_relief.note_request_start()
    assert malloc_relief.note_request_end(now=105.0) is False  # within the interval
    malloc_relief.note_request_start()
    assert malloc_relief.note_request_end(now=116.0) is True
    assert fake_trim.calls == 2
    assert malloc_relief.stats()["inflight"] == 0


def test_trim_disabled_by_env_and_never_negative(fake_trim, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_SERVER_MALLOC_TRIM", "0")
    malloc_relief.note_request_start()
    assert malloc_relief.note_request_end(now=500.0) is False
    assert malloc_relief.note_request_end(now=900.0) is False  # unmatched end clamps at 0
    assert fake_trim.calls == 0 and malloc_relief.stats()["inflight"] == 0


def test_trim_unavailable_is_a_noop(monkeypatch):
    monkeypatch.setitem(malloc_relief._STATE, "fn", None)
    monkeypatch.setitem(malloc_relief._STATE, "resolved", True)
    assert malloc_relief.trim_now() is False


def test_server_brackets_every_request():
    """Start at the top of process_request_thread; end in shutdown_request (every served request) and on the
    server_busy 503 path, which closes the socket itself."""
    import ast

    tree = ast.parse((ROOT / "scripts" / "portfolio_server.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ReusableHTTPServer")
    fns = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    prt = fns["process_request_thread"]
    first = ast.unparse(prt.body[0])
    assert first == "_malloc_relief.note_request_start()"
    prt_src = ast.unparse(prt)
    busy = prt_src.split("server_busy", 1)[1].split("_t0 = time.monotonic()", 1)[0]
    assert "_malloc_relief.note_request_end()" in busy
    shut = ast.unparse(fns["shutdown_request"])
    assert "finally:" in shut and "_malloc_relief.note_request_end()" in shut
