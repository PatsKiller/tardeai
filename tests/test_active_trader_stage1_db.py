"""Stage 1 database tests — run EXCLUSIVELY against the isolated lab cluster.

Requires ACTIVE_TRADER_TEST_DATABASE_DSN in the environment (Bitwarden project
trade-ai-lab). Every test is skipped with an explicit reason when the DSN is
absent. The suite refuses (via the migration runner's guards) to ever touch a
database named trade_ai or the production cluster port.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

DSN = os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="ACTIVE_TRADER_TEST_DATABASE_DSN not set (lab DB required; never runs on production)")

psycopg2 = pytest.importorskip("psycopg2")


def run_migrate(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "active_trader" / "migrate.py"), *args],
        capture_output=True, text=True,
        env={**os.environ, "ACTIVE_TRADER_TEST_DATABASE_DSN": DSN})


@pytest.fixture(scope="module")
def db():
    r = run_migrate("reapply")
    assert r.returncode == 0, r.stderr + r.stdout
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    yield conn
    conn.close()


def test_migration_forward_rollback_reapply_cycle():
    assert run_migrate("up").returncode == 0            # idempotent no-op after reapply
    down = run_migrate("down", "--all")
    assert down.returncode == 0 and "rolled back" in down.stdout
    up = run_migrate("up")
    assert up.returncode == 0 and "applied" in up.stdout
    status = run_migrate("status")
    assert status.returncode == 0 and "pending" not in status.stdout and "DRIFT" not in status.stdout


def test_runner_refuses_production_targets():
    r = run_migrate("status", "--dsn", "postgresql://u:p@localhost:5432/trade_ai")
    assert r.returncode == 2 and "REFUSED" in r.stderr
    r2 = run_migrate("status", "--dsn", "postgresql://u:p@localhost:5433/trade_ai")
    assert r2.returncode == 2 and "production" in r2.stderr
    r3 = run_migrate("status", "--dsn", "UNSET__OPERATOR_REQUIRED")
    assert r3.returncode == 2 and "Sentinel" in r3.stderr


def _mk_session(cur, env="LIVE"):
    did, aid = str(uuid.uuid4()), str(uuid.uuid4())
    cur.execute(
        """INSERT INTO active_trader_session_drafts
           (draft_id, draft_version, environment, session_name, broker_set, account_policy,
            symbol_policy, risk_limits, time_bounds, runner_policy, feature_policy_versions,
            draft_hash, created_by)
           VALUES (%s,1,%s,'t','["alpaca"]','{}','{}','{}','{}','{}','{}',%s,'op')""",
        (did, env, "hash-" + did))
    cur.execute(
        """INSERT INTO active_trader_session_authorizations
           (session_authorization_id, draft_id, draft_version, environment, authorization_hash,
            draft_hash, operator_id, status, session_start, session_entry_cutoff, session_expiry)
           VALUES (%s,%s,1,%s,%s,%s,'op','AUTHORIZED', now(), now()+interval '1h', now()+interval '4h')""",
        (aid, did, env, "auth-" + aid, "hash-" + did))
    return aid


def _intent_row(cur, env, key, session_id=None, auth_hash=None, status="DRAFT"):
    cur.execute(
        """INSERT INTO active_trader_order_intents
           (order_intent_id, environment, session_authorization_id, authorization_hash, broker,
            account_label, symbol, side, quantity, order_type, time_in_force, trading_session,
            idempotency_key, input_hash, status)
           VALUES (%s,%s,%s,%s,'alpaca','paper','GRAB','BUY',1,'LIMIT','DAY','RTH',%s,'ih',%s)""",
        (str(uuid.uuid4()), env, session_id, auth_hash, key, status))


def test_live_intent_requires_authorization_in_db(db):
    cur = db.cursor()
    with pytest.raises(psycopg2.errors.CheckViolation):
        _intent_row(cur, "LIVE", "k-live-bare")
    aid = _mk_session(cur)
    _intent_row(cur, "LIVE", "k-live-ok", session_id=aid, auth_hash="auth-" + aid)


def test_environment_not_null_no_default(db):
    cur = db.cursor()
    with pytest.raises(psycopg2.errors.NotNullViolation):
        _intent_row(cur, None, "k-noenv")
    with pytest.raises(psycopg2.errors.CheckViolation):
        _intent_row(cur, "PROD", "k-badenv")


def test_idempotency_key_cannot_be_reused_across_environments(db):
    cur = db.cursor()
    _intent_row(cur, "SIMULATION", "k-shared")
    aid = _mk_session(cur)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _intent_row(cur, "LIVE", "k-shared", session_id=aid, auth_hash="auth-" + aid)


def test_shadow_rows_cannot_carry_write_states(db):
    cur = db.cursor()
    with pytest.raises(psycopg2.errors.CheckViolation):
        _intent_row(cur, "SHADOW", "k-shadow-sub", status="SUBMITTED")
    _intent_row(cur, "SHADOW", "k-shadow-ok", status="DRAFT")


def test_session_drafts_are_append_only(db):
    cur = db.cursor()
    _mk_session(cur, env="SIMULATION")
    with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
        cur.execute("UPDATE active_trader_session_drafts SET session_name='x'")
    with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
        cur.execute("DELETE FROM active_trader_session_drafts")


def test_feature_flags_append_only_versioned_and_checked(db):
    cur = db.cursor()
    cur.execute("""INSERT INTO active_trader_feature_flags
                   (flag_name, scope_key, version, mode, reason, changed_by)
                   VALUES ('quick_add','global',1,'OFF','stage1 default','stage1')""")
    with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
        cur.execute("UPDATE active_trader_feature_flags SET mode='SHADOW'")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("""INSERT INTO active_trader_feature_flags
                       (flag_name, scope_key, version, mode, reason, changed_by)
                       VALUES ('quick_add','global',2,'ON','bad mode','stage1')""")


def test_journal_events_append_only(db):
    cur = db.cursor()
    cur.execute("""INSERT INTO active_trader_journal_events (environment, event_type, payload, occurred_at)
                   VALUES ('SHADOW','candidate_discovered','{}', now())""")
    with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
        cur.execute("DELETE FROM active_trader_journal_events")


def test_capability_supported_requires_evidence(db):
    cur = db.cursor()
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("""INSERT INTO broker_account_capabilities
                       (broker, account_label, environment, capability, state, source)
                       VALUES ('schwab','a','LIVE','BRACKET_ORDER','SUPPORTED','DOCUMENTATION')""")
    cur.execute("""INSERT INTO broker_account_capabilities
                   (broker, account_label, environment, capability, state, source)
                   VALUES ('schwab','a','LIVE','BRACKET_ORDER','UNKNOWN','DOCUMENTATION')""")


def test_checkpoint_row_contract(db):
    cur = db.cursor()
    cur.execute("""INSERT INTO active_trader_run_checkpoints
                   (run_id, architecture_version, program_version, base_sha, branch,
                    current_stage, state, version)
                   VALUES ('20260722-01','v3.3','v1.1','87c2fa09','feat/active-trader-next',1,'RUNNING',1)""")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE active_trader_run_checkpoints SET state='DONE' WHERE run_id='20260722-01'")
    cur.execute("SELECT state, version FROM active_trader_run_checkpoints WHERE run_id='20260722-01'")
    assert cur.fetchone() == ("RUNNING", 1)


def test_all_fourteen_tables_exist(db):
    cur = db.cursor()
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND (table_name LIKE 'active_trader%%'
                       OR table_name IN ('broker_account_capabilities','broker_rejection_events'))
                   ORDER BY 1""")
    tables = {r[0] for r in cur.fetchall()}
    expected = {
        "active_trader_session_drafts", "active_trader_session_authorizations",
        "active_trader_session_accounts", "active_trader_order_intents",
        "active_trader_position_states", "active_trader_journal_events",
        "active_trader_score_snapshots", "active_trader_parity_checks",
        "broker_account_capabilities", "broker_rejection_events",
        "active_trader_feature_flags", "active_trader_notification_events",
        "active_trader_drive_sync_manifest", "active_trader_run_checkpoints",
        "active_trader_schema_migrations",
    }
    assert expected <= tables
