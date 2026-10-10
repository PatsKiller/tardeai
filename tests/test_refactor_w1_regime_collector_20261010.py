"""Refactor wave 1 (cron -> n8n, 2026-10-10): scripts/market_regime_collector.py (cron L199 / L213).

- --dry-run collects and reports, wins over --apply, runs on a READ ONLY session, and returns before
  save_indicators is reachable (AGENTS.md §6) -- no DB write, no receipt, no file.
- a real run (--apply) writes data/runtime/market_regime_collector_last.json, ok_at only on success;
  a failing save leaves a failed receipt and exits non-zero.
Hermetic: fake DB connection, VIX/session collectors stubbed, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import market_regime_collector as mrc  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


class FakeConn:
    def __init__(self, breadth=60):
        self.log: list = []
        self.breadth = breadth

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                conn.log.append(("execute", " ".join(sql.split())[:40]))
                self._sql = sql

            def fetchone(self):
                s = self._sql
                if "COUNT(DISTINCT symbol)" in s:
                    return (conn.breadth, conn.breadth * 2)
                if "AVG(score)" in s:
                    return (Decimal("65"), 1)
                if "AVG(ABS(gap_pct))" in s:
                    return (Decimal("2.0"), 1)
                if "data_source_health" in s:
                    return ("finviz", "healthy", False)
                return (None,)

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))

    def close(self):
        self.log.append(("close",))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    conn = FakeConn()
    monkeypatch.setattr(mrc, "_get_conn", lambda: conn)
    monkeypatch.setattr(mrc, "collect_vix", lambda sid: None)
    monkeypatch.setattr(
        mrc,
        "collect_market_session",
        lambda sid: {
            "indicator_id": "I",
            "snapshot_id": sid,
            "indicator_key": "market_session",
            "value_text": "closed",
        },
    )
    saved = []
    monkeypatch.setattr(mrc, "save_indicators", lambda c, inds, dry_run=True: saved.append(len(inds)))
    return {"conn": conn, "saved": saved, "root": tmp_path}


def _forbid_receipt(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run reached write_receipt")

    monkeypatch.setattr(llr, "write_receipt", boom)


@pytest.mark.parametrize("argv", [["--dry-run"], ["--dry-run", "--apply"], [], ["--dry-run", "--json"]])
def test_dry_run_reaches_no_write(env, monkeypatch, capsys, argv):
    _forbid_receipt(monkeypatch)
    assert mrc.main(argv) == 0
    assert env["saved"] == [], "save_indicators reached from a dry run"
    assert ("commit",) not in env["conn"].log
    assert ("set_session", {"readonly": True}) in env["conn"].log, "dry run must run on a READ ONLY session"
    assert not (env["root"] / "data").exists(), "dry run wrote a file under the state root"
    out = capsys.readouterr().out
    assert "dry_run" in out


def test_dry_run_reports_what_it_would_write_and_tracks_state(env, monkeypatch, capsys):
    _forbid_receipt(monkeypatch)
    mrc.main(["--dry-run", "--json"])
    first = json.loads(capsys.readouterr().out)
    assert first["would_write"] == {"table": "market_regime_indicators", "rows": first["indicators_collected"]}
    # Mutation test (§6): change the underlying state, the report changes with it.
    env["conn"].breadth = 5
    mrc.main(["--dry-run", "--json"])
    second = json.loads(capsys.readouterr().out)
    sig = {i["indicator_key"]: i.get("signal") for i in second["indicators"]}
    assert sig["scan_breadth_24h"] == "missing"
    assert {i["indicator_key"]: i.get("signal") for i in first["indicators"]}["scan_breadth_24h"] == "broad"


def test_source_order_dry_run_returns_before_save_is_reachable():
    src = inspect.getsource(mrc.main)
    assert src.index("# returns before save_indicators is reachable") < src.index(
        "save_indicators(conn, indicators, dry_run=False)"
    )


def test_apply_writes_ok_receipt(env, capsys):
    assert mrc.main(["--apply"]) == 0
    assert env["saved"] and env["saved"][0] >= 3
    doc = json.loads((env["root"] / "data/runtime/market_regime_collector_last.json").read_text())
    assert doc["status"] == "ok" and doc["ok_at"] and doc["summary"]["indicators_collected"] == env["saved"][0]
    assert "Collected" in capsys.readouterr().out and ("set_session", {"readonly": True}) not in env["conn"].log


def test_apply_failure_leaves_failed_receipt_and_raises(env, monkeypatch):
    mrc_path = env["root"] / "data/runtime/market_regime_collector_last.json"
    mrc.main(["--apply"])
    ok_at = json.loads(mrc_path.read_text())["ok_at"]

    def bad_save(*a, **k):
        raise RuntimeError("LockNotAvailable")

    monkeypatch.setattr(mrc, "save_indicators", bad_save)
    with pytest.raises(RuntimeError):
        mrc.main(["--apply"])
    doc = json.loads(mrc_path.read_text())
    assert doc["status"] == "failed" and doc["ok_at"] == ok_at
    assert doc["error"] == "RuntimeError" and "LockNotAvailable" not in json.dumps(doc)  # type only, never the message


def test_entrypoint_exits_with_mains_code():
    src = (ROOT / "scripts" / "market_regime_collector.py").read_text()
    assert "sys.exit(main())" in src
