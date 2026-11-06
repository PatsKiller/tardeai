"""Injection triage batch 20: SQL values reach the driver as parameters, never as SQL text.

ANCHOR: INJECTION_TRIAGE_20_20261106

Hermetic: a fake cursor records (sql, params); no database, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(1, str(ROOT / "scripts" / "lib"))

import watch_decision_refresh as wdr  # noqa: E402
import watchlist_entry_planner as wep  # noqa: E402

HOSTILE = "x'; DROP TABLE t;--"


class FakeCursor:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.description = [("symbol",)]

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def test_finish_binds_values_and_rejects_unknown_columns():
    conn = FakeConn()
    wdr._finish(conn, 7, "FAILED", failure_class="E", error=HOSTILE)
    [(sql, params)] = conn.cur.calls
    assert HOSTILE not in sql
    assert HOSTILE in params
    assert sql.startswith("UPDATE watch_decision_refresh_jobs SET state=%s, completed_at=now(), failure_class=%s")
    assert params[-1] == 7 and conn.commits == 1

    conn2 = FakeConn()
    with pytest.raises(ValueError):
        wdr._finish(conn2, 7, "FAILED", **{"error=NULL; DROP TABLE t;--": 1})
    assert conn2.cur.calls == [] and conn2.commits == 0


def test_entry_planner_interest_thresholds_are_params(monkeypatch):
    monkeypatch.setattr(wep, "INTEREST_MOVE_PCT", HOSTILE)
    monkeypatch.setattr(wep, "INTEREST_CATALYST_DAYS", HOSTILE)
    cur = FakeCursor()
    wep._candidates(cur, limit=5, buy_rated_cap=11)
    assert len(cur.calls) == 2
    sql, params = cur.calls[1]
    assert HOSTILE not in sql
    assert params == (HOSTILE, wep.INTEREST_MOVE_RVOL, HOSTILE, wep.INTEREST_MOVE_RVOL, HOSTILE,
                      wep.INTEREST_CATALYST_CONF, 11)
    assert sql.count("%s") == len(params)
    assert "%s * interval '1 day'" in sql
    assert "'^[A-Z]{1,5}$'" in sql  # the f-string brace escape still renders the regex quantifier


def test_entry_planner_default_thresholds_keep_types():
    cur = FakeCursor()
    wep._candidates(cur, limit=5, buy_rated_cap=3)
    _, params = cur.calls[1]
    assert isinstance(params[0], float) and isinstance(params[4], int) and params[-1] == 3


@pytest.mark.parametrize("name", [
    "validate_v4_signal_intelligence.py",
    "validate_v5_signal_intelligence.py",
    "validate_v7_cio_intelligence.py",
])
def test_validators_bind_table_name(name):
    src = (ROOT / "scripts" / name).read_text()
    assert "table_name='{t}'" not in src
    assert 'WHERE table_name=%s", (t,))' in src
