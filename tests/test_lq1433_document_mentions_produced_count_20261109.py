# ANCHOR: LQ1433_DOCUMENT_MENTIONS_PRODUCED_COUNT_20261109
"""LQ-20261107-1433 — produced_count must equal rows that actually landed.

The 2026-11-09 00:25 ET live slot reported produced_count=32 (news_articles written=30 +
hermes_external_research written=2) while document_mentions gained only 30 durable rows
(news_articles short by 2: AAOZ/388111 and ABOS/388156 re-landed at 01:25). Counting
cursor.rowcount after ON CONFLICT DO NOTHING over-counted; INSERT … RETURNING id does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import document_mentions as DM  # noqa: E402


class _Cur:
    """Scripted cursor: match substrings in SQL to canned results.

    For INSERT…RETURNING, ``result`` is the list of rows ``fetchall`` should return
    (empty = conflict no-op; non-empty = landed). ``rowcount`` may lie on purpose so the
    test proves we ignore it.
    """

    def __init__(self, script, connection=None):
        self.script = list(script)
        self.connection = connection
        self.sql: list[tuple] = []
        self.rowcount = -1
        self._rows: list = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        for match, result in self.script:
            if match in sql:
                self._rows = result(params) if callable(result) else list(result)
                return
        self._rows = []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True


def _row(symbol="AAOZ", role="subject"):
    return {
        "symbol": symbol,
        "subject_guid": None,
        "issuer_guid": None,
        "identity_status": "UNRESOLVED",
        "matched_via": "company_name",
        "matched_text": symbol,
        "role": role,
        "role_source": "deterministic",
        "role_confidence": None,
    }


def test_persist_counts_returning_rows_not_rowcount():
    """A lying rowcount must not inflate the write tally (the 00:25 defect shape)."""
    cur = _Cur([
        ("pg_indexes", [(1,)]),
        ("INSERT INTO document_mentions", []),  # conflict no-op: RETURNING empty
    ])
    cur.rowcount = 1  # the unreliable signal that over-counted live
    conn = _Conn(cur)
    n = DM.persist(conn, source_table="news_articles", source_id=388111, rows=[_row()])
    assert n == 0
    assert conn.committed
    inserts = [s for s, _ in cur.sql if "INSERT INTO document_mentions" in s]
    assert inserts and "RETURNING id" in inserts[0]


def test_persist_counts_each_landed_returning_id():
    cur = _Cur([
        ("pg_indexes", [(1,)]),
        ("INSERT INTO document_mentions", [(678015,)]),
    ])
    cur.rowcount = 0  # even a zero rowcount must not hide a landed RETURNING row
    conn = _Conn(cur)
    n = DM.persist(conn, source_table="news_articles", source_id=388111, rows=[_row()])
    assert n == 1


def test_persist_mixed_land_and_conflict_matches_returning_only():
    """Two offered rows, one lands and one conflicts → written=1 (offered still 2 upstream)."""
    landed = {"first": True}

    def on_insert(params):
        # first call lands, second is a no-op
        if landed["first"]:
            landed["first"] = False
            return [(1,)]
        return []

    cur = _Cur([
        ("pg_indexes", [(1,)]),
        ("INSERT INTO document_mentions", on_insert),
    ])
    conn = _Conn(cur)
    n = DM.persist(
        conn,
        source_table="news_articles",
        source_id=388144,
        rows=[_row("PATK", "subject"), _row("CART", "mentioned")],
    )
    assert n == 1


def test_lane_output_produced_equals_written_not_offered():
    from backfill_document_mentions import lane_output

    out = lane_output({"written": 30, "offered": 32, "no_mention": 0, "undecided": 0})
    assert out["produced_count"] == 30
    assert out["attempted_count"] == 32
    assert out["skipped_reasons"]["already_written"] == 2
