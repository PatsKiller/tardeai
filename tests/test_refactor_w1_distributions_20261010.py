"""n8n refactor wave 1 (W2), 2026-10-10 — distributions_enrich.py (cron:L553).

The old ``--dry`` ran ``ensure_columns()`` (ALTER TABLE symbol_profiles) before computing anything, so the
"dry" run took the table's ACCESS EXCLUSIVE lock — the same DDL behind the 7 ``LockNotAvailable`` failures in
distributions_enrich.log. Now: ``--dry-run``/``--dry`` reaches no DDL, no upsert, no commit, no receipt; a
real run issues the ALTER only when a column is actually missing (information_schema read first); a real run
writes a LaneRunReceipt@v1 and exits 1 when every symbol failed. Offline: yfinance and the DB are fakes.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import distributions_enrich as de  # noqa: E402

COVERS = ["scripts/distributions_enrich.py"]


class _Cur:
    def __init__(self, conn):
        self.conn, self._rows = conn, []
        self.connection = conn

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        if "information_schema.columns" in sql:
            self._rows = [(c,) for c in self.conn.columns]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, columns):
        self.columns, self.sql, self.commits = columns, [], 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _divs(n=8, gap=30, amount=0.4):
    today = datetime.now()
    return {today - timedelta(days=gap * i + 5): amount for i in range(n)}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    conn = _Conn(list(de.DIST_COLUMNS))
    monkeypatch.setattr(de, "_conn", lambda: conn)
    data = {"JEPI": _divs(gap=30), "SCHD": _divs(gap=91)}
    yf = type(sys)("yfinance")

    def ticker(sym):
        if isinstance(data.get(sym), Exception):
            raise data[sym]
        return SimpleNamespace(dividends=data.get(sym, {}))

    yf.Ticker = ticker
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    upserts = []
    monkeypatch.setattr(
        de,
        "upsert_profile",
        lambda cur, s, fields, source: upserts.append((s, fields)) or SimpleNamespace(rows_written=1, rejected=[]),
    )
    return {
        "root": tmp_path,
        "conn": conn,
        "data": data,
        "upserts": upserts,
        "receipt": tmp_path / "data/runtime/distributions_enrich_last.json",
    }


def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["distributions_enrich.py", "--symbols", "JEPI,SCHD", *argv])
    return de.main()


@pytest.mark.parametrize("flag", ["--dry-run", "--dry"])
def test_dry_run_reaches_no_ddl_no_upsert_no_commit_no_receipt(env, monkeypatch, capsys, flag):
    monkeypatch.setattr(de, "ensure_columns", lambda: pytest.fail("DDL reached"))
    import lib.lane_last_receipt as llr

    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: pytest.fail("receipt reached"))
    assert _main(monkeypatch, flag) == 0
    out = capsys.readouterr().out
    assert "dry run — nothing written; would upsert 2 symbol_profiles rows" in out
    assert "would ALTER TABLE for missing columns: none" in out
    assert '"distribution_cadence": "monthly"' in out and '"distribution_cadence": "quarterly"' in out
    assert env["upserts"] == [] and env["conn"].commits == 0
    assert not any("ALTER" in s for s in env["conn"].sql) and not env["receipt"].exists()


def test_dry_run_mutation_tested_rows_follow_the_source(env, monkeypatch, capsys):
    _main(monkeypatch, "--dry-run")
    first = capsys.readouterr().out
    env["data"]["SCHD"] = _divs(gap=365, amount=1.5)
    _main(monkeypatch, "--dry-run")
    second = capsys.readouterr().out
    assert first != second and '"distribution_cadence": "annual"' in second


def test_source_order_ddl_only_on_the_apply_path():
    src = inspect.getsource(de.run)
    assert src.index("if apply:") < src.index("ensure_columns()") < src.index("syms = symbols or")
    m = inspect.getsource(de.main)
    assert m.index("if a.dry:") < m.index("return 0") < m.index("run(symbols=syms, apply=True)")


def test_ensure_columns_skips_the_alter_when_columns_exist(env):
    de.ensure_columns()
    assert not any("ALTER" in s for s in env["conn"].sql) and env["conn"].commits == 0
    env["conn"].columns = list(de.DIST_COLUMNS[:-1])
    de.ensure_columns()
    assert any("ALTER TABLE symbol_profiles" in s for s in env["conn"].sql) and env["conn"].commits == 1


def test_real_run_upserts_and_writes_receipt_ok_at(env, monkeypatch):
    assert _main(monkeypatch) == 0
    assert [s for s, _ in env["upserts"]] == ["JEPI", "SCHD"] and env["conn"].commits == 1
    rc = json.loads(env["receipt"].read_text())
    assert rc["status"] == "ok" and rc["ok_at"] == rc["finished_at"] and rc["summary"]["updated"] == 2


def test_every_symbol_failing_exits_1_some_failing_is_a_finding(env, monkeypatch):
    env["data"]["JEPI"] = RuntimeError("yahoo 429")
    assert _main(monkeypatch) == 0  # one of two failed: a finding, not a failed run
    ok_at = json.loads(env["receipt"].read_text())["ok_at"]
    assert ok_at
    env["data"]["SCHD"] = RuntimeError("yahoo 429")
    assert _main(monkeypatch) == 1
    rc = json.loads(env["receipt"].read_text())
    assert rc["status"] == "failed" and rc["summary"]["errors"] == 2 and rc["ok_at"] == ok_at


def test_proposed_allowlist_argv_is_dispatcher_eligible():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    entry = {
        "lane_id": "distributions-enrich",
        "command": ["$PY", "scripts/distributions_enrich.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": [],
    }
    assert dispatcher_eligible(entry) == (True, "ok")
