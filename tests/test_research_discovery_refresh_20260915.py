"""research_discovery reported 'error' for 7 days while surfacing 60 names a day (R-02, 2026-09-15)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import research_watchlist_discovery as rwd  # noqa: E402


class _Cur:
    def __init__(self, inserted):
        self.inserted, self.sql = inserted, ""

    def execute(self, sql, params):
        self.sql = sql

    def fetchone(self):
        return (self.inserted,)


class _Conn:
    def __init__(self, inserted):
        self.cur = _Cur(inserted)

    def cursor(self):
        return self.cur


CAND = {"symbol": "ACHV", "origin_system": "hermes_research", "provenance_reason": "Hermes research: x",
        "detail": {"source": "hermes_research"}}


def test_an_already_listed_idea_is_refreshed_not_dropped():
    conn = _Conn(False)
    assert rwd._upsert(conn, CAND) == "refreshed"
    assert "DO UPDATE" in conn.cur.sql and "last_seen_at = NOW()" in conn.cur.sql
    assert "status" not in conn.cur.sql.split("DO UPDATE", 1)[1]


def test_a_new_idea_is_inserted():
    assert rwd._upsert(_Conn(True), CAND) == "inserted"


def test_health_is_ok_when_research_surfaced_names_even_if_all_were_listed():
    assert rwd.run_report(60, 0, 60) == (True, 60, None)
    assert rwd.run_report(0, 0, 0) == (False, 0, "0 research candidates")
