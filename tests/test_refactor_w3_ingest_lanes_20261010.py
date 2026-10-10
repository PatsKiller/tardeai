"""Refactor wave 3 (cron -> n8n, 2026-10-10), bucket X1: ingest lanes.

Eight scripts / nine cron rows get ``--dry-run`` that cannot reach a write (AGENTS.md §6), a
LaneRunReceipt@v1 on real runs only, and honest exit codes:

- finviz_enrichment.py (L142 finviz-enrichment): dry run never calls Finviz (paid), never saves the cache.
- sec_data_ingest.py (L150 sec-data-ingest, --all): dry run never enters PipelineRun or calls SEC.
- social_ingest.py (L243 social-ingest-all, L244 social-ingest-stocktwits; lane id from argv).
- fred_data_ingest.py (L248 fred-data-ingest, --ingest): dry run never enters PipelineRun or calls FRED.
- sync_dividend_data.py (L216 sync-dividend-data).
- etf_analyst_enrich.py (L505): per-run ALTER TABLE stays off the dry path; 0 constituents fetched -> exit 1.
- etf_performance_enrich.py (L520): --dry-run / --no-fetch run no DDL (--no-fetch used to).
- validate_expense_ratios.py (L550): --dry-run wins over --apply.

Hermetic: fake connections and modules, TRADEAI_STATE_ROOT = tmp_path. No DB, network or LLM.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the
# real driver is absent, so the dry-run safety tests still run in CI instead of being skipped.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
    import psycopg2.extras  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import etf_analyst_enrich as eae  # noqa: E402
import etf_performance_enrich as epe  # noqa: E402
import finviz_enrichment as fe  # noqa: E402
import fred_data_ingest as fdi  # noqa: E402
import sec_data_ingest as sdi  # noqa: E402
import social_ingest as si  # noqa: E402
import sync_dividend_data as sdd  # noqa: E402
import validate_expense_ratios as ver  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 1
        self._one, self._all = (0,), []

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.sql.append(norm)
        if self.conn.fail_on and self.conn.fail_on in norm:
            raise RuntimeError("db failure")
        res = (self.conn.responder(norm, params) if self.conn.responder else None) or {}
        self._one, self._all = res.get("one", (0,)), res.get("all", [])
        self.rowcount = res.get("rowcount", 1)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, responder=None, fail_on=None):
        self.responder, self.fail_on = responder, fail_on
        self.sql, self.commits, self.readonly, self.closed = [], 0, False, 0

    def cursor(self, *a, **k):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass

    def set_session(self, readonly=False, **_k):
        self.readonly = readonly

    def writes(self):
        return [s for s in self.sql if s.split(" ", 1)[0].upper() in _WRITE_VERBS]


def _boom(*_a, **_k):
    raise AssertionError("a dry run reached a side effect")


def _boom_module(name):
    mod = types.ModuleType(name)
    mod.__getattr__ = lambda attr: _boom()  # any attribute access is a reach
    return mod


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)


def _receipt(tmp_path, lane):
    p = tmp_path / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


def _no_receipts(tmp_path):
    rt = tmp_path / "data" / "runtime"
    return not rt.exists() or not any(rt.iterdir())


def _seed_ok(tmp_path, lane):
    llr.write_lane_receipt(lane, ok=True, exit_code=0)
    return _receipt(tmp_path, lane)["ok_at"]


def _pipeline_stub(monkeypatch, calls):
    mod = types.ModuleType("pipeline_registry")
    mod.run_start = lambda *a, **k: calls.append(("start", a)) or 7
    mod.run_complete = lambda *a, **k: calls.append(("complete", a, k))
    mod.run_fail = lambda *a, **k: calls.append(("fail", a))
    monkeypatch.setitem(sys.modules, "pipeline_registry", mod)
    return mod


# ── sync_dividend_data (L216) ────────────────────────────────────────────────────────────────────────────


def _div_conn(**kw):
    def responder(sql, _p):
        if "FROM ticker_strategy_classifications" in sql:
            return {"all": [{"symbol": "KO"}, {"symbol": "FID-X"}, {"symbol": "PEP"}]}
        return None

    return FakeConn(responder, **kw)


def test_sync_dividend_dry_run_reaches_no_write(tmp_path, monkeypatch, capsys):
    conn = _div_conn()
    monkeypatch.setattr(sdd, "_get_conn", lambda: conn)
    monkeypatch.setattr(sdd, "_fetch_yf_dividend", _boom)
    monkeypatch.setattr(sdd, "sync", _boom)
    assert sdd.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"would_check": 2' in out and "FID-X" not in out
    assert conn.readonly and conn.writes() == [] and conn.commits == 0
    assert _no_receipts(tmp_path)


def test_sync_dividend_real_run_writes_receipt(tmp_path, monkeypatch):
    conn = _div_conn()
    monkeypatch.setattr(sdd, "_get_conn", lambda: conn)
    monkeypatch.setattr(
        sdd, "_fetch_yf_dividend", lambda s: {"annual_dividend_per_share": 1.0, "dividend_yield_pct": 2.0}
    )
    assert sdd.main([]) == 0
    assert any(s.startswith("INSERT INTO ticker_dividend_data") for s in conn.sql) and conn.commits == 1
    r = _receipt(tmp_path, "sync-dividend-data")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["updated"] == 2


def test_sync_dividend_every_fetch_failed_exits_1(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "sync-dividend-data")
    monkeypatch.setattr(sdd, "_get_conn", lambda: _div_conn())
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_boom_ticker))
    assert sdd.main([]) == 1
    r = _receipt(tmp_path, "sync-dividend-data")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["fetch_errors"] == 2


def _boom_ticker(*_a, **_k):
    raise ConnectionError("yahoo down")


def test_sync_dividend_crash_writes_failed_receipt(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "sync-dividend-data")
    monkeypatch.setattr(sdd, "_get_conn", lambda: _div_conn(fail_on="INSERT"))
    monkeypatch.setattr(sdd, "_fetch_yf_dividend", lambda s: {"annual_dividend_per_share": 1.0})
    with pytest.raises(RuntimeError):
        sdd.main([])
    r = _receipt(tmp_path, "sync-dividend-data")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["error"] == "RuntimeError"


def test_sync_dividend_dry_branch_returns_before_sync():
    src = inspect.getsource(sdd.main)
    assert src.index("if a.dry_run:") < src.index("return 0") < src.index("r = sync()")


# ── fred_data_ingest (L248) ──────────────────────────────────────────────────────────────────────────────


def test_fred_dry_run_reaches_no_write(tmp_path, monkeypatch, capsys):
    conn = FakeConn(lambda sql, p: {"all": [("DFF", "2026-10-08")]} if "fred_economic_series" in sql else None)
    monkeypatch.setattr(fdi, "_get_conn", lambda: conn)
    monkeypatch.setattr(fdi, "_env", lambda k: "x" if k == "FRED_API_KEY" else "")
    monkeypatch.setattr(fdi, "ingest_fred", _boom)
    monkeypatch.setattr(fdi, "ingest_history", _boom)
    assert fdi.dry_run(["--ingest", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"series_with_stored_data": 1' in out and '"fred_api_key_configured": true' in out
    assert conn.readonly and conn.writes() == [] and _no_receipts(tmp_path)


def test_fred_dry_run_is_checked_before_pipeline_run():
    src = (ROOT / "scripts" / "fred_data_ingest.py").read_text()
    main_block = src[src.index('if __name__ == "__main__":') :]
    assert main_block.index("sys.exit(dry_run(") < main_block.index("with PipelineRun(")


def test_fred_real_run_receipt_and_honest_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(fdi, "ingest_fred", lambda: {"source": "fred", "fetched": 7})
    assert fdi.main(["--ingest"]) == 0
    ok_at = _receipt(tmp_path, "fred-data-ingest")["ok_at"]
    assert ok_at
    monkeypatch.setattr(fdi, "ingest_fred", lambda: {"source": "fred", "fetched": 0, "reason": "no_key"})
    assert fdi.main(["--ingest"]) == 1
    r = _receipt(tmp_path, "fred-data-ingest")
    assert r["status"] == "failed" and r["ok_at"] == ok_at and r["summary"]["reason"] == "no_key"


def test_fred_crash_writes_failed_receipt(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "fred-data-ingest")
    monkeypatch.setattr(fdi, "ingest_fred", lambda: (_ for _ in ()).throw(OSError("db down")))
    with pytest.raises(OSError):
        fdi.main(["--ingest"])
    r = _receipt(tmp_path, "fred-data-ingest")
    assert r["status"] == "failed" and r["ok_at"] == prev


def test_fred_usage_error_is_2():
    assert fdi.main([]) == 2


# ── sec_data_ingest (L150) ───────────────────────────────────────────────────────────────────────────────


def _sec_conn():
    def responder(sql, _p):
        if "FROM ticker_strategy_classifications" in sql:
            return {"all": [{"symbol": "V"}, {"symbol": "FID-ABC"}, {"symbol": "LMT"}]}
        if "FROM sec_form4" in sql:
            return {"all": [("V", 4, "2026-10-01")]}
        return None

    return FakeConn(responder)


def test_sec_dry_run_reaches_no_write(tmp_path, monkeypatch, capsys):
    conn = _sec_conn()
    monkeypatch.setattr(sdi, "_get_conn", lambda: conn)
    monkeypatch.setattr(sdi, "fetch_form4", _boom)
    monkeypatch.setattr(sdi, "_sec_get", _boom)
    monkeypatch.setattr(sdi, "ingest_form4", _boom)
    assert sdi.dry_run(["--all", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"would_scan": 2' in out and "would scan V: stored sec_form4 rows=4" in out
    assert conn.readonly and conn.writes() == [] and _no_receipts(tmp_path)


def test_sec_dry_run_is_checked_before_pipeline_run():
    src = (ROOT / "scripts" / "sec_data_ingest.py").read_text()
    main_block = src[src.index('if __name__ == "__main__":') :]
    assert main_block.index("sys.exit(dry_run(") < main_block.index("with PipelineRun(")


def test_sec_real_run_writes_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(sdi, "_get_conn", lambda: _sec_conn())
    monkeypatch.setattr(
        sdi,
        "fetch_form4",
        lambda s, limit=5: [
            {
                "filer_name": "X",
                "filer_relation": "insider",
                "transaction_type": "Form 4",
                "filing_date": "2026-10-01",
                "sec_url": "u",
            }
        ],
    )
    monkeypatch.setitem(
        sys.modules,
        "content_scoring",
        types.SimpleNamespace(tag_content=lambda **k: {"strategy_tags": [], "agent_tags": []}),
    )
    assert sdi.main(["--all"]) == 0
    r = _receipt(tmp_path, "sec-data-ingest")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["new_filings"] == 2


def test_sec_every_fetch_failed_exits_1(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "sec-data-ingest")
    monkeypatch.setattr(sdi, "_get_conn", lambda: _sec_conn())

    def failing_fetch(sym, limit=5):
        sdi._FETCH_ERRORS.append(f"{sym}: URLError")
        return []

    monkeypatch.setattr(sdi, "fetch_form4", failing_fetch)
    assert sdi.main(["--all"]) == 1
    r = _receipt(tmp_path, "sec-data-ingest")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["fetch_failed"] == 2


def test_sec_crash_writes_failed_receipt(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "sec-data-ingest")
    monkeypatch.setattr(sdi, "_get_conn", lambda: (_ for _ in ()).throw(OSError("db down")))
    with pytest.raises(OSError):
        sdi.main(["--all"])
    r = _receipt(tmp_path, "sec-data-ingest")
    assert r["status"] == "failed" and r["ok_at"] == prev


# ── social_ingest (L243 / L244) ──────────────────────────────────────────────────────────────────────────


def test_social_lane_id_is_derived_from_argv():
    assert si.lane_id_for("all", False) == "social-ingest-all"
    assert si.lane_id_for("stocktwits", True) == "social-ingest-stocktwits"
    assert si.lane_id_for("stocktwits", False) is None
    assert si.lane_id_for("reddit", True) is None


@pytest.mark.parametrize(
    "argv", [["--source", "all", "--dry-run"], ["--source", "stocktwits", "--discover", "--dry-run"]]
)
def test_social_dry_run_reaches_nothing(tmp_path, monkeypatch, capsys, argv):
    calls = []
    _pipeline_stub(monkeypatch, calls)
    monkeypatch.setitem(sys.modules, "requests", _boom_module("requests"))
    for name in (
        "_get_conn",
        "reddit_session",
        "_reddit_secret",
        "ingest_stocktwits",
        "ingest_stocktwits_discovery",
        "ingest_reddit_with_discovery",
        "ingest_reddit",
    ):
        monkeypatch.setattr(si, name, _boom)
    monkeypatch.setattr(si, "_get_holdings_symbols", lambda: ["SCHD", "NVDA", "KO"])
    assert si.main(argv) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and calls == [] and _no_receipts(tmp_path)
    plan = json.loads(out[: out.index("DRY-RUN")])
    strat = plan["stocktwits_discovery"]["strategy_symbols"]
    assert "SCHD" not in strat["dividend_growth"] and "NVDA" not in strat["growth_tech"]  # holdings excluded


def test_social_dry_run_report_varies_with_holdings(monkeypatch, capsys):
    monkeypatch.setattr(si, "_get_holdings_symbols", lambda: [])
    si.main(["--source", "all", "--dry-run"])
    a = capsys.readouterr().out
    monkeypatch.setattr(si, "_get_holdings_symbols", lambda: ["AAPL", "MSFT", "KO", "T"])
    si.main(["--source", "all", "--dry-run"])
    b = capsys.readouterr().out
    assert '"stocktwits_symbol_requests": 15' in a and '"stocktwits_symbol_requests": 19' in b


def test_social_dry_branch_returns_before_run_start():
    src = inspect.getsource(si.main)
    assert src.index('if "--dry-run" in argv:') < src.index("return 0") < src.index("run_start(")


def test_social_real_all_run_writes_per_source_receipt(tmp_path, monkeypatch):
    calls = []
    _pipeline_stub(monkeypatch, calls)
    monkeypatch.setattr(si, "_get_holdings_symbols", lambda: ["KO"])
    monkeypatch.setattr(si, "ingest_stocktwits", lambda syms: {"inserted": 3, "skipped": 1, "errors": []})
    monkeypatch.setattr(
        si, "ingest_stocktwits_discovery", lambda: {"inserted": 5, "skipped": 0, "errors": ["X: HTTP 404"]}
    )
    monkeypatch.setattr(
        si,
        "ingest_reddit_with_discovery",
        lambda: {"inserted": 0, "skipped": 0, "errors": ["REDDIT_NOT_CONFIGURED"], "configured": False},
    )
    assert si.main(["--source", "all"]) == 0
    r = _receipt(tmp_path, "social-ingest-all")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["rows_produced"] == 8
    assert r["summary"]["per_source"]["reddit_discovery"]["configured"] is False
    assert ("complete", (7,), {"rows_processed": 8}) in calls


def test_social_nothing_fetched_exits_1_and_manual_runs_write_no_receipt(tmp_path, monkeypatch):
    _pipeline_stub(monkeypatch, [])
    prev = _seed_ok(tmp_path, "social-ingest-stocktwits")
    monkeypatch.setattr(
        si,
        "ingest_stocktwits_discovery",
        lambda: {"inserted": 0, "skipped": 0, "errors": ["A: HTTP 429 (rate limited)"]},
    )
    assert si.main(["--source", "stocktwits", "--discover"]) == 1
    r = _receipt(tmp_path, "social-ingest-stocktwits")
    assert r["status"] == "failed" and r["ok_at"] == prev
    monkeypatch.setattr(si, "ingest_stocktwits", lambda syms: {"inserted": 1, "skipped": 0, "errors": []})
    before = sorted(p.name for p in (tmp_path / "data" / "runtime").iterdir())
    assert si.main(["--source", "stocktwits", "--symbols", "KO"]) == 0
    assert sorted(p.name for p in (tmp_path / "data" / "runtime").iterdir()) == before


def test_social_crash_writes_failed_receipt(tmp_path, monkeypatch):
    _pipeline_stub(monkeypatch, [])
    prev = _seed_ok(tmp_path, "social-ingest-all")
    monkeypatch.setattr(si, "_get_holdings_symbols", lambda: [])
    monkeypatch.setattr(si, "ingest_stocktwits", lambda syms: (_ for _ in ()).throw(OSError("db down")))
    with pytest.raises(OSError):
        si.main(["--source", "all"])
    r = _receipt(tmp_path, "social-ingest-all")
    assert r["status"] == "failed" and r["ok_at"] == prev


def test_social_429_is_recorded_as_an_error(monkeypatch):
    class Resp:
        status_code = 429

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda *a, **k: Resp()))
    monkeypatch.setattr(si, "_get_conn", lambda: FakeConn())
    res = si.ingest_stocktwits(["KO", "PEP"])
    assert res["inserted"] == 0 and res["errors"] and "429" in res["errors"][0]
    assert si.run_failed([res]) is True


def test_social_usage_error_is_2():
    assert si.main(["--source", "myspace"]) == 2


# ── finviz_enrichment (L142) ─────────────────────────────────────────────────────────────────────────────


def _finviz_cache(tmp_path, fresh):
    from datetime import datetime

    p = tmp_path / fe.CACHE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({s: {"symbol": s, "cached_at": datetime.now().isoformat()} for s in fresh}))
    return p


def test_finviz_dry_run_reaches_no_fetch_or_write(tmp_path, monkeypatch, capsys):
    calls = []
    _pipeline_stub(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)
    cache = _finviz_cache(tmp_path, ["AAA"])
    before = cache.read_bytes()
    for name in ("_fetch_view", "save_cache", "enrich_tickers", "_env", "_load_env"):
        monkeypatch.setattr(fe, name, _boom)
    monkeypatch.setattr(fe.requests, "get", _boom)
    monkeypatch.setattr(sys, "argv", ["finviz_enrichment.py", "AAA", "BBB", "CCC", "--dry-run"])
    assert fe.main() == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"stale": 2' in out and '"finviz_export_requests": 6' in out
    assert cache.read_bytes() == before and calls == [] and _no_receipts(tmp_path)


def test_finviz_dry_run_creates_no_cache_dir_and_varies_with_cache(tmp_path, monkeypatch, capsys):
    _pipeline_stub(monkeypatch, [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "AAA", "BBB", "--dry-run"])
    fe.main()
    a = capsys.readouterr().out
    assert not (tmp_path / "data").exists()  # load_cache() would have mkdir'd data/state
    _finviz_cache(tmp_path, ["AAA", "BBB"])
    monkeypatch.setattr(sys, "argv", ["x", "AAA", "BBB", "--dry-run"])
    fe.main()
    b = capsys.readouterr().out
    assert '"stale": 2' in a and '"stale": 0' in b


def test_finviz_dry_run_universe_session_is_read_only(tmp_path, monkeypatch, capsys):
    import psycopg2

    _pipeline_stub(monkeypatch, [])
    monkeypatch.chdir(tmp_path)
    conn = FakeConn(lambda sql, p: {"all": [("ZETA",)]} if "watchlist_items" in sql else None)
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run"])
    assert fe.main() == 0
    assert conn.readonly and conn.writes() == [] and '"symbols": 1' in capsys.readouterr().out


def test_finviz_dry_branch_returns_before_run_start():
    src = inspect.getsource(fe.main)
    assert src.index("if dry_run:\n        # Structural") < src.index("run_start(") < src.index("enrich_tickers(")


def test_finviz_real_run_receipt_and_nothing_fetched(tmp_path, monkeypatch):
    _pipeline_stub(monkeypatch, [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fe, "_fetch_view", lambda tickers, v, root: {t: {"rsi": 50.0} for t in tickers})
    monkeypatch.setattr(sys, "argv", ["x", "AAA"])
    assert fe.main() == 0
    r = _receipt(tmp_path, "finviz-enrichment")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["stale"] == 1
    ok_at = r["ok_at"]
    monkeypatch.setattr(fe, "_fetch_view", lambda tickers, v, root: {})
    monkeypatch.setattr(sys, "argv", ["x", "BBB"])
    assert fe.main() == 1
    r = _receipt(tmp_path, "finviz-enrichment")
    assert r["status"] == "failed" and r["ok_at"] == ok_at and r["summary"]["nothing_fetched"] is True


def test_finviz_crash_writes_failed_receipt(tmp_path, monkeypatch):
    _pipeline_stub(monkeypatch, [])
    monkeypatch.chdir(tmp_path)
    prev = _seed_ok(tmp_path, "finviz-enrichment")
    monkeypatch.setattr(fe, "enrich_tickers", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(sys, "argv", ["x", "AAA"])
    with pytest.raises(OSError):
        fe.main()
    r = _receipt(tmp_path, "finviz-enrichment")
    assert r["status"] == "failed" and r["ok_at"] == prev


# ── etf_analyst_enrich (L505) ────────────────────────────────────────────────────────────────────────────


def _etf_conn():
    def responder(sql, _p):
        if "information_schema.columns" in sql:
            return {"all": [("analyst_basis",)]}
        if "FROM symbol_profiles" in sql:
            return {"all": [("SPY", "etf", None), ("SH", "inverse_etf", "short")]}
        if "count(DISTINCT" in sql:
            return {"one": (12,)}
        if "SELECT DISTINCT upper(symbol) FROM yahoo_analyst_targets_history" in sql:
            return {"all": []}
        return None

    return FakeConn(responder)


def test_etf_analyst_dry_run_reaches_no_ddl_or_write(tmp_path, monkeypatch, capsys):
    conn = _etf_conn()
    monkeypatch.setattr(eae, "_get_conn", lambda: conn)
    monkeypatch.setattr(eae, "upsert_profile", _boom)
    monkeypatch.setitem(sys.modules, "yfinance", _boom_module("yfinance"))
    assert eae.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"etfs_funds": 2' in out and '"would_run_ddl": true' in out
    assert conn.readonly and conn.writes() == [] and conn.commits == 0 and _no_receipts(tmp_path)


def test_etf_analyst_ddl_is_not_reachable_from_dry_run():
    src = inspect.getsource(eae.main)
    assert src.index("if a.dry_run:") < src.index("return 0") < src.index("res = enrich()")
    assert "ALTER" not in inspect.getsource(eae.preview)


def test_etf_analyst_real_run_receipt(tmp_path, monkeypatch):
    conn = _etf_conn()
    written = []
    monkeypatch.setattr(eae, "_get_conn", lambda: conn)
    monkeypatch.setattr(eae, "upsert_profile", lambda cur, sym, fields, source: written.append(sym))
    info = {"targetMeanPrice": 110.0, "currentPrice": 100.0}
    yf = types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info=info, funds_data=None))
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    assert eae.main([]) == 0
    r = _receipt(tmp_path, "etf-analyst-enrich")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["etfs_with_direct_target"] == 2
    assert any(s.startswith("ALTER TABLE symbol_profiles") for s in conn.sql)  # DDL stays on the real path


def test_etf_analyst_honest_exit_rules():
    base = {
        "ok": True,
        "etfs_funds": 40,
        "etfs_with_holdings": 38,
        "etfs_with_direct_target": 0,
        "constituents_needed": 0,
        "constituents_fetched": 0,
        "with_analyst_view": 31,
    }
    assert eae.run_failed(base) is False  # nothing needed a fetch: 0 fetched is a finding
    assert eae.run_failed({**base, "constituents_needed": 57}) is True  # work existed, 0 fetched
    assert eae.run_failed({**base, "constituents_needed": 57, "constituents_fetched": 3}) is False
    assert eae.run_failed({**base, "etfs_with_holdings": 0}) is True  # pass 1 got nothing for any ETF
    assert eae.run_failed({"ok": False, "etfs_funds": 3}) is True  # yfinance unavailable


def test_etf_analyst_zero_constituents_fetched_exits_1(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "etf-analyst-enrich")
    monkeypatch.setattr(
        eae,
        "enrich",
        lambda: {
            "ok": True,
            "etfs_funds": 2,
            "etfs_with_holdings": 2,
            "etfs_with_direct_target": 0,
            "constituents_needed": 9,
            "constituents_fetched": 0,
            "with_analyst_view": 0,
        },
    )
    assert eae.main([]) == 1
    r = _receipt(tmp_path, "etf-analyst-enrich")
    assert r["status"] == "failed" and r["ok_at"] == prev


def test_etf_analyst_crash_writes_failed_receipt(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "etf-analyst-enrich")
    monkeypatch.setattr(eae, "_get_conn", lambda: (_ for _ in ()).throw(OSError("db down")))
    with pytest.raises(OSError):
        eae.main([])
    assert _receipt(tmp_path, "etf-analyst-enrich")["ok_at"] == prev


# ── etf_performance_enrich (L520) ────────────────────────────────────────────────────────────────────────


def _perf_conn():
    def responder(sql, _p):
        if "information_schema.columns" in sql:
            return {"all": [("ytd_return_pct",), ("dividend_yield_pct",), ("ttm_dividend",), ("perf_updated_at",)]}
        if "FROM symbol_profiles" in sql:
            return {"all": [("SPY",), ("QQQ",), ("SCHD",)]}
        return None

    return FakeConn(responder)


@pytest.mark.parametrize("flag", ["--dry-run", "--no-fetch"])
def test_etf_performance_dry_run_and_no_fetch_run_no_ddl(tmp_path, monkeypatch, capsys, flag):
    conn = _perf_conn()
    monkeypatch.setattr(epe, "_get_conn", lambda: conn)
    monkeypatch.setattr(epe, "upsert_profile", _boom)
    monkeypatch.setitem(sys.modules, "yfinance", _boom_module("yfinance"))
    monkeypatch.setattr(sys, "argv", ["etf_performance_enrich.py", flag])
    assert epe.main() == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"would_fetch": 3' in out and '"would_run_ddl": false' in out
    assert conn.readonly and conn.writes() == [] and conn.commits == 0 and _no_receipts(tmp_path)


def test_etf_performance_dry_run_respects_symbols(monkeypatch, capsys):
    monkeypatch.setattr(epe, "_get_conn", lambda: _perf_conn())
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--symbols", "VTI"])
    epe.main()
    assert '"would_fetch": 1' in capsys.readouterr().out


def test_etf_performance_ddl_is_not_reachable_from_dry_run():
    src = inspect.getsource(epe.main)
    assert (
        src.index('"--dry-run" in sys.argv or "--no-fetch" in sys.argv')
        < src.index("return 0")
        < src.index("res = enrich()")
    )
    assert "ALTER" not in inspect.getsource(epe.preview)


def _perf_yf(info):
    def hist(**_k):
        raise ValueError("no history")

    return types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info=info, history=hist))


def test_etf_performance_real_run_receipt(tmp_path, monkeypatch):
    conn = _perf_conn()
    monkeypatch.setattr(epe, "_get_conn", lambda: conn)
    monkeypatch.setattr(epe, "upsert_profile", lambda *a, **k: types.SimpleNamespace(rows_written=1, rows_rejected=0))
    monkeypatch.setitem(sys.modules, "yfinance", _perf_yf({"ytdReturn": 0.1, "yield": 0.02}))
    monkeypatch.setattr(sys, "argv", ["x"])
    assert epe.main() == 0
    r = _receipt(tmp_path, "etf-performance-enrich")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["updated"] == 3
    assert any(s.startswith("ALTER TABLE symbol_profiles") for s in conn.sql)


def test_etf_performance_nothing_fetched_exits_1(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "etf-performance-enrich")
    monkeypatch.setattr(epe, "_get_conn", lambda: _perf_conn())
    monkeypatch.setattr(epe, "upsert_profile", lambda *a, **k: types.SimpleNamespace(rows_written=0, rows_rejected=0))
    monkeypatch.setitem(sys.modules, "yfinance", _perf_yf({}))
    monkeypatch.setattr(sys, "argv", ["x"])
    assert epe.main() == 1
    r = _receipt(tmp_path, "etf-performance-enrich")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["empty"] == 3


def test_etf_performance_crash_writes_failed_receipt(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "etf-performance-enrich")
    monkeypatch.setattr(epe, "_get_conn", lambda: (_ for _ in ()).throw(OSError("db down")))
    monkeypatch.setattr(sys, "argv", ["x"])
    with pytest.raises(OSError):
        epe.main()
    assert _receipt(tmp_path, "etf-performance-enrich")["ok_at"] == prev


# ── validate_expense_ratios (L550) ───────────────────────────────────────────────────────────────────────


def _er_conn():
    def responder(sql, _p):
        if "expense_ratio FROM symbol_profiles" in sql:
            return {"all": [("FCNTX", 0.0147), ("AMANX", None)]}
        return None

    return FakeConn(responder)


def test_validate_er_dry_run_wins_over_apply(tmp_path, monkeypatch, capsys):
    conn = _er_conn()
    monkeypatch.setattr(ver, "_conn", lambda: conn)
    monkeypatch.setattr(ver, "upsert_profile", _boom)
    monkeypatch.setattr(ver, "run", _boom)
    monkeypatch.setitem(sys.modules, "yfinance", _boom_module("yfinance"))
    assert ver.main(["--apply", "--dry-run", "--symbols", "FCNTX,AMANX"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"missing_ratio": 1' in out and '"apply_requested": true' in out
    assert conn.readonly and conn.writes() == [] and conn.commits == 0 and _no_receipts(tmp_path)


def test_validate_er_dry_branch_returns_before_run():
    src = inspect.getsource(ver.main)
    assert src.index("if a.dry_run:") < src.index("return 0") < src.index("run(symbols=syms, apply=True)")


def _er_yf(info):
    return types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info=info))


def test_validate_er_preview_without_apply_is_read_only_and_writes_no_receipt(tmp_path, monkeypatch):
    conn = _er_conn()
    monkeypatch.setattr(ver, "_conn", lambda: conn)
    monkeypatch.setattr(ver, "upsert_profile", _boom)
    monkeypatch.setitem(sys.modules, "yfinance", _er_yf({"annualReportExpenseRatio": 0.0074}))
    assert ver.main(["--symbols", "FCNTX"]) == 0
    assert conn.readonly and conn.commits == 0 and _no_receipts(tmp_path)


def test_validate_er_apply_writes_receipt(tmp_path, monkeypatch):
    conn = _er_conn()
    written = []
    monkeypatch.setattr(ver, "_conn", lambda: conn)
    monkeypatch.setattr(
        ver, "upsert_profile", lambda cur, s, f, source: written.append((s, f)) or types.SimpleNamespace(rejected=[])
    )
    monkeypatch.setitem(sys.modules, "yfinance", _er_yf({"annualReportExpenseRatio": 0.0074}))
    assert ver.main(["--apply", "--symbols", "FCNTX,AMANX"]) == 0
    assert written and conn.commits == 1
    r = _receipt(tmp_path, "validate-expense-ratios")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["changed"] == 2


def test_validate_er_every_fetch_failed_exits_1(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "validate-expense-ratios")
    monkeypatch.setattr(ver, "_conn", lambda: _er_conn())
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_boom_ticker))
    assert ver.main(["--apply", "--symbols", "FCNTX,AMANX"]) == 1
    r = _receipt(tmp_path, "validate-expense-ratios")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["fetch_errors"] == 2


def test_validate_er_crash_writes_failed_receipt(tmp_path, monkeypatch):
    prev = _seed_ok(tmp_path, "validate-expense-ratios")
    monkeypatch.setattr(ver, "_conn", lambda: (_ for _ in ()).throw(OSError("db down")))
    with pytest.raises(OSError):
        ver.main(["--apply", "--symbols", "FCNTX"])
    assert _receipt(tmp_path, "validate-expense-ratios")["ok_at"] == prev
