"""v1.2 P1/P15 — REAL-DATABASE migration + integration tests on an EPHEMERAL
PostgreSQL database (created and dropped per run). Proves a clean database
installs from the repository alone — no workstation DDL. Skips (loudly) when
no local postgres superuser access is available (CI without PG)."""
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture()
def ephemeral_db():
    """Ephemeral SCHEMA (clean slate) in the configured database — CREATEDB is
    not granted here, and a fresh schema with search_path pinned is an equally
    honest clean-install surface: every unqualified CREATE lands in it, and it
    is dropped CASCADE afterward. trade_instances is built from the same DDL
    contract as migrate_trade_instances.py (mirror kept minimal + asserted)."""
    try:
        conn = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                user=os.environ.get("DB_USER", os.environ.get("PGUSER", "postgres")),
                                password=os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", "")),
                                host=os.environ.get("DB_HOST", "localhost"),
                                port=os.environ.get("DB_PORT", "5432"))
    except Exception as e:
        pytest.skip(f"no postgres access: {e}")
    schema = f"olc_mig_{uuid.uuid4().hex[:8]}"
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
    conn.commit()
    yield conn
    conn.rollback()
    cur = conn.cursor()
    cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _build_all(conn):
    cur = conn.cursor()
    from options_lifecycle_model import ensure_tables
    from options_lifecycle_alerts import ensure_alert_tables
    from options_lifecycle_tickets import ensure_ticket_tables
    from options_lifecycle_basis import ensure_basis_tables
    from options_journal_bridge import ensure_bridge_tables
    from options_lifecycle_oversight import ensure_oversight_tables
    from options_fill_evidence import ensure_evidence_tables
    ensure_tables(cur, conn)
    ensure_alert_tables(cur, conn)
    ensure_ticket_tables(cur, conn)
    ensure_basis_tables(cur, conn)
    ensure_oversight_tables(cur, conn)
    ensure_bridge_tables(cur, conn)   # view needs decisions/outcomes: after model
    ensure_evidence_tables(cur, conn)
    return cur


def test_clean_database_installs_from_repo_alone(ephemeral_db):
    cur = _build_all(ephemeral_db)
    from options_lifecycle_model import verify_schema
    problems = verify_schema(cur)
    assert problems == [], f"clean DB missing columns: {problems}"
    # unique partial index exists and is enforced at the DATABASE
    cur.execute("""SELECT indexname FROM pg_indexes
                   WHERE tablename='options_lifecycle_tickets'
                     AND indexname='uq_active_ticket_per_idem_key'""")
    assert cur.fetchone(), "active-ticket unique partial index missing"


def test_migration_rerun_is_idempotent(ephemeral_db):
    _build_all(ephemeral_db)
    _build_all(ephemeral_db)   # rerun must not raise


def test_db_enforced_single_active_ticket(ephemeral_db):
    cur = _build_all(ephemeral_db)
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
        VALUES (%s,'close','{}','h1','DAY','samekey')""", (spid,))
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("""INSERT INTO options_lifecycle_tickets
            (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
            VALUES (%s,'close','{}','h2','DAY','samekey')""", (spid,))
    ephemeral_db.rollback()
    # but a terminal ticket frees the key
    cur = ephemeral_db.cursor()
    cur.execute("UPDATE options_lifecycle_tickets SET status='cancelled' WHERE idempotency_key='samekey'")
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
        VALUES (%s,'close','{}','h3','DAY','samekey')""", (spid,))


