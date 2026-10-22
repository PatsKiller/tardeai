"""Release train arming finding 12 (ANCHOR RELEASE_QUEUE_MIGRATION_GRANTS_20261021): the queue migration grants the
controller role ``trade_ai`` SELECT/INSERT on ``release_queue_events`` (+ USAGE on its sequence, which INSERT needs)
and SELECT/INSERT/UPDATE on ``release_queue`` (the projection upsert), and nothing else; the down migration withdraws
the write grants from the archived tables.

The cluster test runs the real files on a THROWAWAY PostgreSQL cluster: its own ``initdb`` data dir under $TMPDIR,
``listen_addresses=''`` (unix socket in that temp dir only, no TCP), stopped afterwards. It never connects to the
production server. A role named ``trade_ai`` exists only inside that temp cluster. Skipped where no PG server binaries
exist (the static checks still run). psycopg2 is not used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "migrations/2026_10_21_release_queue.sql"
DOWN = ROOT / "migrations/2026_10_21_release_queue.down.sql"


def _code(path: Path) -> str:
    return "\n".join(line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())


def test_up_grants_exactly_the_controller_rights():
    sql = _code(UP)
    grants = [" ".join(g.split()) for g in re.findall(r"GRANT[^;]+;", sql, re.I)]
    assert grants == [
        "GRANT SELECT, INSERT ON release_queue_events TO trade_ai;",
        "GRANT USAGE ON SEQUENCE release_queue_events_seq_seq TO trade_ai;",
        "GRANT SELECT, INSERT, UPDATE ON release_queue TO trade_ai;",
    ]
    assert "REVOKE ALL ON release_queue_events, release_queue FROM PUBLIC" in " ".join(sql.split())
    assert not re.search(r"\b(DROP|DELETE\s+FROM|TRUNCATE\s+\w|ALTER\s+TABLE)\b", sql, re.I)


def test_down_archives_and_withdraws_writes_never_drops():
    sql = _code(DOWN)
    assert (
        "RENAME TO release_queue_archived_20261021" in sql and "RENAME TO release_queue_events_archived_20261021" in sql
    )
    assert "REVOKE INSERT, UPDATE ON release_queue_archived_20261021 FROM trade_ai" in sql
    assert "REVOKE INSERT ON release_queue_events_archived_20261021 FROM trade_ai" in sql
    assert not re.search(r"\bDROP\b", sql, re.I) and "GRANT " not in sql


def _bin() -> Path | None:
    for major in ("17", "18", "16", "15"):
        d = Path(f"/usr/lib/postgresql/{major}/bin")
        if (d / "initdb").is_file() and (d / "pg_ctl").is_file():
            return d
    found = shutil.which("initdb")
    return Path(found).parent if found else None


BIN = _bin()
PSQL = shutil.which("psql") or (str(BIN / "psql") if BIN and (BIN / "psql").is_file() else None)


@pytest.fixture(scope="module")
def cluster():
    base = Path(tempfile.mkdtemp(prefix="rtq-pg-", dir=os.environ.get("TMPDIR") or None))
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    env = {**os.environ, "LC_ALL": "C"}
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD", "PGSERVICE", "PGPASSFILE"):
        env.pop(k, None)
    subprocess.run(
        [str(BIN / "initdb"), "-D", str(data), "-U", "rtq_admin", "--auth=trust", "-E", "UTF8"],
        check=True,
        capture_output=True,
        env=env,
    )
    opts = f"-c listen_addresses='' -c unix_socket_directories={sock} -p 55432 -c fsync=off"
    subprocess.run(
        [str(BIN / "pg_ctl"), "-D", str(data), "-o", opts, "-l", str(base / "log"), "-w", "start"],
        check=True,
        capture_output=True,
        env=env,
    )

    def psql(user, db, sql=None, file=None):
        argv = [PSQL, "-X", "-h", str(sock), "-p", "55432", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-tA"]
        argv += ["-f", str(file)] if file else ["-c", sql]
        p = subprocess.run(argv, capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    try:
        assert psql("rtq_admin", "postgres", "CREATE ROLE trade_ai LOGIN")[0] == 0
        assert psql("rtq_admin", "postgres", "CREATE DATABASE rtq_scratch")[0] == 0
        assert psql("rtq_admin", "rtq_scratch", "GRANT USAGE, CREATE ON SCHEMA public TO trade_ai")[0] == 0
        yield psql
    finally:
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], capture_output=True, env=env)
        shutil.rmtree(base, ignore_errors=True)  # the throwaway cluster's own temp tree only


EVENT = (
    "INSERT INTO release_queue_events (event_id, event_type, subject_kind, subject_id, pr_number, actor, "
    "occurred_at) VALUES ('{eid}', 'submitted', 'pr', 'pr:7', 7, 'test', now()) RETURNING seq"
)
UPSERT = (
    "INSERT INTO release_queue (pr_number, repo, state, updated_at, last_event_seq) VALUES "
    "(7, 'PatsKiller/tardeai', 'submitted', now(), {seq}) ON CONFLICT (pr_number) DO UPDATE SET "
    "state = EXCLUDED.state, updated_at = EXCLUDED.updated_at, last_event_seq = EXCLUDED.last_event_seq"
)


@pytest.mark.skipif(BIN is None or PSQL is None, reason="no PostgreSQL server binaries on this host")
def test_migration_on_a_throwaway_cluster(cluster):
    psql = cluster
    rc, out = psql("rtq_admin", "rtq_scratch", file=UP)  # an admin role applies it
    assert rc == 0, out
    assert psql("rtq_admin", "rtq_scratch", file=UP)[0] == 0  # idempotent
    rc, out = psql(
        "rtq_admin",
        "rtq_scratch",
        "SELECT table_name || ':' || string_agg(privilege_type, ',' ORDER BY privilege_type) "
        "FROM information_schema.role_table_grants WHERE grantee = 'trade_ai' GROUP BY table_name "
        "ORDER BY table_name",
    )
    assert out.splitlines() == ["release_queue:INSERT,SELECT,UPDATE", "release_queue_events:INSERT,SELECT"], out
    rc, out = psql(
        "rtq_admin",
        "rtq_scratch",
        "SELECT count(*) FROM information_schema.role_table_grants "
        "WHERE grantee = 'PUBLIC' AND table_name LIKE 'release_queue%'",
    )
    assert out == "0"
    # the controller role: append + upsert work
    rc, seq = psql("trade_ai", "rtq_scratch", EVENT.format(eid="e1"))
    assert rc == 0, seq
    seq = seq.splitlines()[0]
    assert psql("trade_ai", "rtq_scratch", UPSERT.format(seq=seq))[0] == 0
    assert psql("trade_ai", "rtq_scratch", UPSERT.format(seq=seq))[0] == 0  # upsert path
    assert psql("trade_ai", "rtq_scratch", "SELECT state FROM release_queue WHERE pr_number = 7")[1] == "submitted"
    # ... and nothing else
    for sql in (
        "DELETE FROM release_queue_events",
        "UPDATE release_queue_events SET actor = 'x'",
        "TRUNCATE release_queue_events",
        "DELETE FROM release_queue",
        "TRUNCATE release_queue",
        "ALTER TABLE release_queue ADD COLUMN x int",
        "DROP TABLE release_queue",
    ):
        rc, out = psql("trade_ai", "rtq_scratch", sql)
        assert rc != 0 and ("permission denied" in out or "must be owner" in out), (sql, out)
    # the owner is still bound by the append-only trigger
    rc, out = psql("rtq_admin", "rtq_scratch", "DELETE FROM release_queue_events")
    assert rc != 0 and "append-only" in out
    # down: archived, never dropped; writes withdrawn, reads kept; idempotent
    assert psql("rtq_admin", "rtq_scratch", file=DOWN)[0] == 0
    assert psql("rtq_admin", "rtq_scratch", file=DOWN)[0] == 0
    assert psql("trade_ai", "rtq_scratch", "SELECT count(*) FROM release_queue_events_archived_20261021")[1] == "1"
    rc, out = psql(
        "trade_ai",
        "rtq_scratch",
        "INSERT INTO release_queue_events_archived_20261021 (event_id, event_type, subject_kind, "
        "subject_id, pr_number, actor, occurred_at) VALUES ('e2','submitted','pr','pr:7',7,'t',now())",
    )
    assert rc != 0 and "permission denied" in out
    rc, out = psql("trade_ai", "rtq_scratch", "UPDATE release_queue_archived_20261021 SET state = 'held'")
    assert rc != 0 and "permission denied" in out
    assert psql("rtq_admin", "rtq_scratch", "SELECT to_regclass('release_queue_events')")[1] == ""


@pytest.mark.skipif(BIN is None or PSQL is None, reason="no PostgreSQL server binaries on this host")
def test_migration_applied_as_trade_ai_still_works(cluster):
    psql = cluster
    assert psql("rtq_admin", "postgres", "CREATE DATABASE rtq_owner")[0] == 0
    assert psql("rtq_admin", "rtq_owner", "GRANT USAGE, CREATE ON SCHEMA public TO trade_ai")[0] == 0
    rc, out = psql("trade_ai", "rtq_owner", file=UP)  # packet step A path (trade_ai owns)
    assert rc == 0, out
    rc, seq = psql("trade_ai", "rtq_owner", EVENT.format(eid="o1"))
    assert rc == 0
    rc, out = psql("trade_ai", "rtq_owner", "DELETE FROM release_queue_events")
    assert rc != 0 and "append-only" in out


def test_packet_finding_12_is_marked_fixed():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("12. **The migration owner.**") :]
    assert "**Status: FIXED**" in seg[:1600]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_queue_migration_grants_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_QUEUE_MIGRATION_GRANTS_20261021"
    assert "tests/test_release_queue_migration_grants_20261021.py" in doc["files"]
