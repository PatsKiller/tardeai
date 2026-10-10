"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V3 -- learning lanes.

- agent_calibration_engine.py (cron:L314), enterprise_backtester.py (cron:L349),
  setup_quality_prior.py (cron:L369), backtest_results_aggregator.py (cron:L605).

Each: --dry-run cannot REACH a write (AGENTS.md §6) -- no INSERT/TRUNCATE/DDL executed, READ ONLY
session where a connection is held, no yfinance fetch, no report/cache file, no receipt; a real run
writes data/runtime/<lane_id>_last.json (LaneRunReceipt@v1, keyed by the lane_registry lane id) with
ok_at only on success and a failed receipt + non-zero exit on failure. Hermetic: fake DB connections, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

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

WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP")


def _load(name: str):
    """Import scripts/<name>.py under a private module name. A worktree / CI checkout has no .env,
    and some of these scripts read it at import time -- serve an empty one for that read only."""
    orig = Path.read_text

    def read_text(self, *a, **k):
        if self.name == ".env":
            return ""
        return orig(self, *a, **k)

    with mock.patch.object(Path, "read_text", read_text):
        spec = importlib.util.spec_from_file_location(f"w2v3_{name}", SCRIPTS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class FakeConn:
    """Records every statement; `responder(sql, params) -> rows` (list of dicts) serves reads."""

    def __init__(self, responder=None, dict_rows=True, fail_on=None):
        self.responder = responder or (lambda sql, params: [])
        self.dict_rows = dict_rows
        self.fail_on = fail_on
        self.sql: list[str] = []
        self.calls: list = []
        self.autocommit = False

    def cursor(self, *a, **k):
        conn = self

        class C:
            rowcount = 1
            description = None

            def execute(self, sql, params=None):
                flat = " ".join(str(sql).split())
                conn.sql.append(flat)
                if conn.fail_on and flat.upper().startswith(conn.fail_on):
                    raise RuntimeError("simulated write failure")
                self._rows = list(conn.responder(flat, params) or [])
                if self._rows and isinstance(self._rows[0], dict):
                    self.description = [(k,) for k in self._rows[0]]

            def _conv(self, r):
                return r if conn.dict_rows or not isinstance(r, dict) else tuple(r.values())

            def fetchall(self):
                return [self._conv(r) for r in self._rows]

            def fetchone(self):
                return self._conv(self._rows[0]) if self._rows else None

        return C()

    def writes(self):
        return [s for s in self.sql if s.upper().lstrip("( ").startswith(WRITE_PREFIXES)]

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def set_session(self, **kw):
        self.calls.append(("set_session", kw))

    def close(self):
        self.calls.append("close")


def _receipt(tmp_path, name):
    p = tmp_path / "data" / "runtime" / f"{name}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


# ── agent_calibration_engine (cron:L314) ──────────────────────────────────────


def _calib_rows(sql, params):
    if "FROM agent_recommendation_registry" in sql:
        return [
            {
                "recommendation_id": "R1",
                "agent_name": "Maria",
                "symbol": "AAA",
                "strategy_id": "s",
                "recommendation_type": "buy",
                "confidence": 0.8,
                "recommendation_time": None,
                "outcome_type": "trade",
                "paper_trade_id": 7,
                "proposal_id": None,
                "link_confidence": 1,
            }
        ]
    if "FROM paper_trades" in sql:
        return [{"status": "closed", "pnl": 10, "r_multiple": 1.0}]
    return []


def test_calibration_dry_run_wins_over_apply_and_writes_nothing(state, monkeypatch):
    ace = _load("agent_calibration_engine")
    conn = FakeConn(_calib_rows, dict_rows=False)
    monkeypatch.setattr(ace, "_get_conn", lambda: conn)
    assert ace.main(["--apply", "--dry-run", "--json"]) == 0
    assert conn.writes() == []
    assert ("set_session", {"readonly": True}) in conn.calls
    assert "commit" not in conn.calls
    assert _receipt(state, "agent-calibration-engine") is None


def test_calibration_apply_writes_receipt_and_reports_cap(state, monkeypatch, capsys):
    ace = _load("agent_calibration_engine")
    conn = FakeConn(_calib_rows, dict_rows=False)
    monkeypatch.setattr(ace, "_get_conn", lambda: conn)
    assert ace.main(["--apply", "--json"]) == 0
    assert any(s.startswith("INSERT INTO agent_calibration_events") for s in conn.writes())
    rec = _receipt(state, "agent-calibration-engine")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["calibration_events"] == 1
    assert json.loads(capsys.readouterr().out)["events_capped"] is False
    assert any(s.endswith(f"LIMIT {ace.ROW_CAP}") for s in conn.sql)  # the cap the output reports


def test_calibration_failed_write_leaves_failed_receipt_and_raises(state, monkeypatch):
    ace = _load("agent_calibration_engine")
    conn = FakeConn(_calib_rows, dict_rows=False, fail_on="INSERT")
    monkeypatch.setattr(ace, "_get_conn", lambda: conn)
    with pytest.raises(RuntimeError):
        ace.main(["--apply"])
    rec = _receipt(state, "agent-calibration-engine")
    assert rec["status"] == "failed" and rec["ok_at"] is None


# ── enterprise_backtester (cron:L349) ─────────────────────────────────────────

_TRADE = {
    "id": 1,
    "symbol": "AAA",
    "strategy_id": "swing",
    "entry_price": 10,
    "exit_price": 11,
    "stop_loss": 9,
    "target_1": 12,
    "shares": 1,
    "pnl": 1,
    "exit_reason": "target",
    "entry_time": "2026-09-01",
    "closed_at": "2026-09-05",
    "account": "",
    "broker": "",
    "source_table": "trades",
}


def _bt_setup(monkeypatch, ebt, fetch=None, save=None):
    monkeypatch.setattr(ebt, "get_trades_from_db", lambda: [dict(_TRADE)])
    monkeypatch.setattr(ebt, "load_ohlc_cache", lambda: {})
    monkeypatch.setattr(ebt, "load_close_cache", lambda: {})
    monkeypatch.setattr(ebt, "fetch_ohlc_for_symbols", fetch or mock.Mock(side_effect=AssertionError("fetch")))
    monkeypatch.setattr(ebt, "save_results_to_db", save or mock.Mock(side_effect=AssertionError("save")))


def test_backtester_dry_run_never_fetches_saves_or_writes_files(state, monkeypatch, tmp_path):
    ebt = _load("enterprise_backtester")
    _bt_setup(monkeypatch, ebt)
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    report = ebt.main(
        ["--replay-trades", "--apply", "--dry-run", "--output-json", str(out_json), "--output-md", str(out_md)]
    )
    assert report["mode"] == "dry_run" and report["would_fetch_ohlc_symbols"] == 1
    assert not out_json.exists() and not out_md.exists()
    assert _receipt(state, "enterprise-backtester") is None


def test_backtester_apply_fetches_saves_and_writes_receipt(state, monkeypatch):
    ebt = _load("enterprise_backtester")
    bars = {
        "AAA": {
            "2026-09-01": {"o": 10, "h": 10.5, "l": 9.8, "c": 10.2, "v": 1},
            "2026-09-02": {"o": 10.2, "h": 12.5, "l": 10.1, "c": 12.2, "v": 1},
        }
    }
    save = mock.Mock()
    _bt_setup(monkeypatch, ebt, fetch=mock.Mock(return_value=bars), save=save)
    report = ebt.main(["--replay-trades", "--apply"])
    assert save.called and report["mode"] == "apply"
    rec = _receipt(state, "enterprise-backtester")
    assert rec["status"] == "ok" and rec["summary"]["run_id"] == report["run_id"]


def test_backtester_failed_save_is_a_failed_receipt(state, monkeypatch):
    ebt = _load("enterprise_backtester")
    bars = {
        "AAA": {
            "2026-09-01": {"o": 10, "h": 10.5, "l": 9.8, "c": 10.2, "v": 1},
            "2026-09-02": {"o": 10.2, "h": 12.5, "l": 10.1, "c": 12.2, "v": 1},
        }
    }
    _bt_setup(monkeypatch, ebt, fetch=mock.Mock(return_value=bars), save=mock.Mock(side_effect=RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        ebt.main(["--replay-trades", "--apply"])
    assert _receipt(state, "enterprise-backtester")["status"] == "failed"


# ── setup_quality_prior (cron:L369) ───────────────────────────────────────────


def _prior_rows(sql, params):
    if "FROM trade_backtest_results WHERE entry_rsi" in sql:
        return [{"band": "<40", "n": 10, "win_rate": 40, "avg_pnl": 1, "avg_left": 4000, "grade_score": 45}]
    if "FROM paper_trade_proposals" in sql:
        return [{"id": 1, "symbol": "AAA", "status": "PENDING", "rsi": 30}]
    if "FROM incubator_universe" in sql:
        return [{"symbol": "BBB", "status": "ACTIVE"}]
    if "FROM ticker_snapshot_daily" in sql:
        return [{"rsi": 35, "snapshot_date": "2026-10-01"}]
    return []


def test_setup_prior_dry_run_executes_no_ddl_truncate_or_insert(state, monkeypatch):
    sqp = _load("setup_quality_prior")
    conn = FakeConn(_prior_rows)
    monkeypatch.setattr(sqp.psycopg2, "connect", lambda **kw: conn)
    assert sqp.main(["--dry-run"]) == 0
    assert conn.writes() == []
    assert conn.calls[:2] == ["rollback", ("set_session", {"readonly": True})]
    assert _receipt(state, "setup-quality-prior") is None


def test_setup_prior_real_run_rebuilds_and_writes_receipt(state, monkeypatch):
    sqp = _load("setup_quality_prior")
    conn = FakeConn(_prior_rows)
    monkeypatch.setattr(sqp.psycopg2, "connect", lambda **kw: conn)
    assert sqp.main([]) == 0
    w = conn.writes()
    assert w[0].startswith("CREATE TABLE IF NOT EXISTS setup_quality_prior")
    assert "TRUNCATE setup_quality_prior" in w and any(s.startswith("INSERT INTO proposal_setup_advisory") for s in w)
    rec = _receipt(state, "setup-quality-prior")
    assert rec["status"] == "ok" and rec["summary"] == {
        "prior_bands": 1,
        "proposal_advisories": 1,
        "candidate_advisories": 1,
    }


def test_setup_prior_failure_is_failed_receipt(state, monkeypatch):
    sqp = _load("setup_quality_prior")
    conn = FakeConn(_prior_rows, fail_on="TRUNCATE")
    monkeypatch.setattr(sqp.psycopg2, "connect", lambda **kw: conn)
    with pytest.raises(RuntimeError):
        sqp.main([])
    assert _receipt(state, "setup-quality-prior")["status"] == "failed"


# ── backtest_results_aggregator (cron:L605) ───────────────────────────────────


def _agg_rows(sql, params):
    if "FROM strategy_backtest_runs" in sql:
        return [
            {"run_id": "R1", "strategy_id": "s", "run_type": "replay"},
            {"run_id": "R2", "strategy_id": "s", "run_type": "replay"},
        ]
    if "FROM strategy_backtest_trades" in sql:
        if params == ["R1"]:
            return [
                {"pnl": 5, "pnl_pct": 1, "r_multiple": 1.0, "entry_date": "2026-09-01", "exit_reason": "t"},
                {"pnl": -2, "pnl_pct": -1, "r_multiple": -0.5, "entry_date": "2026-09-02", "exit_reason": "s"},
            ]
        return []
    return []


def _agg(monkeypatch, conn):
    agg = _load("backtest_results_aggregator")
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    return agg


def test_aggregator_dry_run_inserts_nothing(state, monkeypatch):
    conn = FakeConn(_agg_rows)
    agg = _agg(monkeypatch, conn)
    assert agg.main(["--dry-run"]) == 0
    assert conn.writes() == [] and ("set_session", {"readonly": True}) in conn.calls
    assert _receipt(state, "backtest-results-aggregator") is None


def test_aggregator_real_run_counts_inserted_vs_skipped(state, monkeypatch):
    conn = FakeConn(_agg_rows)
    agg = _agg(monkeypatch, conn)
    assert agg.main([]) == 0
    assert len([s for s in conn.writes() if s.startswith("INSERT INTO strategy_backtest_results")]) == 1
    rec = _receipt(state, "backtest-results-aggregator")
    assert rec["status"] == "ok"
    assert rec["summary"] == {"pending": 2, "aggregated": 1, "skipped_no_trades": 1}


def test_aggregator_failed_insert_is_failed_receipt(state, monkeypatch):
    conn = FakeConn(_agg_rows, fail_on="INSERT")
    agg = _agg(monkeypatch, conn)
    with pytest.raises(RuntimeError):
        agg.main([])
    assert _receipt(state, "backtest-results-aggregator")["status"] == "failed"
