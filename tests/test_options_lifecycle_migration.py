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
    # v1.2.2 P1-3: PERSIST the original row, provoke the violation inside a
    # SAVEPOINT (original survives), then terminalize the SAME persisted row.
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
        VALUES (%s,'close','{}','h1','DAY','samekey') RETURNING ticket_id""", (spid,))
    original_tid = cur.fetchone()[0]
    ephemeral_db.commit()
    cur.execute("SAVEPOINT sp1")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("""INSERT INTO options_lifecycle_tickets
            (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
            VALUES (%s,'close','{}','h2','DAY','samekey')""", (spid,))
    cur.execute("ROLLBACK TO SAVEPOINT sp1")
    cur.execute("SELECT ticket_id, status FROM options_lifecycle_tickets WHERE idempotency_key='samekey'")
    rows = cur.fetchall()
    assert rows == [(original_tid, 'draft')]              # original persisted row intact
    cur.execute("UPDATE options_lifecycle_tickets SET status='cancelled' WHERE ticket_id=%s",
                (original_tid,))
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
        VALUES (%s,'close','{}','h3','DAY','samekey') RETURNING ticket_id""", (spid,))
    assert cur.fetchone()[0] != original_tid              # identical key reused after terminal


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
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 2, "price": 1.0,
         "broker_order_id": "o9", "broker_execution_id": "e9"}],
        source="schwab")
    assert r["ok"] is False and "OVERFILL" in r["error"]
    rf = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 0.5, "price": 1.0,
         "broker_order_id": "o9", "broker_execution_id": "e10"}],
        source="schwab")
    assert rf["ok"] is False and "fractional" in rf["error"]
    rid = record_broker_evidence(cur, conn, tid, [
        {"occ_symbol": "TEST  260821C00110000", "instruction": "BTC", "contracts": 1, "price": 1.0}],
        source="schwab")
    assert rid["ok"] is False and "broker_execution_id" in rid["error"]


def _mk_position(cur, conn, contracts=2.0, opening=2.00):
    import json as _j
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
                %s,100,110,'2026-08-21',%s)""", (spid, contracts, opening))
    ticket = {"kind": "close", "strategy_position_id": spid, "underlying": "TEST",
              "strategy_type": "covered_call", "broker": "schwab", "account_key": "acct",
              "legs": [{"occ_symbol": "TEST  260821C00110000", "instruction": "BTC",
                        "contracts": contracts, "proposed_limit": 1.0}],
              "net_debit_credit": -100.0 * contracts, "net_label": "pay", "tif": "DAY",
              "quote_ts": "t", "quote_max_age_seconds": 90}
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, status, idempotency_key)
        VALUES (%s,'close',%s,'h','DAY','armed',%s) RETURNING ticket_id""",
        (spid, _j.dumps(ticket), f"k-{spid}"))
    tid = cur.fetchone()[0]
    conn.commit()
    return spid, tid


def _fill(occ, n, px, oid, eid):
    return {"occ_symbol": occ, "instruction": "BTC", "contracts": n, "price": px,
            "broker_order_id": oid, "broker_execution_id": eid}


