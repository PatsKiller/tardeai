"""LQ-20261107-1696 — a lost DB connection must not kill the hourly document-mentions run.

ANCHOR: DOCUMENT_MENTIONS_CONN_LOSS_LQ1696_20261109

Measured on the live line 2026-11-09 (read-only, coordination ledger): the lane failed three
consecutive hourly slots — 08:25, 09:25 and 10:25 ET, ``RUN_FAILED exit 1``, each ~168 s, each
ending in the same traceback::

    File "scripts/lib/document_mentions.py", line 325, in _conflict_target
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s LIMIT 1", (_COALESCE_INDEX,))
    psycopg2.OperationalError: SSL connection has been closed unexpectedly

The backfill opens ONE psycopg2 connection for a scan of up to ``--limit 4000`` documents and never
recovers it, so a server-side drop (restart, idle proxy timeout) loses the whole batch. The failure
mode is the one ``lib/pg_reconnect.py`` was written for on 2026-10-09 (``topic_ingestion.py``, the
same message), and the lane simply was not using it.

Two consequences, both tested here:

A. the run must survive the drop — wrap the connection in ``ReconnectingConnection`` and end the
   read transaction after the row fetch, so ``_conflict_target``'s probe is the first statement of
   its transaction and the proxy can retry it once on a fresh connection;
B. if the connection cannot be recovered, the lane must exit **69 (EX_UNAVAILABLE)**, not 1. The
   lane's policy is ``transient-1-ingest`` (``config/n8n_retry_policies.json``), whose
   ``retryable_exit_codes`` are ``[69, 75, 111]`` and whose ``retryable_states`` include
   ``RUN_FAILED`` — so exit 69 earns the one retry after 120 s that exit 1 could never earn. 75 is
   NOT usable here: the executor maps exit 75 of a ``lock_kind: flock`` lane to
   ``RUN_SKIPPED_LOCK reason="flock_held"`` (scripts/n8n_run_executor.py, ``FLOCK_CONFLICT_EXIT``),
   which would record a DB drop as a lock collision. 69 is the code the 2026-11-07 disk-ledger lane
   already uses for the same "busy, retry me" meaning (LQ-20261107-1486).

No database and no network: the connection, its cursors and the reconnect are fakes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_document_mentions as BDM  # noqa: E402
from lib import document_mentions as DM  # noqa: E402
from lib import pg_reconnect  # noqa: E402
from lib import research_identity as RI  # noqa: E402

LOSS = "SSL connection has been closed unexpectedly"
DOC_ROWS = [(11, "AAA", "Apple and Morgan Stanley both appear in this article")]


class FakeCursor:
    """Records SQL and raises the production failure once, at the same statement it happened."""

    def __init__(self, conn: "FakeConn"):
        self._conn = conn
        self.connection = conn        # _conflict_target memoises on cursor.connection
        self.rowcount = 1

    def execute(self, sql, params=None):  # noqa: ARG002 — the fake ignores the values
        self._conn.queries.append(sql)
        if "pg_indexes" in sql and self._conn.lose_next_probe:
            self._conn.lose_next_probe = False
            raise psycopg2.OperationalError(LOSS)
        self.rowcount = 1

    def fetchall(self):
        last = self._conn.queries[-1] if self._conn.queries else ""
        if "INSERT INTO document_mentions" in last:      # persist() counts RETURNING id
            return [(1,)]
        if " FROM t" in last:
            return DOC_ROWS
        return []

    def fetchone(self):
        if self._conn.queries and "pg_indexes" in self._conn.queries[-1]:
            return (1,)                      # the coalesce index exists
        return DOC_ROWS[0]

    def close(self):
        pass


class FakeConn:
    """One psycopg2-shaped connection. ``lose_next_probe`` makes the next pg_indexes probe raise."""

    def __init__(self, lose_next_probe: bool = False):
        self.queries: list[str] = []
        self.lose_next_probe = lose_next_probe
        self.closed = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = 1


def _patch_extraction(monkeypatch):
    """The extractor is not what is under test: one decided mention per document."""
    from scripts.lib import document_mention_matcher as M

    monkeypatch.setattr(RI, "load_registry", lambda: {"entities": {}, "by_symbol": {}})
    monkeypatch.setattr(DM, "SOURCES", {"t": {"id": "id", "own_symbol": "symbol", "text": ["body"]}})
    monkeypatch.setattr(
        M, "match_mentions",
        lambda text, names=None, own_symbol=None: [  # noqa: ARG005 -- the fake ignores its three inputs and only has to answer
            {"symbol": "AAA", "subject_guid": "s-aaa", "issuer_guid": "i-aaa",
             "identity_status": "CONFIRMED", "role": "subject", "role_source": "test",
             "role_confidence": 0.9, "matched_via": "t", "matched_text": "AAA"}])


def test_the_run_survives_a_dropped_connection_by_reconnecting(monkeypatch):
    """The live failure, replayed: the pg_indexes probe loses the connection mid-batch."""
    _patch_extraction(monkeypatch)
    made: list[FakeConn] = []

    def factory():
        made.append(FakeConn(lose_next_probe=not made))   # only the FIRST connection drops
        return made[-1]

    monkeypatch.setattr(BDM, "_conn", factory)

    stat = BDM.run("t", 10, True, mark=10, deadline=None, seed=False,
                   names={"AAA": {}}, registry={})

    assert len(made) == 2, "the run did not open a second connection after the drop"
    assert stat["written"] == 1, f"the document was lost with the connection: {stat}"
    assert any("INSERT INTO document_mentions" in q for q in made[1].queries), (
        "the retried INSERT never reached the new connection"
    )


def test_without_the_reconnecting_wrapper_the_same_drop_kills_the_run(monkeypatch):
    """Negative control: the wrapper is what saves the run, not something else in the path.

    A plain connection (the code before this change) propagates the psycopg2 error out of ``run()``
    — which is exactly the traceback the ledger recorded three times this morning.
    """
    _patch_extraction(monkeypatch)
    made: list[FakeConn] = []

    def factory():
        made.append(FakeConn(lose_next_probe=not made))
        return made[-1]

    monkeypatch.setattr(BDM, "_conn", factory)
    monkeypatch.setattr(BDM, "ReconnectingConnection", lambda factory, **kw: factory(), raising=False)

    with pytest.raises(psycopg2.OperationalError, match="SSL connection has been closed"):
        BDM.run("t", 10, True, mark=10, deadline=None, seed=False,
                names={"AAA": {}}, registry={})


# ── B. the exit code the retry policy reads ─────────────────────────────────

class _Receipts:
    def __init__(self):
        self.calls: list[dict] = []

    def now_iso(self):
        return "2026-11-09T15:26:53+00:00"

    def write_lane_receipt(self, lane_id, **kwargs):  # noqa: ARG002 -- mirrors the real signature; the fake records kwargs
        self.calls.append(kwargs)
        return None


def test_a_lost_connection_exits_69_so_the_policy_retries_it(monkeypatch):
    receipts = _Receipts()
    monkeypatch.setattr(BDM, "_receipt_lib", lambda: receipts)

    def dropped(_a, _targets, _stats):
        raise psycopg2.OperationalError(LOSS)

    monkeypatch.setattr(BDM, "_run", dropped)

    assert BDM.main(["--all", "--apply"]) == 69
    assert receipts.calls[-1]["exit_code"] == 69
    assert receipts.calls[-1]["ok"] is False
    assert LOSS in (receipts.calls[-1].get("error") or ""), (
        "the receipt must name the cause, not just the exception type"
    )
    assert BDM.LOST_CONNECTION_EXIT == 69, "transient-1-ingest retries 69; the constant must say why"


def test_an_ordinary_error_is_still_exit_1(monkeypatch):
    """Only a lost connection earns the retryable code; a real bug must keep failing loudly."""
    receipts = _Receipts()
    monkeypatch.setattr(BDM, "_receipt_lib", lambda: receipts)

    def bug(_a, _targets, _stats):
        raise ValueError("a real bug")

    monkeypatch.setattr(BDM, "_run", bug)

    with pytest.raises(ValueError):
        BDM.main(["--all", "--apply"])
    assert receipts.calls[-1]["exit_code"] == 1


# ── the classifier itself ───────────────────────────────────────────────────

@pytest.mark.parametrize("exc,expected", [
    (psycopg2.OperationalError(LOSS), True),
    (psycopg2.InterfaceError("cursor already closed"), True),
    (psycopg2.OperationalError("syntax error at or near"), False),
    (ValueError(LOSS), False),                     # right message, wrong class
])
def test_is_connection_loss_classifies_the_way_the_wrapper_does(exc, expected):
    assert pg_reconnect.is_connection_loss(exc) is expected
