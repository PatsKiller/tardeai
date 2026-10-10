"""Refactor wave 2 (cron -> n8n, 2026-10-10): the learning / scoring lanes.

- agent_recommendation_normalizer.py (cron:L320 --apply): --dry-run wins over --apply, READ ONLY session,
  no INSERT/commit; a real --apply writes agent_recommendation_normalizer_last.json.
- update_agent_performance.py (cron:L427): score() is SELECT-only, --dry-run returns before _write_rows;
  db_adapter connection; a real run writes update_agent_performance_last.json.
- catalyst_calibration.py (cron:L408): --dry-run on a READ ONLY session, never writes the output file;
  a real run writes it plus catalyst_calibration_last.json.
- backtest_history_snapshot.py (cron:L363): --dry-run runs no DDL and no INSERT (a counted SELECT);
  a real run writes backtest_history_snapshot_last.json.
Hermetic: fake connections, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
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

import agent_recommendation_normalizer as arn  # noqa: E402
import backtest_history_snapshot as bhs  # noqa: E402
import catalyst_calibration as cc  # noqa: E402
import update_agent_performance as uap  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


class FakeConn:
    """Answers statements by substring (first match wins); records everything."""

    def __init__(self, answers):
        self.answers = answers
        self.log: list = []
        self.autocommit = False
        self.closed = 0

    def cursor(self, *a, **k):
        conn = self

        class C:
            rowcount = 0

            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat))
                self._rows = next((rows for sub, rows in conn.answers if sub in flat), [])
                self.rowcount = len(self._rows) if flat.upper().startswith("INSERT") else self.rowcount

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

            def close(self):
                pass

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))

    def close(self):
        self.log.append(("close",))

    def sqls(self):
        return [e[1] for e in self.log if e[0] == "execute"]

    def mutations(self):
        bad = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
        return [s for s in self.sqls() if s.lstrip().upper().startswith(bad)]


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _readonly(conn):
    return ("set_session", {"readonly": True}) in conn.log


def _receipt(name):
    return json.loads(llr.receipt_path(name).read_text())


# ── agent_recommendation_normalizer ─────────────────────────────────────────────────────────────
@pytest.fixture
def arn_conn(monkeypatch, state):
    now = datetime(2026, 10, 9, 12, 0)
    conn = FakeConn(
        [
            (
                "FROM watchlist_agent_results",
                [(1, "Maria", "AAA", "BUY", 0.7, now), (2, "Steph", "BBB", "SELL", 0.4, now)],
            ),
            ("FROM cio_decisions", [("D1", "AAA", "HOLD", 0.5, None, now)]),
            ("FROM agent_debate_log", []),
            ("INSERT INTO agent_recommendation_registry", [("x",)]),
        ]
    )
    monkeypatch.setattr(arn, "_get_conn", lambda: conn)
    monkeypatch.setattr(arn, "_tag_recommendation", lambda cur, r: None)
    return conn


@pytest.mark.parametrize("argv", [["--dry-run", "--json"], ["--dry-run", "--apply", "--json"], ["--json"]])
def test_arn_dry_run_reaches_no_write(arn_conn, monkeypatch, capsys, state, argv):
    _forbid(monkeypatch, llr, "write_receipt")
    assert arn.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["inserted"] == 0
    assert out["would_write"] == {"table": "agent_recommendation_registry", "rows": 3}
    assert arn_conn.mutations() == [] and ("commit",) not in arn_conn.log and _readonly(arn_conn)
    assert not state.exists()


def test_arn_dry_run_report_tracks_state(arn_conn, capsys):
    arn.main(["--dry-run", "--json"])
    before = json.loads(capsys.readouterr().out)["would_write"]["rows"]
    arn_conn.answers[0] = ("FROM watchlist_agent_results", [])
    arn.main(["--dry-run", "--json"])
    after = json.loads(capsys.readouterr().out)["would_write"]["rows"]
    assert (before, after) == (3, 1)


def test_arn_save_returns_before_insert_on_dry_run():
    src = inspect.getsource(arn.save_recommendations)
    assert src.index("if dry_run:\n        return len(recs)") < src.index("INSERT INTO")


def test_arn_apply_writes_and_receipts(arn_conn, capsys):
    assert arn.main(["--apply", "--json"]) == 0
    assert len(arn_conn.mutations()) == 3 and ("commit",) in arn_conn.log and not _readonly(arn_conn)
    rc = _receipt("agent_recommendation_normalizer")
    assert rc["status"] == "ok" and rc["ok_at"] and rc["summary"]["inserted"] == 3


def test_arn_apply_failure_receipt_and_raise(arn_conn, monkeypatch):
    def broken(conn, *a):
        raise RuntimeError("relation missing")

    monkeypatch.setattr(arn, "normalize_cio_decisions", broken)
    with pytest.raises(RuntimeError):
        arn.main(["--apply"])
    rc = _receipt("agent_recommendation_normalizer")
    assert rc["status"] == "failed" and rc["ok_at"] is None


# ── update_agent_performance ────────────────────────────────────────────────────────────────────
@pytest.fixture
def uap_conn(monkeypatch, state):
    t = datetime(2026, 10, 1, 12, 0)
    conn = FakeConn(
        [
            ("FROM decision_outcomes", [(1, "AAA", "buy", 100.0, 110.0, None, t)]),
            ("FROM watchlist_agent_results", [(9, "AAA", "Maria", "buy", 0.8, t - timedelta(hours=3))]),
            ("INSERT INTO agent_performance_history", [(77,)]),
        ]
    )
    monkeypatch.setattr(uap, "_get_conn", lambda: conn)
    return conn


def test_uap_dry_run_reaches_no_write(uap_conn, monkeypatch, capsys, state):
    _forbid(monkeypatch, uap, "_write_rows")
    _forbid(monkeypatch, llr, "write_receipt")
    assert uap.run(dry_run=True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["would_write"] == {"table": "agent_performance_history", "rows": 1}
    assert out["agents"][0]["agent"] == "Maria" and out["agents"][0]["accuracy_pct"] == 100.0
    assert uap_conn.mutations() == [] and ("commit",) not in uap_conn.log and _readonly(uap_conn)
    assert not state.exists()


def test_uap_dry_run_report_tracks_state(uap_conn, capsys):
    uap.run(dry_run=True)
    before = json.loads(capsys.readouterr().out)["agents"][0]["accuracy_pct"]
    uap_conn.answers[0] = ("FROM decision_outcomes", [(1, "AAA", "buy", 100.0, 90.0, None, datetime(2026, 10, 1, 12))])
    uap.run(dry_run=True)
    after = json.loads(capsys.readouterr().out)["agents"][0]["accuracy_pct"]
    assert (before, after) == (100.0, 0.0)


def test_uap_score_is_select_only_and_db_adapter():
    assert "INSERT" not in inspect.getsource(uap.score)
    src = (ROOT / "scripts" / "update_agent_performance.py").read_text()
    assert "DB_PASSWORD" not in src and "from db_adapter import _get_conn" in src
    run_src = inspect.getsource(uap.run)
    assert run_src.index("return 0") < run_src.index("_write_rows(cur")


def test_uap_real_run_writes_row_and_receipt(uap_conn, capsys):
    assert uap.run() == 0
    assert len(uap_conn.mutations()) == 1 and ("commit",) in uap_conn.log
    rc = _receipt("update_agent_performance")
    assert rc["status"] == "ok" and rc["summary"]["agents_scored"] == 1
    assert "Maria" in capsys.readouterr().out


# ── catalyst_calibration ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def cc_env(monkeypatch, state, tmp_path):
    conn = FakeConn(
        [("FROM catalyst_events", [("earnings", "bullish", 10.0, 11.0), ("earnings", "bearish", 10.0, 11.0)])]
    )
    monkeypatch.setattr(cc, "_db", lambda: conn)
    out = tmp_path / "runtime" / "catalyst_calibration.json"
    monkeypatch.setattr(cc, "OUT", out)
    return conn, out


def test_cc_dry_run_reaches_no_write(cc_env, monkeypatch, capsys, state):
    conn, out = cc_env
    _forbid(monkeypatch, llr, "write_receipt")
    assert cc.main(["--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert '"total_settled_catalysts": 2' in printed and "nothing written" in printed
    assert not out.exists() and not out.parent.exists() and not state.exists()
    assert _readonly(conn) and conn.mutations() == []


def test_cc_dry_run_report_tracks_state(cc_env, capsys):
    conn, _ = cc_env
    cc.main(["--dry-run"])
    before = capsys.readouterr().out
    conn.answers[0] = ("FROM catalyst_events", [])
    cc.main(["--dry-run"])
    after = capsys.readouterr().out
    assert '"total_settled_catalysts": 2' in before and '"total_settled_catalysts": 0' in after


def test_cc_real_run_writes_output_and_receipt(cc_env):
    conn, out = cc_env
    assert cc.main([]) == 0
    doc = json.loads(out.read_text())
    assert doc["by_type"]["earnings"]["samples"] == 2 and doc["by_type"]["earnings"]["hit_rate"] == 0.5
    rc = _receipt("catalyst_calibration")
    assert rc["status"] == "ok" and rc["summary"]["settled_catalysts"] == 2


def test_cc_output_resolves_through_the_resolution_layer():
    src = inspect.getsource(cc._out_path)
    assert 'resolve_durable_dir("data/runtime", ROOT)' in src


# ── backtest_history_snapshot ───────────────────────────────────────────────────────────────────
@pytest.fixture
def bhs_conn(monkeypatch, state):
    conn = FakeConn(
        [
            ("to_regclass", [(True,)]),
            ("SELECT COUNT(*) FROM ( SELECT r.run_id", [(3,)]),
            ("SELECT COUNT(*) FROM backtest_result_history", [(40,)]),
            ("INSERT INTO backtest_result_history", [(1,), (2,), (3,)]),
        ]
    )
    monkeypatch.setattr(bhs.psycopg2, "connect", lambda **kw: conn)
    return conn


def test_bhs_dry_run_runs_no_ddl_and_no_insert(bhs_conn, monkeypatch, capsys, state):
    _forbid(monkeypatch, llr, "write_receipt")
    assert bhs.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["would_write"] == {"table": "backtest_result_history", "rows": 3} and out["history_rows"] == 40
    assert bhs_conn.mutations() == [] and _readonly(bhs_conn) and not state.exists()


def test_bhs_dry_run_report_tracks_state(bhs_conn, capsys):
    bhs.main(["--dry-run"])
    before = json.loads(capsys.readouterr().out)["would_write"]["rows"]
    bhs_conn.answers[1] = ("SELECT COUNT(*) FROM ( SELECT r.run_id", [(0,)])
    bhs.main(["--dry-run"])
    after = json.loads(capsys.readouterr().out)["would_write"]["rows"]
    assert (before, after) == (3, 0)


def test_bhs_preview_is_select_only():
    src = inspect.getsource(bhs.preview)
    assert "execute(DDL)" not in src and "execute(SNAPSHOT)" not in src
    assert "INSERT" not in bhs.PREVIEW and "INSERT" not in bhs.PREVIEW_NO_TABLE


def test_bhs_real_run_appends_and_receipts(bhs_conn):
    assert bhs.main([]) == 0
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS") for s in bhs_conn.sqls())
    rc = _receipt("backtest_history_snapshot")
    assert rc["status"] == "ok" and rc["summary"] == {"appended": 3, "history_rows": 40}