def test_three_batches_vwap_exact_db_rows(ephemeral_db):
    """P0-3: three batches at different prices — VWAP + realized exact,
    asserted from DATABASE ROWS, not returned dicts."""
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import record_broker_evidence
    spid, tid = _mk_position(cur, conn, contracts=3.0, opening=2.00)
    occ = "TEST  260821C00110000"
    record_broker_evidence(cur, conn, tid, [_fill(occ, 1, 1.20, "o1", "e1")], "schwab")
    record_broker_evidence(cur, conn, tid, [_fill(occ, 1, 1.00, "o2", "e2")], "schwab")
    r3 = record_broker_evidence(cur, conn, tid, [_fill(occ, 1, 0.80, "o3", "e3")], "schwab")
    assert r3["ticket_complete"] and r3["position_closed"]
    # VWAP = 1.00 → realized = (2.00-1.00)*3*100 = 300
    assert abs(r3["realized_cumulative"] - 300.0) < 0.01
    cur.execute("""SELECT status, contracts, closed_price FROM options_strategy_legs
                   WHERE strategy_position_id=%s""", (spid,))
    rows = cur.fetchall()
    closed_qty = sum(float(r[1]) for r in rows if r[0] == "closed")
    assert closed_qty == 3.0, rows                      # slices reconcile to exactly 3
    assert not [r for r in rows if r[0] == "open"]      # no open residual
    for st, n, cp in rows:
        if st == "closed":
            assert abs(float(cp) - 1.00) < 0.005        # cumulative VWAP on the row
    cur.execute("SELECT realized_pnl FROM options_lifecycle_outcomes WHERE strategy_position_id=%s", (spid,))
    assert abs(float(cur.fetchone()[0]) - 300.0) < 0.01
    cur.execute("SELECT status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "closed"


def test_partial_then_cancel_leaves_correct_residual(ephemeral_db):
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import record_broker_evidence
    from options_lifecycle_tickets import cancel_ticket
    spid, tid = _mk_position(cur, conn, contracts=2.0)
    occ = "TEST  260821C00110000"
    record_broker_evidence(cur, conn, tid, [_fill(occ, 1, 1.00, "o1", "e1")], "schwab")
    cur.execute("SELECT status FROM options_lifecycle_tickets WHERE ticket_id=%s", (tid,))
    assert cur.fetchone()[0] == "partial"
    # cancellation of the partial ticket: residual leg stays open at 1 contract
    cur.execute("UPDATE options_lifecycle_tickets SET status='cancelled' WHERE ticket_id=%s", (tid,))
    conn.commit()
    # v1.2.2 model: ONE leg row holds the residual; the closed contract lives
    # as an IMMUTABLE per-ticket allocation
    cur.execute("""SELECT status, contracts FROM options_strategy_legs
                   WHERE strategy_position_id=%s""", (spid,))
    rows = cur.fetchall()
    assert [(r[0], float(r[1])) for r in rows] == [("open", 1.0)]
    cur.execute("""SELECT ticket_id, contracts, vwap FROM options_close_allocations
                   WHERE strategy_position_id=%s""", (spid,))
    alloc = cur.fetchall()
    assert len(alloc) == 1 and float(alloc[0][1]) == 1.0 and abs(float(alloc[0][2]) - 1.00) < 0.005
    cur.execute("SELECT status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "open"                  # position remains actionable


def test_assignment_model_a_premium_once(ephemeral_db):
    """P0-5: covered-call assignment — premium counted ONCE (options), stock
    transfer strike-only, invariant fields persisted."""
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import record_assignment
    spid, _ = _mk_position(cur, conn, contracts=1.0, opening=2.82)
    r = record_assignment(cur, conn, spid, "TEST  260821C00110000", "schwab", "assign:test1")
    assert r["ok"] and r["premium_accounting_mode"] == "A_option_retains_premium"
    assert abs(r["premium_retained_in_options"] - 282.0) < 0.01
    cur.execute("""SELECT premium_transferred_to_stock, stock_basis_transfer_amount,
                          premium_retained_in_options FROM options_stock_basis_transfers
                   WHERE strategy_position_id=%s""", (spid,))
    tr = cur.fetchone()
    assert float(tr[0]) == 0.0                     # Model A: nothing moves to stock
    assert abs(float(tr[1]) - 11000.0) < 0.01      # strike-only stock economics
    assert abs(float(tr[2]) - 282.0) < 0.01
    cur.execute("SELECT realized_pnl FROM options_lifecycle_outcomes WHERE strategy_position_id=%s", (spid,))
    assert abs(float(cur.fetchone()[0]) - 282.0) < 0.01   # premium exactly once
    cur.execute("SELECT status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "assigned"


def test_outbox_unique_and_stale_guard(ephemeral_db):
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import _queue_projection, process_projection_outbox
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    conn.commit()
    _queue_projection(cur, spid)
    _queue_projection(cur, spid)   # duplicate → unique constraint absorbs it
    conn.commit()
    cur.execute("SELECT count(*) FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == 1
    r = process_projection_outbox(cur, conn)
    assert r["projected"] == 1
    cur.execute("SELECT state FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "PROJECTED"


def test_provisional_basis_survives_snapshots(ephemeral_db):
    """P0-2 regression: manual basis → snapshots don't clear provisional →
    confirm promotes to ok."""
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_lifecycle_basis import record_operator_basis, confirm_operator_basis
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status, data_quality_status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open','incomplete_basis')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    cur.execute("""INSERT INTO options_strategy_legs
        (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
         contracts, multiplier, strike, expiration)
        VALUES (%s,'TEST  260821C00110000','short_call','call','STO','short',1,100,110,'2026-08-21')
        RETURNING leg_id""", (spid,))
    leg_id = cur.fetchone()[0]
    conn.commit()
    rb = record_operator_basis(cur, conn, leg_id, opening_premium=2.0, opening_date="2026-07-01",
                               contracts=1, fees=None, source_ref="stmt-p3.png", operator="john")
    assert rb["ok"] and rb["review_status"] == "unreviewed"
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "provisional_basis"
    # simulate 10 monitoring cycles applying the pricing axis
    for _ in range(10):
        cur.execute("""UPDATE options_strategy_positions SET
                       data_quality_status=CASE WHEN data_quality_status='provisional_basis'
                         AND 'ok'='ok' THEN 'provisional_basis' ELSE 'ok' END
                       WHERE strategy_position_id=%s""", (spid,))
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "provisional_basis"
    cur.execute("SELECT evidence_id FROM options_basis_evidence WHERE leg_id=%s", (leg_id,))
    cf = confirm_operator_basis(cur, conn, cur.fetchone()[0], "john")
    assert cf["ok"]
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "ok"


def test_concurrent_fill_evidence_cannot_corrupt(ephemeral_db):
    """P0-4: two sessions writing different executions concurrently — row locks
    serialize the mutation; totals stay exact, no corruption."""
    import threading, os
    conn = ephemeral_db
    cur = _build_all(conn)
    # capture the schema so worker threads join the same namespace
    cur.execute("SELECT current_schema()")
    schema = cur.fetchone()[0]
    from options_fill_evidence import record_broker_evidence
    spid, tid = _mk_position(cur, conn, contracts=2.0)
    occ = "TEST  260821C00110000"
    errs = []

    def worker(eid, px):
        try:
            c2 = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                  user=os.environ.get("DB_USER", "postgres"),
                                  password=os.environ.get("DB_PASSWORD", ""),
                                  host=os.environ.get("DB_HOST", "localhost"),
                                  port=os.environ.get("DB_PORT", "5432"))
            k2 = c2.cursor()
            k2.execute(f'SET search_path TO "{schema}"')
            r = record_broker_evidence(k2, c2, tid, [_fill(occ, 1, px, f"o{eid}", f"e{eid}")], "schwab")
            if not r.get("ok"):
                errs.append(r.get("error"))
            c2.close()
        except Exception as e:
            errs.append(str(e))

    t1 = threading.Thread(target=worker, args=("c1", 1.10))
    t2 = threading.Thread(target=worker, args=("c2", 0.90))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not errs, errs
    cur.execute("SELECT COALESCE(sum(contracts),0) FROM options_fill_evidence WHERE ticket_id=%s", (tid,))
    assert float(cur.fetchone()[0]) == 2.0
    cur.execute("""SELECT COALESCE(sum(contracts),0) FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND status='closed'""", (spid,))
    assert float(cur.fetchone()[0]) == 2.0             # exactly two closed, no corruption
    cur.execute("SELECT status FROM options_lifecycle_tickets WHERE ticket_id=%s", (tid,))
    assert cur.fetchone()[0] == "filled"
    cur.execute("SELECT realized_pnl FROM options_lifecycle_outcomes WHERE strategy_position_id=%s", (spid,))
    # VWAP 1.00 → (2.00-1.00)*2*100 - 1.30? no commissions passed → 200 net
    assert abs(float(cur.fetchone()[0]) - 200.0) < 0.01


def _mk_ticket_for(cur, conn, spid, contracts, key, occ="TEST  260821C00110000"):
    import json as _j
    ticket = {"kind": "close", "strategy_position_id": spid, "underlying": "TEST",
              "strategy_type": "covered_call", "broker": "schwab", "account_key": "acct",
              "legs": [{"occ_symbol": occ, "instruction": "BTC",
                        "contracts": contracts, "proposed_limit": 1.0}],
              "net_debit_credit": -100.0 * contracts, "net_label": "pay", "tif": "DAY",
              "quote_ts": "t", "quote_max_age_seconds": 90}
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, status, idempotency_key)
        VALUES (%s,'close',%s,'h','DAY','armed',%s) RETURNING ticket_id""",
        (spid, _j.dumps(ticket), key))
    tid = cur.fetchone()[0]
    conn.commit()
    return tid


def test_cross_ticket_partial_cancel_then_residual_close(ephemeral_db):
    """v1.2.2 P0-1 MANDATED TRACE: Ticket A partial-fills then cancels; Ticket B
    closes the residual. A's allocation stays immutable; totals exact."""
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import record_broker_evidence
    spid, tidA = _mk_position(cur, conn, contracts=2.0, opening=2.00)
    occ = "TEST  260821C00110000"
    # 3: Ticket A fills one at $1.00 (with a fee)
    rA = record_broker_evidence(cur, conn, tidA, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 1.00,
         "commission": 0.65, "broker_order_id": "oA", "broker_execution_id": "eA1"}], "schwab")
    assert rA["ok"] and not rA["ticket_complete"]
    # 4: Ticket A cancelled
    cur.execute("UPDATE options_lifecycle_tickets SET status='cancelled' WHERE ticket_id=%s", (tidA,))
    conn.commit()
    # 5: one open residual + one immutable allocation
    cur.execute("SELECT status, contracts FROM options_strategy_legs WHERE strategy_position_id=%s", (spid,))
    assert [(r[0], float(r[1])) for r in cur.fetchall()] == [("open", 1.0)]
    cur.execute("""SELECT allocation_id, ticket_id, contracts, vwap, fees
                   FROM options_close_allocations WHERE strategy_position_id=%s""", (spid,))
    allocA = cur.fetchall()
    assert len(allocA) == 1 and allocA[0][1] == tidA and float(allocA[0][2]) == 1.0
    alloc_a_snapshot = allocA[0]
    # 6+7: Ticket B targets the 1-contract residual, fills at $0.50
    tidB = _mk_ticket_for(cur, conn, spid, 1.0, "kB")
    rB = record_broker_evidence(cur, conn, tidB, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 0.50,
         "commission": 0.65, "broker_order_id": "oB", "broker_execution_id": "eB1"}], "schwab")
    assert rB["ok"] and rB["ticket_complete"] and rB["position_closed"]
    # 8: assertions from DATABASE rows
    cur.execute("""SELECT allocation_id, ticket_id, contracts, vwap, fees
                   FROM options_close_allocations WHERE strategy_position_id=%s
                   ORDER BY allocation_id""", (spid,))
    allocs = cur.fetchall()
    assert len(allocs) == 2
    assert allocs[0] == alloc_a_snapshot                      # A's row byte-identical
    assert sum(float(a[2]) for a in allocs) == 2.0            # two contracts closed
    cur.execute("SELECT count(*) FROM options_strategy_legs WHERE strategy_position_id=%s AND status='open'",
                (spid,))
    assert cur.fetchone()[0] == 0                             # no open residual
    # gross P&L: (2.00-1.00)*100 + (2.00-0.50)*100 = 250; fees 1.30 once
    cur.execute("SELECT realized_pnl, meta FROM options_lifecycle_outcomes WHERE strategy_position_id=%s",
                (spid,))
    out = cur.fetchone()
    assert abs(float(out[0]) - (250.0 - 1.30)) < 0.01
    assert abs(float(out[1]["fees"]) - 1.30) < 0.01
    cur.execute("""SELECT status, pnl FROM trade_instances
                   WHERE source_table='options_strategy_positions' AND source_trade_id=%s""",
                (str(spid),))
    inst = cur.fetchone()
    assert inst[0] == "closed" and abs(float(inst[1]) - 248.70) < 0.01
    # replay A's execution (cancelled ticket) → refused-not-mutating; replay B (filled) → idempotent noop
    rA2 = record_broker_evidence(cur, conn, tidA, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 1.00,
         "commission": 0.65, "broker_order_id": "oA", "broker_execution_id": "eA1"}], "schwab")
    assert rA2["ok"] is False and "cancelled" in rA2["error"]
    rB2 = record_broker_evidence(cur, conn, tidB, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 0.50,
         "commission": 0.65, "broker_order_id": "oB", "broker_execution_id": "eB1"}], "schwab")
    assert rB2["ok"] and rB2.get("idempotent_noop") and rB2["all_fills_known"]
    cur.execute("SELECT realized_pnl FROM options_lifecycle_outcomes WHERE strategy_position_id=%s", (spid,))
    assert abs(float(cur.fetchone()[0]) - 248.70) < 0.01      # replays changed nothing


