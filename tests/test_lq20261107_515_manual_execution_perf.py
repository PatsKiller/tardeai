"""/v3/manual-execution worker cost (LQ-20261107-515) — three endpoints, three pathologies.

ANCHOR: LQ20261107_515_MANUAL_EXECUTION_PERF

Measured on the live release e8f51ad76 with the page's own polls open: symbol-cards 18.7 s,
technical-grades 12.8 s, open-trades/intelligence 10.3 s, and the page never reached network idle.
Each number came from a loop that ran on every poll, not from a heavy one-off:

* technical-grades re-read and re-parsed the 10.8 MB `ticker_enrichment_cache.json` twice per symbol
  (entry_desk_ops called `enrichment_technicals` and then `snapshot_from_enrichment`, which loads it
  again) — ~70 parses for a 35-symbol desk.
* symbol-cards ran `DISTINCT ON (symbol)` over the whole `ticker_snapshot_daily` history (341,842
  rows, ~82k buffers) although each symbol only needs its newest row, and ran the Yahoo analyst
  backfill synchronously inside the GET.
* open-trades/intelligence read every stored `market_quotes` row for the held symbols (28,367 rows,
  ~23.8k buffers) through a bitmap scan on every 60 s poll, for one row per symbol.

These tests pin the fixed shape hermetically: a fake file, a fake module, a fake `_db_query` and a
fake connection. No database, no broker, no file under data/.

The broker-read legs of `build_intelligence` are stubbed (AGENTS.md §2: an agent never calls a live
broker), so nothing here proves anything about them.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path[:0] = [str(ROOT), str(SCRIPTS)]

import proposal_enrichment_bridge as peb  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_enrichment_cache(monkeypatch):
    """Each test starts from an empty parse cache and a file of its own."""
    monkeypatch.setattr(peb, "_ENRICH_CACHE", {"key": None, "map": {}})
    yield


def _count_parses(monkeypatch) -> list:
    """Record every read of the enrichment file, without touching any other file read."""
    calls: list = []
    real_read_text = Path.read_text

    def counting_read_text(self, *a, **kw):
        calls.append(str(self))
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    return calls


def _write(path: Path, payload) -> None:
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))


# ── 1. proposal_enrichment_bridge: one parse per file version ──────────────────────────────────


def test_many_symbols_cost_one_parse_of_the_enrichment_file(monkeypatch, tmp_path):
    """40 symbols in a desk batch = 1 read, not 40 (and not the 70 the doubled call made)."""
    path = tmp_path / "ticker_enrichment_cache.json"
    _write(path, {f"S{i}": {"rsi": 50 + i, "atr": 1.5} for i in range(40)})
    monkeypatch.setattr(peb, "ENRICH_PATH", path)
    reads = _count_parses(monkeypatch)

    rows = [peb.load_enrichment(f"S{i}") for i in range(40)]
    # the desk calls both entry points per symbol; neither may re-parse
    techs = [peb.enrichment_technicals(f"S{i}") for i in range(40)]

    assert [r["rsi"] for r in rows] == [50 + i for i in range(40)]
    assert [t["rsi"] for t in techs] == [50 + i for i in range(40)]
    assert len(reads) == 1, f"enrichment file parsed {len(reads)}x for 80 lookups"


def test_a_rewritten_cache_is_picked_up_on_the_next_call(monkeypatch, tmp_path):
    """The cache is keyed on (mtime_ns, size): a lane that rewrites the file must be seen at once."""
    path = tmp_path / "ticker_enrichment_cache.json"
    _write(path, {"AAA": {"rsi": 41}})
    monkeypatch.setattr(peb, "ENRICH_PATH", path)
    assert peb.load_enrichment("AAA")["rsi"] == 41

    _write(path, {"AAA": {"rsi": 77}, "BBB": {"rsi": 22}})
    assert peb.load_enrichment("AAA")["rsi"] == 77
    assert peb.load_enrichment("BBB")["rsi"] == 22


def test_a_torn_rewrite_keeps_the_last_good_map_and_is_retried(monkeypatch, tmp_path):
    """A half-written file (a lane replaces it in place) must not blank every card; the next call
    retries because the bad read never becomes the cached key."""
    path = tmp_path / "ticker_enrichment_cache.json"
    _write(path, {"AAA": {"rsi": 41}})
    monkeypatch.setattr(peb, "ENRICH_PATH", path)
    assert peb.load_enrichment("AAA")["rsi"] == 41

    _write(path, '{"AAA": {"rsi": 4')  # truncated mid-write
    assert peb.load_enrichment("AAA")["rsi"] == 41

    _write(path, {"AAA": {"rsi": 63}})
    assert peb.load_enrichment("AAA")["rsi"] == 63


def test_a_missing_file_is_empty_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(peb, "ENRICH_PATH", tmp_path / "absent.json")
    assert peb.load_enrichment("AAA") == {}
    assert peb.enrichment_technicals("AAA")["available"] is False


def test_a_non_dict_payload_does_not_escape(monkeypatch, tmp_path):
    path = tmp_path / "ticker_enrichment_cache.json"
    _write(path, [1, 2, 3])
    monkeypatch.setattr(peb, "ENRICH_PATH", path)
    assert peb.load_enrichment("AAA") == {}


# ── 2. entry_desk_ops.technical_grades_batch: one enrichment read per symbol ───────────────────


def _fake_enrichment_bridge(calls: dict):
    """A stand-in for the bridge that counts the two entry points the batch used to double up."""
    calls.update(enrichment_technicals=0, load_enrichment=0, snapshot=0)

    def enrichment_technicals(symbol, *, live_price=None):
        calls["enrichment_technicals"] += 1
        return {"available": True, "source": "finviz_enrichment", "rsi": 55.0, "atr": 2.0,
                "atr_pct": 3.0, "rvol": 1.5, "trend": "uptrend", "mas": []}

    def grade_from_enrichment(tech, *, adx_regime=None):
        return "TECH_OK", 62, []

    def build_technical_assessment(tech, grade, score, concerns, **kw):
        return {"verdict": "Acceptable setup", "action": "Proceed", "narrative": "ok"}

    def load_enrichment(symbol):
        calls["load_enrichment"] += 1
        return {}

    def snapshot_from_enrichment(symbol, **kw):
        calls["snapshot"] += 1
        return {}

    return types.SimpleNamespace(
        enrichment_technicals=enrichment_technicals,
        grade_from_enrichment=grade_from_enrichment,
        build_technical_assessment=build_technical_assessment,
        load_enrichment=load_enrichment,
        snapshot_from_enrichment=snapshot_from_enrichment,
    )


def test_technical_grades_reads_enrichment_once_per_symbol(monkeypatch):
    """The old path called load_enrichment twice per symbol (technicals + snapshot). Pinned: one
    `enrichment_technicals` per unique symbol, zero extra `load_enrichment`, no `snapshot_from_enrichment`."""
    import entry_desk_ops as edo

    calls: dict = {}
    monkeypatch.setitem(sys.modules, "proposal_enrichment_bridge", _fake_enrichment_bridge(calls))

    symbols = ["nvda", "NVDA", "pfe", "T", ""]
    out = edo.technical_grades_batch(symbols)

    assert out["count"] == 3
    assert set(out["grades"]) == {"NVDA", "PFE", "T"}
    assert calls["enrichment_technicals"] == 3
    assert calls["load_enrichment"] == 0
    assert calls["snapshot"] == 0
    assert all(g["technical_grade"] == "TECH_OK" for g in out["grades"].values())


def test_technical_grades_caps_the_desk_batch_at_40(monkeypatch):
    import entry_desk_ops as edo

    calls: dict = {}
    monkeypatch.setitem(sys.modules, "proposal_enrichment_bridge", _fake_enrichment_bridge(calls))

    out = edo.technical_grades_batch([f"S{i}" for i in range(60)])

    assert out["count"] == 40
    assert calls["enrichment_technicals"] == 40


def test_technical_grades_reports_a_failed_symbol_without_losing_the_batch(monkeypatch):
    import entry_desk_ops as edo

    def enrichment_technicals(symbol, *, live_price=None):
        if symbol == "BAD":
            raise RuntimeError("enrichment unavailable")
        return {"available": True, "source": "finviz_enrichment", "rsi": 55.0, "atr": 2.0,
                "atr_pct": 3.0, "rvol": 1.5, "trend": "uptrend", "mas": []}

    fake = _fake_enrichment_bridge({})
    fake.enrichment_technicals = enrichment_technicals
    monkeypatch.setitem(sys.modules, "proposal_enrichment_bridge", fake)

    out = edo.technical_grades_batch(["BAD", "GOOD"])

    assert out["grades"]["BAD"]["technical_grade"] == "TECH_INCOMPLETE"
    assert "enrichment unavailable" in out["grades"]["BAD"]["error"]
    assert out["grades"]["GOOD"]["technical_grade"] == "TECH_OK"


# ── 3. api_v2._latest_perf_week: newest row per symbol, not the whole history ──────────────────


def _perf_week_with_fake_db(monkeypatch, rows_by_call):
    """Run `_latest_perf_week` against a fake `_db_query`; return (result, recorded calls)."""
    import api_v2

    calls: list = []

    def fake_db_query(sql, params=None):
        # the newest date per symbol: first call answers the recent window, later calls answer the
        # targeted lookup for whatever symbols are still missing
        idx = min(len(calls), len(rows_by_call) - 1)
        calls.append(" ".join(str(sql).split()))
        rows = rows_by_call[idx]
        if isinstance(rows, dict) and "missing" in rows:
            keep = {s: v for s, v in rows["by_symbol"].items() if s in set(rows.get("requested") or [])}
            return [{"symbol": s, "perf_week_pct": v} for s, v in keep.items()]
        return rows

    monkeypatch.setattr(api_v2, "_db_query", fake_db_query)
    return api_v2._latest_perf_week, calls


def test_latest_perf_week_asks_for_a_narrow_date_window_first(monkeypatch):
    """The whole-history DISTINCT ON was the 21.9 s leg; the first query must carry a day window and
    must not filter on the symbol list (which forced a per-symbol index probe and was slower still)."""
    import api_v2

    calls: list = []

    def fake_db_query(sql, params=None):
        calls.append((" ".join(str(sql).split()), params))
        return [{"symbol": "AAA", "perf_week_pct": 1.5}, {"symbol": "BBB", "perf_week_pct": -0.5}]

    monkeypatch.setattr(api_v2, "_db_query", fake_db_query)
    perf = api_v2._latest_perf_week(["AAA", "BBB"])

    assert perf == {"AAA": 1.5, "BBB": -0.5}
    assert len(calls) == 1
    sql, params = calls[0]
    assert "snapshot_date" in sql and "%s::int" in sql
    assert params == (api_v2._PERF_RECENT_DAYS,)
    assert "DISTINCT ON (symbol)" in sql
    assert "snapshot_date DESC" in sql


def test_latest_perf_week_fills_symbols_outside_the_window_with_one_targeted_query(monkeypatch):
    """A symbol whose newest snapshot is older than the window is looked up by name — once, with only
    the still-missing symbols, so a wide page does not pay a per-symbol probe for every card."""
    import api_v2

    calls: list = []

    def fake_db_query(sql, params=None):
        calls.append((" ".join(str(sql).split()), params))
        if len(calls) == 1:
            return [{"symbol": "AAA", "perf_week_pct": 1.5}]
        # BBB has no ticker_snapshot_daily row at any date, so it is asked for and answered with
        # nothing; that absence must stay absent (never a 0, which reads as a flat week).
        assert params == (["BBB", "CCC"],), params
        return [{"symbol": "CCC", "perf_week_pct": 9.0}]

    monkeypatch.setattr(api_v2, "_db_query", fake_db_query)
    perf = api_v2._latest_perf_week(["AAA", "BBB", "CCC"])

    assert perf == {"AAA": 1.5, "CCC": 9.0}  # BBB has no row at any date; absent, not zero
    assert len(calls) == 2
    assert "= ANY(%s)" in calls[1][0]
    assert "snapshot_date >=" not in calls[1][0]


def test_latest_perf_week_deduplicates_and_skips_empty_symbols(monkeypatch):
    import api_v2

    calls: list = []

    def fake_db_query(sql, params=None):
        calls.append(params)
        return [{"symbol": "AAA", "perf_week_pct": 2.0}]

    monkeypatch.setattr(api_v2, "_db_query", fake_db_query)

    assert api_v2._latest_perf_week(["aaa", "AAA", "", None]) == {"AAA": 2.0}
    assert len(calls) == 1


def test_latest_perf_week_with_no_symbols_touches_no_database(monkeypatch):
    import api_v2

    def fake_db_query(sql, params=None):  # pragma: no cover - must not run
        raise AssertionError("queried the database for an empty symbol list")

    monkeypatch.setattr(api_v2, "_db_query", fake_db_query)

    assert api_v2._latest_perf_week([]) == {}
    assert api_v2._latest_perf_week(None) == {}


# ── 4. open_trades_intelligence: one quote row per symbol, not every stored row ────────────────


def test_open_trades_quote_read_narrows_per_symbol_and_keeps_the_served_mark(monkeypatch):
    """The DISTINCT ON bitmap-scanned every stored quote for the held symbols on every 60 s poll.
    Pinned: the statement is a per-symbol lateral latest-row read, and the served fields are
    unchanged — mark, source and day move still come from the market_quotes row."""
    oti = importlib.reload(importlib.import_module("open_trades_intelligence"))

    quotes = [
        {"symbol": "QQQ", "price": 512.25, "prev_close": 508.0, "day_change_pct": 0.84,
         "volume": 1, "avg_volume": 1, "fetched_at": "2026-11-07T20:30:00+00:00"},
    ]
    executed: list = []

    class _Cur:
        def __init__(self):
            self._rows: list = []

        def execute(self, sql, params=None):
            flat = " ".join(str(sql).split())
            executed.append(flat)
            self._rows = list(quotes) if "FROM market_quotes" in flat else []

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return None

    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()

        def rollback(self):
            pass

        def close(self):
            pass

    import builtins

    real_open = builtins.open
    hj = {"holdings": [{
        # no stored mark on the row, so the served price comes from the market_quotes row this
        # test is about (a row WITH canonical_mark is preferred over any quote, by design)
        "symbol": "QQQ", "account": "schwab_rollover_ira", "shares": 10,
        "updated_at": "2026-11-07T20:29:00+00:00",
        "market_value": 5122.5, "cost_basis": 5000.0,
        "cost_basis_source": "broker_api", "gain_loss": 0.0,
    }], "last_repriced": "2026-11-07 15:30:02 ET"}

    def fake_open(path, *a, **kw):
        if str(path) == oti.HOLDINGS_JSON:
            return io.StringIO(json.dumps(hj))
        if str(path).startswith(str(ROOT / "data")) or str(path).startswith(str(ROOT / "config" / "strategies")):
            raise FileNotFoundError(path)
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(oti, "_conn", lambda: _Conn())
    monkeypatch.setattr(oti, "_broker_protective_stops", lambda accts, force=False: {})
    monkeypatch.setattr(oti, "_alpaca_protective_stops", lambda: {})
    for name in ("broker_stop_read_ok", "broker_stops_fetched_at"):
        if hasattr(oti, name):
            monkeypatch.setattr(oti, name, (lambda *a, **k: None) if "fetched" in name else (lambda *a, **k: set()))
    monkeypatch.setattr(oti, "_account_labels", lambda: {
        "schwab_rollover_ira": {"label": "Schwab Rollover IRA", "environment": "live"}})
    extras = types.SimpleNamespace(RealDictCursor=object)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(extras=extras))
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(
        _get_conn=lambda: (_ for _ in ()).throw(RuntimeError("no db"))))

    out = oti.build_intelligence()

    quote_sql = [s for s in executed if "FROM market_quotes" in s]
    assert len(quote_sql) == 1, f"market_quotes read {len(quote_sql)}x"
    sql = quote_sql[0]
    assert "unnest(" in sql
    assert "LATERAL" in sql
    assert "LIMIT 1" in sql
    assert "DISTINCT ON" not in sql

    pos = next(p for p in out["positions"] if p["symbol"] == "QQQ")
    assert pos["current_price"] == 512.25
    assert pos["quote_source"] == "market_quotes"
    assert pos["today_move_pct"] == 0.84
