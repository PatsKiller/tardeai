"""Source liveness that actually records, and Alpha Vantage asked about the right names.

2026-09-14: alpha_vantage's data_source_health row read 'unknown' since
2026-05-09 while the lane ran every Monday -- cron does not source .env, so
report_source's own connection had no password and failed inside a swallowed
exception. The lane itself stored ONE symbol a week: the first five rows of an
unordered UNION (micro-caps Alpha Vantage does not cover), with quota notices
skipped silently. Offline: fake cursor and env file, no network, no database.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/lib/data_source_report.py", "scripts/external_market_data_ingest.py"]


def _load(relpath: str):
    name = "shav_" + relpath.replace("/", "_").removesuffix(".py")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_db_setting_falls_back_to_the_project_env_file(tmp_path, monkeypatch):
    dsr = _load("scripts/lib/data_source_report.py")
    env = tmp_path / ".env"
    env.write_text("DB_NAME=from_file\nDB_PASSWORD='quoted-value'\n", encoding="utf-8")
    monkeypatch.setattr(dsr, "_ENV_FILE", str(env))
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    assert dsr._db_setting("DB_PASSWORD") == "quoted-value"
    assert dsr._db_setting("DB_NAME", "trade_ai") == "from_file"
    monkeypatch.setenv("DB_NAME", "from_environ")
    assert dsr._db_setting("DB_NAME") == "from_environ"
    assert dsr._db_setting("DB_MISSING", "dflt") == "dflt"


def test_a_failed_health_write_is_reported_once_not_swallowed(monkeypatch, capsys):
    dsr = _load("scripts/lib/data_source_report.py")
    monkeypatch.delenv("DATA_SOURCE_REPORT_DISABLED", raising=False)
    monkeypatch.setattr(dsr, "_warned", False)
    monkeypatch.setattr(dsr, "_own_conn", lambda: (_ for _ in ()).throw(RuntimeError("no password")))
    dsr.report_source("alpha_vantage", False, error="x")
    dsr.report_source("alpha_vantage", False, error="x")
    err = capsys.readouterr().err
    assert err.count("could not record alpha_vantage") == 1


class _Cur:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.sql = rows or [], fail, []
        self.connection = type("C", (), {"rollback": lambda self: None})()

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if self.fail:
            raise RuntimeError("relation does not exist")

    def fetchall(self):
        return [(r,) for r in self.rows]


def test_alpha_vantage_asks_about_held_and_watched_names_oldest_first():
    ing = _load("scripts/external_market_data_ingest.py")
    cur = _Cur(rows=["V", "WMT", "HPE"])
    assert ing._alpha_vantage_symbols(cur, 5) == ["V", "WMT", "HPE"]
    sql, params = cur.sql[0]
    # the real book (holdings.json) is tier 0; priority orders before fetch age
    assert "unnest(%s::text[])" in sql and "in_directive_watch" in sql
    assert "ORDER BY b.pri, l.at NULLS FIRST" in sql
    assert isinstance(params[0], list) and params[1] == 5


def test_selection_failure_falls_back_and_says_so(monkeypatch, capsys):
    ing = _load("scripts/external_market_data_ingest.py")
    monkeypatch.setattr(ing, "_get_symbols", lambda: ["AAA", "BBB", "CCC"])
    assert ing._alpha_vantage_symbols(_Cur(fail=True), 2) == ["AAA", "BBB"]
    assert "symbol selection query failed" in capsys.readouterr().out