def test_two_partial_cancel_cycles(ephemeral_db):
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import record_broker_evidence
    spid, t1 = _mk_position(cur, conn, contracts=3.0, opening=2.00)
    occ = "TEST  260821C00110000"
    record_broker_evidence(cur, conn, t1, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 1.20,
         "broker_order_id": "o1", "broker_execution_id": "x1"}], "schwab")
    cur.execute("UPDATE options_lifecycle_tickets SET status='cancelled' WHERE ticket_id=%s", (t1,))
    conn.commit()
    t2 = _mk_ticket_for(cur, conn, spid, 2.0, "kC2")
    record_broker_evidence(cur, conn, t2, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 1.00,
         "broker_order_id": "o2", "broker_execution_id": "x2"}], "schwab")
    cur.execute("UPDATE options_lifecycle_tickets SET status='cancelled' WHERE ticket_id=%s", (t2,))
    conn.commit()
    t3 = _mk_ticket_for(cur, conn, spid, 1.0, "kC3")
    r = record_broker_evidence(cur, conn, t3, [
        {"occ_symbol": occ, "instruction": "BTC", "contracts": 1, "price": 0.80,
         "broker_order_id": "o3", "broker_execution_id": "x3"}], "schwab")
    assert r["position_closed"]
    cur.execute("""SELECT count(*), COALESCE(sum(contracts),0), COALESCE(sum(realized),0)
                   FROM options_close_allocations WHERE strategy_position_id=%s""", (spid,))
    n, qty, realized = cur.fetchone()
    assert n == 3 and float(qty) == 3.0
    assert abs(float(realized) - ((2.00-1.20)+(2.00-1.00)+(2.00-0.80))*100) < 0.01