def test_cumulative_two_batch_close_and_outcome(ephemeral_db):
    """Two-batch partial close: cumulative P&L + fees, FILLED only at the end,
    outcome row carries every batch. Runs against REAL SQL."""
    conn = ephemeral_db
    cur = _build_all(conn)
    import json as _j
    from options_fill_evidence import record_broker_evidence
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    cur.execute("UPDATE options_strategy_positions SET roll_root_id=%s WHERE strategy_position_id=%s",
                (spid, spid))
    cur.execute("""INSERT INTO options_strategy_legs
        (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
         contracts, multiplier, strike, expiration, opening_price)
        VALUES (%s,'TEST  260821C00110000','short_call','call','STO','short',
                2,100,110,'2026-08-21',2.00)""", (spid,))
    ticket = {"kind": "close", "strategy_position_id": spid, "underlying": "TEST",
              "strategy_type": "covered_call", "broker": "schwab", "account_key": "acct",
              "legs": [{"occ_symbol": "TEST  260821C00110000", "instruction": "BTC",
                        "contracts": 2.0, "proposed_limit": 1.0}],
              "net_debit_credit": -200.0, "net_label": "pay", "tif": "DAY",
              "quote_ts": "2026-07-19T00:00:00+00:00", "quote_max_age_seconds": 90}
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, status, idempotency_key)
        VALUES (%s,'close',%s,'h','DAY','armed','k1') RETURNING ticket_id""",
        (spid, _j.dumps(ticket)))
    tid = cur.fetchone()[0]
    conn.commit()
    r1 = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 1,
         "price": 1.00, "commission": 0.65, "broker_order_id": "o1", "broker_execution_id": "e1"}],
        source="schwab")
    assert r1["ok"] and r1["ticket_complete"] is False and r1["position_closed"] is False
    # duplicate replay of batch 1 changes NOTHING
    r1b = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 1,
         "price": 1.00, "commission": 0.65, "broker_order_id": "o1", "broker_execution_id": "e1"}],
        source="schwab")
    assert r1b["ok"] and r1b["inserted"] == 0 and r1b["ticket_complete"] is False
    r2 = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 1,
         "price": 0.90, "commission": 0.65, "broker_order_id": "o2", "broker_execution_id": "e2"}],
        source="schwab")
    assert r2["ok"] and r2["ticket_complete"] is True and r2["position_closed"] is True
    # cumulative: (2.00-1.00)*100 + (2.00-0.90)*100 = 210 gross; fees 1.30 → 208.70 net
    assert abs(r2["realized_cumulative"] - 210.0) < 0.01
    cur.execute("SELECT realized_pnl FROM options_lifecycle_outcomes WHERE strategy_position_id=%s", (spid,))
    assert abs(float(cur.fetchone()[0]) - 208.70) < 0.01
    cur.execute("SELECT status FROM options_lifecycle_tickets WHERE ticket_id=%s", (tid,))
    assert cur.fetchone()[0] == "filled"
    # journal projection landed via the durable outbox
    cur.execute("""SELECT status, pnl FROM trade_instances
                   WHERE source_table='options_strategy_positions' AND source_trade_id=%s""", (str(spid),))
    inst = cur.fetchone()
    assert inst and inst[0] == "closed" and abs(float(inst[1]) - 208.70) < 0.01


def test_overfill_fails_closed(ephemeral_db):
    conn = ephemeral_db
    cur = _build_all(conn)
    import json as _j
    from options_fill_evidence import record_broker_evidence
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    cur.execute("""INSERT INTO options_strategy_legs
        (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
         contracts, multiplier, strike, expiration, opening_price)
        VALUES (%s,'TEST  260821C00110000','short_call','call','STO','short',
                1,100,110,'2026-08-21',2.00)""", (spid,))
    ticket = {"kind": "close", "strategy_position_id": spid, "underlying": "TEST",
              "strategy_type": "covered_call", "broker": "schwab", "account_key": "acct",
              "legs": [{"occ_symbol": "TEST  260821C00110000", "instruction": "BTC",
                        "contracts": 1.0, "proposed_limit": 1.0}],
              "net_debit_credit": -100.0, "net_label": "pay", "tif": "DAY",
              "quote_ts": "t", "quote_max_age_seconds": 90}
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, status, idempotency_key)
        VALUES (%s,'close',%s,'h','DAY','armed','k2') RETURNING ticket_id""", (spid, _j.dumps(ticket)))
    tid = cur.fetchone()[0]
    conn.commit()
    r = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 2, "price": 1.0}],
        source="schwab")
    assert r["ok"] is False and "OVERFILL" in r["error"]
    rf = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 0.5, "price": 1.0}],
        source="schwab")
    assert rf["ok"] is False and "fractional" in rf["error"]
