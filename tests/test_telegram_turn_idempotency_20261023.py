"""Conversation replay and concurrency on a private PostgreSQL fixture.

No host env, passwords, TCP listener, provider or production database is used.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from scripts.lib.inbound_identity_tagger import persist_turn

ROOT = Path(__file__).resolve().parents[1]
BIN = next((p for n in (18, 17, 16, 15) if (p := Path(f"/usr/lib/postgresql/{n}/bin") / "initdb").is_file()), None)
pytestmark = pytest.mark.skipif(BIN is None, reason="private PostgreSQL fixture binaries unavailable")
GUID = "11111111-2222-4333-8444-555555555555"
GUID2 = "11111111-2222-4333-8444-666666666666"


@pytest.fixture(scope="module")
def private_pg(tmp_path_factory):
    pg = pytest.importorskip("psycopg2")
    base = tmp_path_factory.mktemp("turn-idempotency-pg")
    data = base / "data"
    # Unix socket paths have a 108-byte ceiling; pytest full paths exceed it.
    socket_base = ROOT.parent / ".cache/rtc"
    socket_base.mkdir(parents=True, exist_ok=True)
    sock = Path(tempfile.mkdtemp(prefix="t29s-", dir=socket_base))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env["LC_ALL"] = "C"
    subprocess.run(
        [str(BIN), "-D", str(data), "-U", "turn_fixture", "--auth=trust", "-E", "UTF8"],
        check=True,
        capture_output=True,
        env=env,
    )
    ctl = BIN.parent / "pg_ctl"
    subprocess.run(
        [
            str(ctl),
            "-D",
            str(data),
            "-o",
            f"-c listen_addresses='' -c unix_socket_directories={sock} -p 55439",
            "-l",
            str(base / "postgres.log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
        env=env,
    )

    def connect():
        return pg.connect(host=str(sock), port=55439, dbname="postgres", user="turn_fixture")

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                sql = (ROOT / "sql/operator_conversation_turns.sql").read_text().split("CREATE INDEX", 1)[0]
                cur.execute(sql)
                cur.execute(
                    "ALTER TABLE operator_conversation_turns ALTER COLUMN occurred_at SET DEFAULT TIMESTAMPTZ '2026-10-23 20:00:00+00'"
                )
        yield connect
    finally:
        subprocess.run(
            [str(ctl), "-D", str(data), "-m", "fast", "-w", "stop"], check=True, capture_output=True, env=env
        )
        # Keep this owned fixture tree and server log as evidence; no archive or host data is removed.


def write(connect, mid, *, chat="fixture-chat", text="fixture page", role="agent", guids=(GUID,)):
    tag = {"resolved": [{"symbol": "FIX", "subject_guid": g} for g in guids]}
    conn = connect()
    try:
        return persist_turn(tag, conn=conn, text=text, role=role, chat_id=chat, message_id=mid)
    finally:
        conn.close()


def count(connect, mid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM operator_conversation_turns WHERE message_id=%s", (mid,))
        return cur.fetchone()[0]


def test_exact_replay_returns_zero_and_keeps_original_row(private_pg):
    assert write(private_pg, 100) == 1
    with private_pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM operator_conversation_turns WHERE message_id=100")
        before = cur.fetchall()
    assert write(private_pg, 100) == 0
    with private_pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM operator_conversation_turns WHERE message_id=100")
        assert cur.fetchall() == before


def test_concurrent_intake_and_reply_capture_only_insert_once(private_pg):
    barrier = Barrier(5)

    def run(_):
        barrier.wait(timeout=10)
        return write(private_pg, 101)

    with ThreadPoolExecutor(max_workers=5) as workers:
        assert sorted(workers.map(run, range(5))) == [0, 0, 0, 0, 1]
    assert count(private_pg, 101) == 1


def test_role_chat_edit_and_security_remain_distinct(private_pg):
    assert write(private_pg, 102) == 1
    assert write(private_pg, 102, chat="other-fixture-chat") == 1
    assert write(private_pg, 102, role="operator") == 1
    assert write(private_pg, 102, text="corrected page") == 1
    assert write(private_pg, 102, guids=(GUID2,)) == 1
    assert count(private_pg, 102) == 5


def test_duplicate_entity_in_one_page_and_unresolved_replay(private_pg):
    assert write(private_pg, 103, guids=(GUID, GUID, GUID2)) == 2
    assert write(private_pg, 103, guids=(GUID, GUID2)) == 0
    assert write(private_pg, 104, guids=()) == 1
    assert write(private_pg, 104, guids=()) == 0
    assert count(private_pg, 104) == 1


def test_missing_coordinates_do_not_collapse_unrelated_turns(private_pg):
    assert write(private_pg, 105, chat=None) == 1
    assert write(private_pg, 105, chat=None) == 1
    assert count(private_pg, 105) == 2


def test_existing_identical_history_is_preserved(private_pg):
    with private_pg() as conn, conn.cursor() as cur:
        for _ in range(2):
            cur.execute(
                "INSERT INTO operator_conversation_turns(role,channel,chat_id,message_id,text,symbol,subject_guid) VALUES('agent','telegram','fixture-chat',106,'fixture page','FIX',%s)",
                (GUID,),
            )
    assert write(private_pg, 106) == 0
    assert count(private_pg, 106) == 2


def test_unsupported_transaction_modes_refuse_before_inserting(private_pg):
    conn = private_pg()
    try:
        conn.autocommit = True
        with pytest.raises(ValueError, match="requires a transaction"):
            persist_turn(
                {"resolved": []}, conn=conn, text="fixture", role="agent", chat_id="fixture-chat", message_id=107
            )
        conn.autocommit = False
        conn.set_session(isolation_level="REPEATABLE READ")
        with pytest.raises(ValueError, match="requires READ COMMITTED"):
            persist_turn(
                {"resolved": []}, conn=conn, text="fixture", role="agent", chat_id="fixture-chat", message_id=107
            )
        conn.rollback()
        assert count(private_pg, 107) == 0
    finally:
        conn.close()


def test_operator_census_is_readonly_and_only_returns_aggregates(private_pg):
    sql = (ROOT / "docs/ops/packets/telegram-turn-dedupe-20261023/read-only-census.sql").read_text()
    sql = sql.replace("CURRENT_TIMESTAMP", "TIMESTAMPTZ '2026-10-24 03:00:00+00'")
    conn = private_pg()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for statement in sql.split(";"):
                if not statement.strip():
                    continue
                cur.execute(statement)
                if cur.description:
                    assert [c.name for c in cur.description] == [
                        "role",
                        "channel",
                        "duplicate_groups",
                        "excess_identical_rows",
                        "largest_group",
                    ]
                    rows = cur.fetchall()
                    assert rows and rows[0][2] >= 1
    finally:
        conn.close()