def _two_leg_provisional(cur, conn):
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status, data_quality_status)
        VALUES ('schwab','acct','credit_spread','TEST','operator_manual','open','incomplete_basis')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    legs = []
    for occ, side in (("TEST  260918P00105000", "short"), ("TEST  260918P00100000", "long")):
        cur.execute("""INSERT INTO options_strategy_legs
            (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
             contracts, multiplier, strike, expiration)
            VALUES (%s,%s,%s,'put',%s,%s,1,100,%s,'2026-09-18') RETURNING leg_id""",
            (spid, occ, f"{side}_put", "STO" if side == "short" else "BTO", side,
             105 if side == "short" else 100))
        legs.append(cur.fetchone()[0])
    conn.commit()
    return spid, legs


def test_multileg_provisional_promotion_gates(ephemeral_db):
    """v1.2.2 P1-1: zero-of-two, one-of-two, two-of-two confirmations —
    promotion ONLY at two-of-two; uses the REAL snapshot persistence path."""
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_lifecycle_basis import record_operator_basis, confirm_operator_basis
    from options_lifecycle_engine import persist_snapshot
    from options_lifecycle_model import strategy_with_legs
    spid, (leg1, leg2) = _two_leg_provisional(cur, conn)
    e1 = record_operator_basis(cur, conn, leg1, opening_premium=1.5, opening_date="2026-07-01",
                               contracts=1, fees=None, source_ref="doc1.png", operator="john")
    # zero-of-two confirmed, one leg still NULL → NOT promoted (still not even provisional-complete)
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "incomplete_basis"
    e2 = record_operator_basis(cur, conn, leg2, opening_premium=0.7, opening_date="2026-07-01",
                               contracts=1, fees=None, source_ref="doc2.png", operator="john")
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "provisional_basis"
    # REAL snapshot persistence path must not clear provenance
    s = strategy_with_legs(cur, spid)
    persist_snapshot(cur, conn, s, {"flags": [], "legs_json": [], "dte_nearest": 30})
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "provisional_basis"
    # one-of-two confirmed → NOT promoted
    r1 = confirm_operator_basis(cur, conn, e1["evidence_id"], "john")
    assert r1["ok"] and r1["promoted"] is False and "unconfirmed" in r1["gate"]
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "provisional_basis"
    # two-of-two → promoted
    r2 = confirm_operator_basis(cur, conn, e2["evidence_id"], "john")
    assert r2["ok"] and r2["promoted"] is True
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "ok"


