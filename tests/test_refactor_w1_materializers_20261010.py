"""n8n refactor wave 1 — materializers and the shared receipt helpers.

* materialize_income_engine.py (cron:L220): ``--dry-run`` opens a READ ONLY session, computes, and
  cannot reach ``_persist`` (the only writer); a real run persists once and leaves a receipt.
* sector_rs_daily.py (cron:L750): ``--dry-run`` runs a different, read-only SELECT (no CREATE, no
  INSERT); a SQL error on the real upsert exits 1 instead of "0 rows upserted" + exit 0.
* scripts/lib/lane_last_receipt.py and the ok_at addition to scripts/lib/scheduled_job_receipt.py.
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

from scripts.lib import lane_last_receipt as L  # noqa: E402
from scripts.lib import scheduled_job_receipt as SJ  # noqa: E402


def _load(rel: str, key: str):
    import importlib.util

    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _boom(*_a, **_k):
    raise AssertionError("a dry run reached a write")


def _dry_report(out: str) -> dict:
    line = next(ln for ln in out.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


@pytest.fixture
def state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


# ── lane_last_receipt ────────────────────────────────────────────────────────


def test_lane_receipt_path_is_under_state_root(state_root):
    assert L.receipt_path("x-lane") == state_root / "data/runtime/x-lane_last.json"


def test_lane_receipt_ok_at_advances_only_on_success(state_root):
    path = L.write_lane_receipt("x-lane", ok=True, started_at="s", script="x.py", exit_code=0, summary={"n": 1})
    first = json.loads(path.read_text())
    assert first["schema"] == "LaneRunReceipt@v1" and first["ok_at"] == first["finished_at"]
    L.write_lane_receipt("x-lane", ok=False, started_at="s", script="x.py", exit_code=1)
    second = json.loads(path.read_text())
    assert second["status"] == "failed" and second["ok_at"] == first["ok_at"]


def test_lane_receipt_write_never_raises(monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert (
        L.write_lane_receipt("x", ok=True, started_at="s", script="x.py", exit_code=0, path=blocker / "sub" / "r.json")
        is None
    )
    assert "lane receipt write failed" in capsys.readouterr().err


def test_scheduled_job_receipt_gains_ok_at_and_summary_from(monkeypatch, tmp_path):
    dest = tmp_path / "r.json"
    monkeypatch.setattr(sys, "argv", ["job.py", "--receipt", str(dest)])
    SJ.run_with_receipt(lambda: 0, script="job", root=tmp_path, summary_from=lambda: {"status": "red"})
    ok = json.loads(dest.read_text())
    assert ok["ok_at"] == ok["as_of"] and ok["summary"] == {"state": "completed", "status": "red"}
    monkeypatch.setattr(sys, "argv", ["job.py", "--receipt", str(dest)])
    SJ.run_with_receipt(lambda: 3, script="job", root=tmp_path)
    bad = json.loads(dest.read_text())
    assert bad["exit"] == 3 and bad["ok_at"] == ok["ok_at"]


# ── materialize_income_engine ────────────────────────────────────────────────

M = _load("scripts/materialize_income_engine.py", "_tested_refactor_w1_income_engine")


class IncomeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._last = ""

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        if self.conn.readonly and flat.split(" ", 1)[0] in ("INSERT", "UPDATE", "DELETE"):
            raise AssertionError(f"write on a read-only session: {flat[:60]}")
        self.conn.sql.append(flat)
        self._last = flat

    def fetchall(self):
        if "FROM watchlist_strategy_cards" in self._last:
            return [{"symbol": "SCHD", "strategy_type": "dividend"}]
        if "FROM ticker_dividend_data" in self._last:
            return [{"symbol": "SCHD", "annual_dividend_per_share": 1.0, "dividend_growth_5y": 10}]
        return []

    def fetchone(self):
        if "portfolio_income_goals" in self._last:
            return {"target_income": 1000, "minimum_income_target": 500, "stretch_income_target": 2000}
        if "FROM ticker_dividend_data WHERE symbol" in self._last:
            return {
                "annual_dividend_per_share": 1.0,
                "dividend_yield_pct": 3.0,
                "dividend_growth_5y": 10,
                "payout_safety_score": 0.9,
                "income_reliability_score": 0.9,
            }
        if "sr.layer_id" in self._last:
            return {"layer_id": "core_compounders"}
        return None


class IncomeConn:
    def __init__(self):
        self.readonly = False
        self.readonly_before_cursor = None
        self.sql: list[str] = []
        self.commits = 0
        self.cursors = 0

    def set_session(self, readonly=False, **_kw):
        self.readonly_before_cursor = self.cursors == 0
        self.readonly = readonly

    def cursor(self, cursor_factory=None):
        self.cursors += 1
        return IncomeCursor(self)

    def commit(self):
        if self.readonly:
            raise AssertionError("commit on a read-only session")
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def income_env(monkeypatch, tmp_path):
    state = tmp_path / "pstate"
    state.mkdir()
    (state / "holdings.json").write_text(
        json.dumps(
            {
                "account_summaries": {"A": {"total_value": 10000}},
                "holdings": [{"symbol": "SCHD", "shares": 100, "market_value": 3000, "cost_basis": 2500}],
            }
        )
    )
    monkeypatch.setattr(M, "STATE_DIR", state)
    conn = IncomeConn()
    monkeypatch.setattr(M, "_get_conn", lambda: conn)
    return conn


def test_income_dry_run_is_read_only_and_never_reaches_persist(monkeypatch, state_root, income_env, capsys):
    monkeypatch.setattr(M, "_persist", _boom)
    assert M.main(["--dry-run"]) == 0
    assert income_env.readonly and income_env.readonly_before_cursor and income_env.commits == 0
    assert not [s for s in income_env.sql if s.startswith(("INSERT", "UPDATE"))]
    rep = _dry_report(capsys.readouterr().out)
    assert rep["summary"]["profiles"] == 1 and rep["summary"]["total_annual_income"] == 100.0
    assert not state_root.exists()


def test_income_dry_run_gate_precedes_persist_in_source():
    src = inspect.getsource(M.materialize)
    assert src.index("conn.set_session(readonly=True)") < src.index("conn.cursor(")
    assert src.index("if dry_run:\n        conn.rollback()") < src.index("_persist(conn")
    assert "INSERT INTO" not in src, "the only writer is _persist"


def test_income_real_run_persists_once_and_writes_receipt(state_root, income_env):
    assert M.main([]) == 0
    inserts = [s for s in income_env.sql if s.startswith("INSERT")]
    assert len(inserts) == 2 and income_env.commits == 1
    doc = json.loads((state_root / "data/runtime/materialize-income-engine_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["profiles"] == 1


def test_income_failure_exits_one_with_failed_receipt(monkeypatch, state_root):
    def no_db():
        raise ConnectionError("db down")

    monkeypatch.setattr(M, "_get_conn", no_db)
    assert M.main([]) == 1
    doc = json.loads((state_root / "data/runtime/materialize-income-engine_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None


# ── sector_rs_daily ──────────────────────────────────────────────────────────

S = _load("scripts/sector_rs_daily.py", "_tested_refactor_w1_sector_rs")


def _fake_ex(monkeypatch, *, upsert_result=([1] * 686), present=True):
    sql_log: list[str] = []

    def ex(sql, params=None, fetch=None):
        flat = " ".join(sql.split())
        sql_log.append(flat)
        if "to_regclass" in flat:
            return {"present": present}
        if flat.startswith("CREATE"):
            return True
        if "INSERT INTO sector_rs_daily" in flat:
            return upsert_result
        if "would_upsert" in flat:
            return {"would_upsert": 688, "would_insert": 2, "latest_date": "2026-10-09"}
        return None

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=ex))
    return sql_log


def test_sector_dry_run_is_a_different_read_only_query(monkeypatch, state_root, capsys):
    sql = _fake_ex(monkeypatch)
    monkeypatch.setattr(S, "_ensure", _boom)
    monkeypatch.setattr(S, "backfill", _boom)
    assert S.main(["--dry-run"]) == 0
    assert all(s.startswith(("SELECT", "WITH")) for s in sql)
    assert not any("INSERT" in s or "CREATE" in s for s in sql)
    rep = _dry_report(capsys.readouterr().out)
    assert rep["summary"]["would_upsert"] == 688 and rep["summary"]["would_insert"] == 2
    assert not state_root.exists()


def test_sector_real_run_receipt_and_sql_error_exit(monkeypatch, state_root):
    _fake_ex(monkeypatch)
    assert S.main([]) == 0
    path = state_root / "data/runtime/sector-rs-daily_last.json"
    doc = json.loads(path.read_text())
    assert doc["status"] == "ok" and doc["summary"]["rows_upserted"] == 686
    _fake_ex(monkeypatch, upsert_result=None)  # db_adapter._execute: None on SQL error
    assert S.main([]) == 1
    bad = json.loads(path.read_text())
    assert bad["status"] == "failed" and bad["ok_at"] == doc["ok_at"]


def test_sector_dry_run_preview_failure_exits_one(monkeypatch, state_root):
    def ex(sql, params=None, fetch=None):
        return None

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=ex))
    assert S.main(["--dry-run"]) == 1


def test_income_holdings_resolve_to_served_persistent_copy(monkeypatch, tmp_path):
    served = tmp_path / "persistent" / "data" / "portfolios" / "state"
    served.mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "persistent"))
    assert M._resolve_state_dir() == served
