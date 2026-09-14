"""Social scalp discovery must not go empty every Monday. Offline: fake connection.

2026-09-14: candidate_discovery ran at 06:15 Monday with ``run_date >=
CURRENT_DATE - 2`` (Saturday), so Friday's social scans were excluded and the
source returned 0; the log shows every fifth run empty and the health ledger
escalated "social_scalp: 0 candidates, last success 76.2h ago".
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from discovery_sources.social_source import SocialSource  # noqa: E402

COVERS = ["scripts/discovery_sources/social_source.py"]


class _Cur:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.sql = rows or [], fail, []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))
        if self.fail:
            raise RuntimeError("column does not exist")

    def fetchall(self):
        return [(r,) for r in self.rows]


class _Conn:
    def __init__(self, cur):
        self.cur, self.rolled_back = cur, False

    def cursor(self):
        return self.cur

    def rollback(self):
        self.rolled_back = True


def test_window_reaches_back_to_the_last_session_with_social_scans():
    conn = _Conn(_Cur(rows=["ELMT", "AXTI"]))
    out = SocialSource().discover(conn, limit=20)
    assert [c["symbol"] if isinstance(c, dict) else getattr(c, "symbol", None) for c in out] == ["ELMT", "AXTI"]
    sql, params = conn.cur.sql[0]
    assert "LEAST( CURRENT_DATE - 2, COALESCE((SELECT max(run_date) FROM trade_ai_scans" in sql
    assert "run_date < CURRENT_DATE AND source ILIKE '%%social%%'" in sql
    assert params == (20,)


def test_a_broken_query_is_reported_not_passed_off_as_no_candidates(capsys):
    conn = _Conn(_Cur(fail=True))
    assert SocialSource().discover(conn) == []
    assert "social_scalp query failed: RuntimeError" in capsys.readouterr().out
    assert conn.rolled_back
