"""Consolidation step 1 (2026-10-10): Finviz enrichment read through the Data Broker.

Pins:
- the single writer (scripts/finviz_enrichment.py save_cache) is locked, merged and atomic, so a
  reader that saw a torn file can no longer wipe the cache down to its own few tickers;
- the broker projection (lib.data_broker.finviz_enrichment_snapshot) is read-only, makes zero
  provider calls, stamps per-symbol as_of/age/stale and a BrokerReadEnvelope@v1, and reads the
  writer's naive local ``cached_at`` as host-local;
- directive_promotion reads the projection first and fetches only on a stale/missing record, has a
  kill switch that restores the legacy path, and prefetches a whole batch in one owner call;
- watch_directives_service's pre-pass mirrors the loop's skips and the governor, and in a dry run
  only plans (no Finviz request, no cache write).

No network, no DB, no live state: every test runs on tmp_path and stubs.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import finviz_enrichment as fe  # noqa: E402
from lib.data_broker import catalog  # noqa: E402
from lib.data_broker import finviz_enrichment_snapshot as snap  # noqa: E402

import directive_promotion as dp  # noqa: E402

NOW_UTC = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def _local_naive(dt_utc: datetime) -> str:
    """What the writer stamps: naive host-local ISO."""
    return dt_utc.astimezone().replace(tzinfo=None).isoformat()


# ── writer: merge + atomic save ──────────────────────────────────────────────


def test_merge_newer_cached_at_wins_and_nothing_is_dropped():
    disk = {
        "AAA": {"cached_at": "2026-10-10T10:00:00", "rsi": 1},
        "BBB": {"cached_at": "2026-10-10T12:00:00", "rsi": 2},
    }
    mine = {
        "BBB": {"cached_at": "2026-10-10T11:00:00", "rsi": 99},
        "CCC": {"cached_at": "2026-10-10T13:00:00", "rsi": 3},
    }
    out = fe.merge_cache_records(disk, mine)
    assert set(out) == {"AAA", "BBB", "CCC"}
    assert out["BBB"]["rsi"] == 2, "an older in-memory record must not overwrite a newer one on disk"
    assert out["CCC"]["rsi"] == 3


def test_save_cache_no_longer_wipes_entries_written_by_another_process(tmp_path):
    big = {f"S{i}": {"symbol": f"S{i}", "cached_at": "2026-10-10T09:00:00"} for i in range(50)}
    fe.save_cache(dict(big), tmp_path)
    path = tmp_path / fe.CACHE_FILE
    os.chmod(path, 0o664)
    # The old failure: a reader got {} from a torn file, then saved only its own ticker.
    small = {"NEW": {"symbol": "NEW", "cached_at": "2026-10-10T10:00:00"}}
    fe.save_cache(small, tmp_path)
    on_disk = json.loads(path.read_text())
    assert len(on_disk) == 51 and "NEW" in on_disk and "S0" in on_disk
    assert small == on_disk, "the caller's dict is refreshed to what is on disk"
    assert (path.stat().st_mode & 0o777) == 0o664, "file mode of the served cache is kept"
    leftovers = [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_cache_is_an_atomic_replace_under_a_lock():
    src = Path(fe.__file__).read_text(encoding="utf-8")
    body = src[src.index("def save_cache(") : src.index("def _read_cache_readonly(")]
    assert "fcntl.flock" in body and "LOCK_EX" in body
    assert "os.replace(" in body and "os.fsync(" in body
    assert ".write_text(" not in body, "no in-place write of the live cache file"


def test_save_cache_survives_a_corrupt_file_on_disk(tmp_path):
    path = tmp_path / fe.CACHE_FILE
    path.parent.mkdir(parents=True)
    path.write_text('{"AAA": {"cached_at": "2026-10-10T09:00:00"')  # torn
    fe.save_cache({"BBB": {"cached_at": "2026-10-10T10:00:00"}}, tmp_path)
    assert json.loads(path.read_text()) == {"BBB": {"cached_at": "2026-10-10T10:00:00"}}


# ── broker projection ────────────────────────────────────────────────────────


def test_projection_reports_fresh_stale_and_missing_with_an_envelope():
    cache = {
        "FRSH": {"symbol": "FRSH", "rsi": 55, "cached_at": _local_naive(NOW_UTC - timedelta(hours=1))},
        "OLD": {"symbol": "OLD", "rsi": 40, "cached_at": _local_naive(NOW_UTC - timedelta(hours=7))},
    }
    out = snap.get_enrichment_batch(["frsh", "OLD", "GONE", "FRSH"], max_age_hours=6, now=NOW_UTC, cache=cache)
    assert out["provider_calls"] == 0
    assert out["fresh"] == ["FRSH"]
    assert out["stale_or_missing"] == ["OLD", "GONE"]
    f = out["symbols"]["FRSH"]
    assert f["stale"] is False and f["record"]["rsi"] == 55
    assert abs(f["age_hours"] - 1.0) < 0.01, "naive cached_at is host-local, not UTC"
    assert out["symbols"]["GONE"] == {"record": None, "as_of": None, "age_hours": None, "stale": True}
    assert out["schema"] == "BrokerReadEnvelope@v1"
    for key in ("as_of", "age_hours", "source", "stale", "stale_after_hours"):
        assert key in out
    assert out["source"]["writer"] == "scripts/finviz_enrichment.py"
    assert out["source"]["registry_status"] == "REGISTERED"  # operator registered the domain 2026-10-10 (§D.2)
    assert out["stale"] is False  # newest requested record is 1 h old


def test_projection_on_a_missing_store_is_no_coverage_and_creates_nothing(tmp_path):
    out = snap.get_enrichment_batch(["AAA"], root=tmp_path, now=NOW_UTC)
    assert out["stale"] is True and out["gap"]["kind"] == "no_coverage"
    assert list(tmp_path.iterdir()) == [], "a read must not create directories or files"


def test_projection_makes_no_provider_call_and_never_writes():
    src = Path(snap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    for forbidden in ("requests", "httpx", "finviz_enrichment", "finviz_throttle", "urllib"):
        assert not any(m == forbidden or m.startswith(forbidden + ".") for m in imported), forbidden
    assert "finviz.com" not in src
    for writer in (".write_text(", ".write_bytes(", "os.replace(", "mkdir("):
        assert writer not in src, writer


def test_catalog_advertises_the_projection():
    row = next(p for p in catalog.PROJECTIONS if p["id"] == "finviz_enrichment_snapshot")
    assert row["read_only"] is True and row["provider_calls"] == 0
    assert row["envelope"] == "BrokerReadEnvelope@v1"
    mod = __import__(row["module"].replace("lib.", "lib.", 1), fromlist=["x"])
    for ep in row["entrypoints"]:
        assert callable(getattr(mod, ep))


# ── directive_promotion consumer ─────────────────────────────────────────────


@pytest.fixture
def fake_owner(monkeypatch):
    """A stand-in for the finviz_enrichment owner: records every fetch, never networks."""
    calls: list[list[str]] = []
    state: dict = {}
    mod = types.SimpleNamespace(
        CACHE_TTL_HOURS=6,
        BATCH_SIZE=20,
        _default_views=lambda skip_fundamentals=False: [111, 121, 131, 141, 171, 161],
        enrich_tickers=lambda syms, project_root=None, **k: calls.append(list(syms)) or {},
        get_enriched=lambda sym, project_root=None: dict(state.get(sym.upper(), {"symbol": sym})),
    )
    monkeypatch.setitem(sys.modules, "finviz_enrichment", mod)
    monkeypatch.setattr(dp, "_latest_quote_price", lambda s, c: 12.5)
    return calls, state


def _stub_projection(monkeypatch, cache):
    real = snap.get_enrichment_batch

    def fake(symbols, **kw):
        kw.pop("root", None)
        kw.setdefault("now", NOW_UTC)
        return real(symbols, cache=cache, **kw)

    monkeypatch.setattr(snap, "get_enrichment_batch", fake)


def test_fresh_broker_record_is_used_without_a_fetch(monkeypatch, fake_owner):
    calls, _ = fake_owner
    monkeypatch.delenv(dp.ENRICH_VIA_BROKER_ENV, raising=False)
    _stub_projection(
        monkeypatch,
        {"AXTI": {"symbol": "AXTI", "rsi": 61, "price": 4.2, "cached_at": _local_naive(NOW_UTC - timedelta(hours=2))}},
    )
    rec = dp.enrich_symbol_on_demand("AXTI", conn=object())
    assert rec["rsi"] == 61 and rec["price"] == 4.2
    assert calls == [], "a fresh broker record must not trigger a Finviz fetch"


def test_stale_broker_record_falls_back_to_the_owner_fetch(monkeypatch, fake_owner):
    calls, state = fake_owner
    _stub_projection(
        monkeypatch, {"AXTI": {"symbol": "AXTI", "rsi": 1, "cached_at": _local_naive(NOW_UTC - timedelta(hours=9))}}
    )
    state["AXTI"] = {"symbol": "AXTI", "rsi": 62}
    rec = dp.enrich_symbol_on_demand("AXTI", conn=object())
    assert calls == [["AXTI"]]
    assert rec["rsi"] == 62 and rec["price"] == 12.5, "price backfilled from the quote projection"


def test_kill_switch_restores_the_legacy_per_symbol_fetch(monkeypatch, fake_owner):
    calls, state = fake_owner
    monkeypatch.setenv(dp.ENRICH_VIA_BROKER_ENV, "0")
    _stub_projection(
        monkeypatch, {"AXTI": {"symbol": "AXTI", "rsi": 61, "cached_at": _local_naive(NOW_UTC - timedelta(hours=1))}}
    )
    state["AXTI"] = {"symbol": "AXTI", "rsi": 61, "price": 4.0}
    dp.enrich_symbol_on_demand("AXTI", conn=object())
    assert calls == [["AXTI"]]


def test_prefetch_dry_run_plans_only(monkeypatch, fake_owner):
    calls, _ = fake_owner
    fresh = {f"F{i}": {"cached_at": _local_naive(NOW_UTC - timedelta(hours=1))} for i in range(5)}
    _stub_projection(monkeypatch, fresh)
    syms = list(fresh) + [f"S{i}" for i in range(45)] + ["s0"]
    plan = dp.prefetch_enrichment(syms, dry_run=True)
    assert calls == []
    assert plan["symbols"] == 50 and plan["fresh_in_broker"] == 5 and plan["stale_or_missing"] == 45
    assert plan["finviz_requests_batched"] == 3 * 6
    assert plan["finviz_requests_per_symbol_path"] == 45 * 6
    assert plan["fetched"] is False and plan["dry_run"] is True


def test_prefetch_fetches_only_stale_symbols_in_one_owner_call(monkeypatch, fake_owner):
    calls, _ = fake_owner
    _stub_projection(monkeypatch, {"F0": {"cached_at": _local_naive(NOW_UTC - timedelta(hours=1))}})
    plan = dp.prefetch_enrichment(["F0", "A", "B"], dry_run=False)
    assert calls == [["A", "B"]]
    assert plan["fetched"] is True


def test_prefetch_with_nothing_stale_makes_no_call(monkeypatch, fake_owner):
    calls, _ = fake_owner
    _stub_projection(monkeypatch, {"F0": {"cached_at": _local_naive(NOW_UTC - timedelta(hours=1))}})
    assert dp.prefetch_enrichment(["F0"])["stale_or_missing"] == 0
    assert calls == []


def test_would_enrich_mirrors_the_governor(monkeypatch):
    monkeypatch.setattr(dp, "get_source_tier", lambda s, conn=None: {"hermes": "trusted", "x": "candidate"}[s])
    assert dp.would_enrich("AAA", "x", True) is True, "operator ticker (auto=True) always enriches"
    assert dp.would_enrich("AAA", "x", None, divergence_index={}) is False, "candidate tier stages"
    assert dp.would_enrich("AAA", "hermes", None, divergence_index={"AAA": "aligned"}) is True
    assert dp.would_enrich("AAA", "hermes", None, divergence_index={"AAA": "divergent"}) is False


# ── watch_directives_service pre-pass (source-level: main() needs the live stores) ──


def _load_prepass():
    src = (SCRIPTS / "watch_directives_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_enrichment_prefetch_candidates")
    return ast.get_source_segment(src, fn), src


class _Cur:
    def __init__(self, staging):
        self.staging, self.rows = staging, []

    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith("SELECT"), "the pre-pass only reads"
        self.rows = [r for r in self.staging if r["directive_id"] == params[0]]

    def fetchall(self):
        return self.rows


def test_prepass_mirrors_loop_skips_and_governor():
    seg, _ = _load_prepass()
    fake_dp = types.SimpleNamespace(
        divergence_index=lambda: {"DIV": "divergent"},
        would_enrich=lambda sym, src, auto, divergence_index=None: (
            bool(auto) if auto is not None else (src == "hermes" and divergence_index.get(sym) != "divergent")
        ),
    )
    ns = {"json": json, "dp": fake_dp, "is_removal_flagged": lambda spec: bool((spec or {}).get("removed"))}
    exec(seg, ns)
    directives = [
        {"id": 1, "spec": {}, "trade_ai_enabled": True, "kind": "ticker", "hermes_enabled": True},
        {"id": 2, "spec": {"removed": True}, "trade_ai_enabled": True, "kind": "ticker", "hermes_enabled": False},
        {"id": 3, "spec": "{}", "trade_ai_enabled": True, "kind": "sector", "hermes_enabled": False},
        {"id": 4, "spec": {}, "trade_ai_enabled": True, "kind": "ticker", "hermes_enabled": False},
    ]
    staging = [
        {"directive_id": 1, "symbol": "hrm", "source_detail": {}},
        {"directive_id": 1, "symbol": "DIV", "source_detail": {}},
        {"directive_id": 1, "symbol": "FLAG", "source_detail": json.dumps({"removed": True})},
        {"directive_id": 1, "symbol": "", "source_detail": {}},
    ]
    resolved = {1: ["TKR", "RECENT"], 2: ["DROPPED"], 3: ["SECT"], 4: ["STALEID"]}
    out = ns["_enrichment_prefetch_candidates"](
        _Cur(staging),
        directives,
        {4},
        lambda did, sym, src: sym == "RECENT",
        lambda d, conn=None: resolved[d["id"]],
        50,
    )
    # TKR: operator ticker (auto) · RECENT: recent hit skipped · DROPPED: removal-flagged directive
    # SECT: trade_ai sector lead the governor would stage · STALEID: stale directive id
    # HRM: hermes lead, trusted+aligned · DIV: divergent stages · FLAG: removal-flagged staging row
    assert out == ["TKR", "HRM"]


def test_service_runs_the_prepass_before_the_loop_and_plans_only_in_dry_run():
    _, src = _load_prepass()
    main = src[src.index("def main():") :]
    assert main.index("_enrichment_prefetch_candidates(") < main.index("for d in directives:")
    assert "dp.prefetch_enrichment(cands, dry_run=dry)" in main
    pre = main[main.index("if _prefetch_enabled():") : main.index("for d in directives:")]
    assert pre.index("c.commit()") < pre.index("dp.prefetch_enrichment("), (
        "no transaction may be held across the network refresh"
    )
