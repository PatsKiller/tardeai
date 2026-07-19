"""v1.2.3 P1-1 — REAL process-boundary outbox crash tests (subprocess, not
threads). A worker COMMITS its claim, emits a marker, then is SIGKILLed before
projecting; a second independent worker process recovers after the lease and
projects exactly once. Runs in CI (PostgreSQL service)."""
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

psycopg2 = pytest.importorskip("psycopg2")

DB = dict(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
          user=os.environ.get("DB_USER", os.environ.get("PGUSER", "postgres")),
          password=os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", "")),
          host=os.environ.get("DB_HOST", "localhost"),
          port=os.environ.get("DB_PORT", "5432"))

CLAIM_WORKER = r'''
import os, sys, time, psycopg2
schema = sys.argv[1]
mode = sys.argv[2]          # claim_commit | die_before_commit | project_then_die
conn = psycopg2.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                        password=os.environ["DB_PASSWORD"], host=os.environ["DB_HOST"],
                        port=os.environ["DB_PORT"])
cur = conn.cursor()
cur.execute(f'SET search_path TO "{schema}"')
cur.execute("""SELECT outbox_id, strategy_position_id FROM journal_projection_outbox
               WHERE state IN ('NEW','RETRY') ORDER BY outbox_id LIMIT 1
               FOR UPDATE SKIP LOCKED""")
row = cur.fetchone()
oid, spid = row
cur.execute("""UPDATE journal_projection_outbox SET state='PROCESSING', claimed_at=now(),
               attempts=attempts+1 WHERE outbox_id=%s""", (oid,))
if mode == "die_before_commit":
    print(f"MARKER claimed_uncommitted {oid} {os.getpid()}", flush=True)
    time.sleep(60)          # parent kills us; uncommitted claim vanishes
conn.commit()
if mode == "project_then_die":
    sys.path.insert(0, os.environ["REPO_SCRIPTS"])
    from options_journal_bridge import upsert_trade_instance
    upsert_trade_instance(cur, conn, spid)   # projection written+committed
    print(f"MARKER projected_no_final {oid} {os.getpid()}", flush=True)
    time.sleep(60)          # killed before outbox final-state update
print(f"MARKER claim_committed {oid} {os.getpid()}", flush=True)
time.sleep(60)              # parent kills us here (after committed claim)
'''

RECOVERY_WORKER = r'''
import os, sys, psycopg2, json
schema = sys.argv[1]
conn = psycopg2.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                        password=os.environ["DB_PASSWORD"], host=os.environ["DB_HOST"],
                        port=os.environ["DB_PORT"])
cur = conn.cursor()
cur.execute(f'SET search_path TO "{schema}"')
sys.path.insert(0, os.environ["REPO_SCRIPTS"])
from options_fill_evidence import process_projection_outbox
print(json.dumps(process_projection_outbox(cur, conn)), flush=True)
'''


@pytest.fixture()
def crash_env(tmp_path):
    conn = psycopg2.connect(**DB)
    schema = f"crash_{uuid.uuid4().hex[:8]}"
    cur = conn.cursor()
    cur.execute(f'CREATE SCHEMA "{schema}"')
    cur.execute(f'SET search_path TO "{schema}"')
    cur.execute("""CREATE TABLE trade_instances (
        id BIGSERIAL PRIMARY KEY, trade_uid TEXT UNIQUE NOT NULL,
        source_system TEXT, source_table TEXT, source_trade_id TEXT,
        execution_broker TEXT, execution_account TEXT, execution_environment TEXT,
        trade_mode TEXT, symbol TEXT, strategy_id TEXT, status TEXT, side TEXT,
        shares NUMERIC, entry_price NUMERIC, entry_time TIMESTAMPTZ,
        exit_price NUMERIC, exit_time TIMESTAMPTZ, pnl NUMERIC,
        lineage_confidence TEXT, lineage_source TEXT, lineage_notes JSONB,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (source_table, source_trade_id))""")
    from options_lifecycle_model import ensure_tables
    from options_lifecycle_tickets import ensure_ticket_tables
    from options_journal_bridge import ensure_bridge_tables
    from options_lifecycle_basis import ensure_basis_tables
    from options_fill_evidence import ensure_evidence_tables, _queue_projection
    ensure_tables(cur, conn)
    ensure_ticket_tables(cur, conn)   # options_lifecycle_outcomes lives here (view dep)
    ensure_basis_tables(cur, conn)
    ensure_bridge_tables(cur, conn)
    ensure_evidence_tables(cur, conn)
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    conn.commit()
    _queue_projection(cur, spid)
    conn.commit()
    claim = tmp_path / "claim_worker.py"
    claim.write_text(CLAIM_WORKER)
    recover = tmp_path / "recovery_worker.py"
    recover.write_text(RECOVERY_WORKER)
    env = {**os.environ, "DB_NAME": DB["dbname"], "DB_USER": DB["user"],
           "DB_PASSWORD": DB["password"], "DB_HOST": DB["host"], "DB_PORT": str(DB["port"]),
           "REPO_SCRIPTS": str(ROOT / "scripts")}
    yield conn, cur, schema, spid, str(claim), str(recover), env
    conn.rollback()
    conn.cursor().execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _spawn_until_marker(script, schema, mode, env, marker):
    p = subprocess.Popen([sys.executable, script, schema, mode], env=env,
                         stdout=subprocess.PIPE, text=True)
    line = ""
    deadline = time.time() + 30
    while time.time() < deadline:
        line = p.stdout.readline()
        if marker in line:
            return p, line
    p.kill()
    raise AssertionError(f"worker never emitted {marker}: {line!r}")


