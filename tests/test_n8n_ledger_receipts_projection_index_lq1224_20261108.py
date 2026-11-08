"""LQ-20261107-1224 (index hunk of LQ-945 1974edbe0 / LQ-891): the gateway ``list`` query uses an index.

ANCHOR: N8N_LEDGER_RECEIPTS_PROJECTION_INDEX_LQ1224_20261108

``LedgerReceiptStore.iter_receipts`` filters project/lane_id/state and orders by updated_at. Without
``receipts_projection`` the plan is ``SCAN receipts`` plus a temp B-tree, which cost 22-29 s cold on the live
635 MB ledger (DONE-LQ-20261107-1217). Hermetic: a tmp_path ledger, no live store.
"""
from __future__ import annotations

import sqlite3

from scripts.lib.n8n_coordination_ledger import CoordinationLedger

LIST_SQL = ("EXPLAIN QUERY PLAN SELECT receipt_json FROM receipts WHERE 1=1 AND project = ? AND lane_id = ? "
            "AND state = ? ORDER BY updated_at DESC LIMIT ?")


def _plan(conn: sqlite3.Connection) -> str:
    return " | ".join(str(r[-1]) for r in conn.execute(LIST_SQL, ("p", "research-intake", "ACCEPTED", 200)))


def test_a_writable_open_creates_the_receipts_projection_index(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite3")
    cols = [r[2] for r in ledger._conn.execute("PRAGMA index_info(receipts_projection)")]
    assert cols == ["project", "lane_id", "state", "updated_at"]


def test_the_list_query_uses_the_index_and_never_scans_or_sorts(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite3")
    plan = _plan(ledger._conn)
    assert "USING INDEX receipts_projection" in plan, plan
    assert "SCAN receipts" not in plan and "TEMP B-TREE" not in plan, plan


def test_an_existing_ledger_gains_the_index_at_its_next_writable_open_and_a_reader_never_builds_it(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    CoordinationLedger(path)._conn.execute("DROP INDEX receipts_projection")  # a pre-LQ-891 store
    reader = CoordinationLedger(path, read_only=True)
    assert "receipts_projection" not in {r[0] for r in reader._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}, "a read-only open must never migrate"
    assert "SCAN receipts" in _plan(reader._conn)
    reader._conn.close()
    assert "USING INDEX receipts_projection" in _plan(CoordinationLedger(path)._conn)