def test_broker_replacement_supersedes_and_promotes(ephemeral_db):
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_lifecycle_basis import record_operator_basis, _apply, _all_open_legs_confirmed
    from options_lifecycle_model import strategy_with_legs
    spid, (leg1, leg2) = _two_leg_provisional(cur, conn)
    record_operator_basis(cur, conn, leg1, opening_premium=1.5, opening_date="2026-07-01",
                          contracts=1, fees=None, source_ref="d1", operator="john")
    record_operator_basis(cur, conn, leg2, opening_premium=0.7, opening_date="2026-07-01",
                          contracts=1, fees=None, source_ref="d2", operator="john")
    s = strategy_with_legs(cur, spid)
    l1 = next(l for l in s["legs"] if l["leg_id"] == leg1)
    # broker replaces ONE provisional leg → original evidence preserved w/ lineage; not yet promoted
    _apply(cur, conn, l1, s, 1.48, "broker_orders", "schwab_order:999")
    cur.execute("""SELECT review_status FROM options_basis_evidence
                   WHERE leg_id=%s AND source_kind='operator_evidence'""", (leg1,))
    assert cur.fetchone()[0] == "superseded_by_broker"
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "provisional_basis"     # leg2 operator row still unconfirmed
    # broker replaces the second → promotion completes without operator confirm
    l2 = next(l for l in strategy_with_legs(cur, spid)["legs"] if l["leg_id"] == leg2)
    _apply(cur, conn, l2, s, 0.69, "broker_fill", "alpaca:abc")
    cur.execute("SELECT data_quality_status FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "ok"
    ok_all, why = _all_open_legs_confirmed(cur, spid)
    assert ok_all, why


def test_outbox_two_workers_project_once(ephemeral_db):
    """v1.2.2 P1-2: two REAL sessions run the claim loop concurrently — the row
    is projected exactly once (FOR UPDATE SKIP LOCKED)."""
    import threading, os
    conn = ephemeral_db
    cur = _build_all(conn)
    cur.execute("SELECT current_schema()")
    schema = cur.fetchone()[0]
    from options_fill_evidence import _queue_projection
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    conn.commit()
    _queue_projection(cur, spid)
    conn.commit()
    results, errs = [], []

    def worker():
        try:
            from options_fill_evidence import process_projection_outbox
            c2 = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                  user=os.environ.get("DB_USER", "postgres"),
                                  password=os.environ.get("DB_PASSWORD", ""),
                                  host=os.environ.get("DB_HOST", "localhost"),
                                  port=os.environ.get("DB_PORT", "5432"))
            k2 = c2.cursor()
            k2.execute(f'SET search_path TO "{schema}"')
            results.append(process_projection_outbox(k2, c2))
            c2.close()
        except Exception as e:
            errs.append(str(e))

    t1, t2 = threading.Thread(target=worker), threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not errs, errs
    assert sum(r["projected"] for r in results) == 1      # exactly ONE projection
    cur.execute("SELECT count(*) FROM trade_instances WHERE source_trade_id=%s", (str(spid),))
    assert cur.fetchone()[0] == 1


def test_outbox_crash_after_claim_recovers(ephemeral_db):
    """v1.2.2 P1-2: crash injection — a worker claims (PROCESSING committed)
    then dies; after the lease timeout the row recovers to RETRY and projects."""
    conn = ephemeral_db
    cur = _build_all(conn)
    from options_fill_evidence import _queue_projection, process_projection_outbox
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, source, status)
        VALUES ('schwab','acct','covered_call','TEST','operator_manual','open')
        RETURNING strategy_position_id""")
    spid = cur.fetchone()[0]
    conn.commit()
    _queue_projection(cur, spid)
    conn.commit()
    # simulate the crash: claim committed as PROCESSING, worker never returns
    cur.execute("""UPDATE journal_projection_outbox SET state='PROCESSING', attempts=1,
                   claimed_at=now() - interval '11 minutes'
                   WHERE strategy_position_id=%s""", (spid,))
    conn.commit()
    r = process_projection_outbox(cur, conn)   # stranded recovery (>10 min lease) then project
    assert r["projected"] == 1
    cur.execute("SELECT state FROM journal_projection_outbox WHERE strategy_position_id=%s", (spid,))
    assert cur.fetchone()[0] == "PROJECTED"