def _expire_lease(cur, conn):
    cur.execute("""UPDATE journal_projection_outbox
                   SET claimed_at = now() - interval '11 minutes' WHERE state='PROCESSING'""")
    conn.commit()


def test_committed_claim_then_sigkill_then_recovery(crash_env):
    conn, cur, schema, spid, claim, recover, env = crash_env
    p, line = _spawn_until_marker(claim, schema, "claim_commit", env, "claim_committed")
    pid = int(line.split()[-1])
    os.kill(p.pid, signal.SIGKILL)          # abrupt death AFTER committed claim
    p.wait()
    cur.execute("SELECT state, attempts FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    state, attempts = cur.fetchone()
    assert state == "PROCESSING" and attempts == 1     # committed claim survives the death
    _expire_lease(cur, conn)
    r = subprocess.run([sys.executable, recover, schema], env=env, capture_output=True, text=True)
    assert '"projected": 1' in r.stdout, r.stdout + r.stderr
    cur.execute("SELECT state, attempts FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    state, attempts = cur.fetchone()
    assert state == "PROJECTED" and attempts == 2       # crash + recovery visible in attempts
    cur.execute("SELECT count(*) FROM trade_instances WHERE source_trade_id=%s", (str(spid),))
    assert cur.fetchone()[0] == 1                        # exactly one projection
    assert pid != os.getpid()


def test_death_before_claim_commit_leaves_new(crash_env):
    conn, cur, schema, spid, claim, recover, env = crash_env
    p, _ = _spawn_until_marker(claim, schema, "die_before_commit", env, "claimed_uncommitted")
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    time.sleep(0.5)
    cur.execute("SELECT state FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "NEW"                    # uncommitted claim vanished with the process


def test_death_after_projection_before_final_state(crash_env):
    conn, cur, schema, spid, claim, recover, env = crash_env
    p, _ = _spawn_until_marker(claim, schema, "project_then_die", env, "projected_no_final")
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    cur.execute("SELECT count(*) FROM trade_instances WHERE source_trade_id=%s", (str(spid),))
    assert cur.fetchone()[0] == 1                        # projection landed, outbox still PROCESSING
    _expire_lease(cur, conn)
    r = subprocess.run([sys.executable, recover, schema], env=env, capture_output=True, text=True)
    cur.execute("SELECT state FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] in ("PROJECTED", "RECONCILED")
    cur.execute("SELECT count(*) FROM trade_instances WHERE source_trade_id=%s", (str(spid),))
    assert cur.fetchone()[0] == 1                        # NO duplicate journal record


def test_two_recovery_workers_project_once(crash_env):
    conn, cur, schema, spid, claim, recover, env = crash_env
    p, _ = _spawn_until_marker(claim, schema, "claim_commit", env, "claim_committed")
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    _expire_lease(cur, conn)
    p1 = subprocess.Popen([sys.executable, recover, schema], env=env, stdout=subprocess.PIPE, text=True)
    p2 = subprocess.Popen([sys.executable, recover, schema], env=env, stdout=subprocess.PIPE, text=True)
    o1, _ = p1.communicate(timeout=60)
    o2, _ = p2.communicate(timeout=60)
    import json as _j
    total = sum(_j.loads(x.strip().splitlines()[-1])["projected"] for x in (o1, o2))
    assert total == 1                                    # simultaneous workers: exactly once
    cur.execute("SELECT count(*) FROM trade_instances WHERE source_trade_id=%s", (str(spid),))
    assert cur.fetchone()[0] == 1
