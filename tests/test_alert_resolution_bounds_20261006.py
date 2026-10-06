"""Bounded recovery cannot close unreviewed/new/acknowledged alert evidence."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import alert_event_writer as writer

OBSERVED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Connection:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.committed = self.rolled_back = self.closed = False
        self.calls = []

    def cursor(self):
        return self

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if self.failure == "execute":
            raise RuntimeError("fixture query failure")

    def fetchall(self):
        return [(5,), (3,)]

    def commit(self):
        if self.failure == "commit":
            raise RuntimeError("fixture commit failure")
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def resolve(ids, **kwargs):
    return writer.resolve_alert_event_ids(
        ids, source_script="stop_health", resolved_by="fixture recovery", observed_before_or_at=OBSERVED, **kwargs
    )


def test_update_is_bound_to_ids_source_active_state_and_older_evidence(monkeypatch):
    conn = Connection()
    monkeypatch.setattr(writer, "_get_conn", lambda: conn)
    assert resolve([5, 3, 5]) == [3, 5]
    assert conn.committed and conn.closed and not conn.rolled_back
    sql, params = conn.calls[0]
    assert "id = ANY(%s)" in sql
    assert "source_script = %s" in sql
    assert "lifecycle_state = 'active'" in sql
    assert "created_at < %s" in sql
    assert params == ("fixture recovery", [3, 5], "stop_health", OBSERVED)


@pytest.mark.parametrize("ids", [None, "all", [0], [-1], [True], ["3"], list(range(1, 202))])
def test_invalid_or_unbounded_ids_never_open_database(monkeypatch, ids):
    monkeypatch.setattr(writer, "_get_conn", lambda: pytest.fail("database reached"))
    with pytest.raises(ValueError):
        resolve(ids)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_script": ""},
        {"resolved_by": ""},
        {"observed_before_or_at": datetime(2026, 1, 1)},
        {"observed_before_or_at": datetime.now(timezone.utc) + timedelta(days=1)},
    ],
)
def test_missing_or_invalid_evidence_never_opens_database(monkeypatch, changes):
    monkeypatch.setattr(writer, "_get_conn", lambda: pytest.fail("database reached"))
    args = {"source_script": "stop_health", "resolved_by": "fixture", "observed_before_or_at": OBSERVED}
    args.update(changes)
    with pytest.raises(ValueError):
        writer.resolve_alert_event_ids([1], **args)


def test_empty_review_is_noop(monkeypatch):
    monkeypatch.setattr(writer, "_get_conn", lambda: pytest.fail("database reached"))
    assert resolve([]) == []


@pytest.mark.parametrize("failure", ["execute", "commit"])
def test_failure_rolls_back_and_never_claims_recovery(monkeypatch, failure):
    conn = Connection(failure=failure)
    monkeypatch.setattr(writer, "_get_conn", lambda: conn)
    with pytest.raises(RuntimeError, match="fixture"):
        resolve([1])
    assert conn.rolled_back and conn.closed and not conn.committed


def test_postgres_exclusions_and_idempotent_replay(monkeypatch):
    import os

    if os.environ.get("SIEM_PG_TEST") != "1":
        pytest.skip("opt-in isolated PostgreSQL recovery proof")
    import psycopg2
    from lib.m2_live_shadow_guard import (
        SHADOW_ADMIN_DSN,
        live_shadow_databases,
        shadow_test_database,
        with_database,
    )

    database = shadow_test_database()
    assert database not in live_shadow_databases()
    conn = psycopg2.connect(with_database(SHADOW_ADMIN_DSN, database), connect_timeout=3)

    class Borrowed:
        def cursor(self):
            return conn.cursor()

        def commit(self):
            conn.commit()

        def rollback(self):
            conn.rollback()

        def close(self):
            pass  # test retains the temp table only to inspect committed effects

    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TEMP TABLE alert_events (
                id bigint PRIMARY KEY, source_script text, lifecycle_state text,
                created_at timestamptz, resolved_at timestamptz, resolved_by text
            )""")
            old = OBSERVED - timedelta(minutes=1)
            new = OBSERVED + timedelta(minutes=1)
            cur.executemany(
                "INSERT INTO alert_events(id,source_script,lifecycle_state,created_at) VALUES(%s,%s,%s,%s)",
                [
                    (1, "stop_health", "active", old),
                    (2, "another_source", "active", old),
                    (3, "stop_health", "acknowledged", old),
                    (4, "stop_health", "active", new),
                    (5, "stop_health", "active", old),
                    (6, "stop_health", "active", OBSERVED),
                    (7, "stop_health", "resolved", old),
                ],
            )
        conn.commit()
        monkeypatch.setattr(writer, "_get_conn", Borrowed)
        assert resolve([1, 2, 3, 4, 6, 7]) == [1]
        assert resolve([1, 2, 3, 4, 6, 7]) == []
        with conn.cursor() as cur:
            cur.execute("SELECT id,lifecycle_state,resolved_by,resolved_at IS NOT NULL FROM alert_events ORDER BY id")
            rows = cur.fetchall()
        assert rows == [
            (1, "resolved", "fixture recovery", True),
            (2, "active", None, False),
            (3, "acknowledged", None, False),
            (4, "active", None, False),
            (5, "active", None, False),
            (6, "active", None, False),
            (7, "resolved", None, False),
        ]
    finally:
        conn.close()  # PostgreSQL discards only this connection's temporary table
