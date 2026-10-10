"""Refactor wave 1 (cron -> n8n, 2026-10-10): scripts/sync_watchlist_items_to_db.py (cron L210).

- --dry-run reads the same JSON sources from the SERVED state dir and reports the upserts a real run
  would make; it never opens a DB connection, so no write is reachable (AGENTS.md §6).
- a real run executes the same SQL as before, in the same order, then writes
  sync_watchlist_items_to_db_last.json (ok_at only on success); a DB failure leaves a failed receipt and
  a non-zero exit.
Hermetic: tmp state dir, fake connection, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_watchlist_items_to_db as sw  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


class FakeConn:
    def __init__(self, fail=False):
        self.fail, self.sql = fail, []
        self.committed = self.closed = False

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                if conn.fail:
                    raise RuntimeError("connection reset")
                conn.sql.append((" ".join(sql.split())[:30], params))

            def close(self):
                pass

        return C()

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    sd = tmp_path / "pstate"
    sd.mkdir()
    (sd / "holdings.json").write_text(
        json.dumps({"holdings": [{"symbol": "AAA", "market_value": 500}, {"symbol": "CASH", "market_value": 9e9}]})
    )
    (sd / "discovery_candidates.json").write_text(json.dumps({"candidates": [{"symbol": "BBB", "bucket": "b1"}]}))
    (sd / "ai_watchlist.json").write_text(json.dumps({"watchlist": [{"symbol": "CCC"}]}))
    (sd / "watchlist.json").write_text(json.dumps(["DDD", {"symbol": "EEE"}]))
    monkeypatch.setattr(sw, "STATE_DIR", sd)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    conn = FakeConn()
    monkeypatch.setattr(sw, "_get_conn", lambda: conn)
    return {"sd": sd, "conn": conn, "state": tmp_path / "state"}


def test_dry_run_never_opens_a_connection(env, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("dry run reached a write path")

    monkeypatch.setattr(sw, "_get_conn", boom)
    monkeypatch.setattr(llr, "write_receipt", boom)
    assert sw.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["upserted"] == 5
    assert out["would_write"] == {"watchlist_items": 5, "watchlist_events": 1}
    assert out["sample"] == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    assert not env["state"].exists()


def test_dry_run_report_tracks_state(env, capsys):
    sw.main(["--dry-run"])
    first = json.loads(capsys.readouterr().out)["upserted"]
    (env["sd"] / "watchlist.json").write_text(json.dumps(["DDD"]))
    sw.main(["--dry-run"])
    assert (first, json.loads(capsys.readouterr().out)["upserted"]) == (5, 4)


def test_source_order_dry_run_returns_before_connect():
    src = inspect.getsource(sw.sync)
    assert src.index("if dry_run:") < src.index("conn = _get_conn()")


def test_real_run_same_sql_then_ok_receipt(env, capsys):
    assert sw.main([]) == 0
    sqls = [s for s, _ in env["conn"].sql]
    assert sqls[:5] == ["INSERT INTO watchlist_items (s"] * 5 and sqls[5].startswith("INSERT INTO watchlist_even")
    assert env["conn"].committed and env["conn"].closed
    assert {p[0] for _, p in env["conn"].sql[:5]} == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    doc = json.loads((env["state"] / "data/runtime/sync_watchlist_items_to_db_last.json").read_text())
    assert doc["status"] == "ok" and doc["ok_at"] and doc["summary"]["upserted"] == 5
    assert "Upserted 5 items" in capsys.readouterr().out


def test_db_failure_is_nonzero_with_failed_receipt(env):
    env["conn"].fail = True
    with pytest.raises(RuntimeError):
        sw.main([])
    doc = json.loads((env["state"] / "data/runtime/sync_watchlist_items_to_db_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None


def test_state_dir_resolves_through_the_served_portfolio_state():
    assert "portfolio_state_write_targets(PROJECT_ROOT)[0]" in inspect.getsource(sw._state_dir)
