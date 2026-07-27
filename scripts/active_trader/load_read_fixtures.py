#!/usr/bin/env python3
"""Active Trader Stage 4 — deterministic lab fixture loader (WRITE identity).

Populates trade_ai_test with the Stage 4 read-API fixture set using the
trade_ai_lab WRITE identity (env ACTIVE_TRADER_TEST_DATABASE_DSN). The API
runtime itself uses the separate read-only identity and can never do this.
Idempotent: keyed rows are deleted-then-inserted inside one transaction.
No real account number or secret value appears anywhere.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from active_trader.migrate import _resolve_dsn  # noqa: E402

NOW = datetime(2026, 7, 22, 21, 30, tzinfo=timezone.utc)
S_SHADOW = "00000000-0000-4000-8000-00000000a001"
S_SIM = "00000000-0000-4000-8000-00000000a002"
D_SHADOW = "00000000-0000-4000-8000-00000000d001"
D_SIM = "00000000-0000-4000-8000-00000000d002"


def main() -> int:
    dsn = _resolve_dsn(os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN"))
    import psycopg2
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    try:
        # -- sessions: saved SHADOW draft + AUTHORIZED SIMULATION session
        cur.execute("DELETE FROM active_trader_session_accounts WHERE session_authorization_id IN (%s,%s)",
                    (S_SHADOW, S_SIM))
        cur.execute("DELETE FROM active_trader_order_intents WHERE idempotency_key LIKE 'stage4-fx-%%'")
        cur.execute("DELETE FROM active_trader_position_states WHERE position_state_id::text LIKE '00000000-0000-4000-8000-%%'")
        cur.execute("DELETE FROM active_trader_session_authorizations WHERE session_authorization_id IN (%s,%s)",
                    (S_SHADOW, S_SIM))
        for did, ver, env, name in ((D_SHADOW, 1, "SHADOW", "stage4 shadow draft"),
                                    (D_SIM, 1, "SIMULATION", "stage4 sim session")):
            cur.execute("SELECT 1 FROM active_trader_session_drafts WHERE draft_id=%s AND draft_version=%s",
                        (did, ver))
            if not cur.fetchone():
                cur.execute(
                    """INSERT INTO active_trader_session_drafts
                       (draft_id, draft_version, environment, session_name, broker_set,
                        account_policy, symbol_policy, risk_limits, time_bounds, runner_policy,
                        feature_policy_versions, draft_hash, created_by)
                       VALUES (%s,%s,%s,%s,'["alpaca"]','{}','{"symbols":["TESTA"]}',
                               '{"max_trades":3,"max_daily_loss":50}','{}','{}','{}',%s,'stage4-fixture')""",
                    (did, ver, env, name, f"hash-{did}"))
        for sid, did, env, status in ((S_SHADOW, D_SHADOW, "SHADOW", "PENDING"),
                                      (S_SIM, D_SIM, "SIMULATION", "AUTHORIZED")):
            cur.execute(
                """INSERT INTO active_trader_session_authorizations
                   (session_authorization_id, draft_id, draft_version, environment,
                    authorization_hash, draft_hash, operator_id, status, session_start,
                    session_entry_cutoff, session_expiry)
                   VALUES (%s,%s,1,%s,%s,%s,'stage4-fixture',%s,%s,%s,%s)""",
                (sid, did, env, f"auth-{sid}", f"hash-{did}", status,
                 NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=4)))
        cur.execute(
            """INSERT INTO active_trader_session_accounts
               (session_authorization_id, broker, account_label, environment, role, max_shares)
               VALUES (%s,'alpaca','alpaca_paper','SIMULATION','PRIMARY',100)""", (S_SIM,))
        # -- order + position + journal
        cur.execute(
            """INSERT INTO active_trader_order_intents
               (order_intent_id, environment, session_authorization_id, authorization_hash,
                broker, account_label, symbol, side, quantity, order_type, time_in_force,
                trading_session, idempotency_key, input_hash, status)
               VALUES (%s,'SIMULATION',%s,%s,'alpaca','alpaca_paper','TESTA','BUY',10,
                       'LIMIT','DAY','RTH','stage4-fx-order-1','ih','VALIDATED')""",
            (str(uuid.uuid4()), S_SIM, f"auth-{S_SIM}"))
        cur.execute(
            """INSERT INTO active_trader_position_states
               (position_state_id, environment, session_authorization_id, broker, account_label,
                symbol, state, quantity, avg_entry, protection_state, resilience_score,
                resistance_score, as_of)
               VALUES ('00000000-0000-4000-8000-00000000e001','SIMULATION',%s,'alpaca',
                       'alpaca_paper','TESTA','MANAGING',10,4.10,'CONFIRMED',72,38,%s)""",
            (S_SIM, NOW))
        cur.execute("SELECT 1 FROM active_trader_journal_events WHERE session_authorization_id=%s AND event_type='order_intent_created'", (S_SIM,))
        if not cur.fetchone():
            cur.execute("""INSERT INTO active_trader_journal_events
                           (environment, event_type, session_authorization_id, symbol, payload,
                            replay_segment_ref, occurred_at)
                           VALUES ('SIMULATION','order_intent_created',%s,'TESTA','{}',
                                   'replay://stage4/segment-001',%s)""", (S_SIM, NOW))
        # -- capability evidence: fresh + stale + conflicting
        for cap, state, source, verified, expires in (
                ("READ_ACCOUNT", "SUPPORTED", "RUNTIME_PROBE", NOW, NOW + timedelta(hours=24)),
                ("BRACKET_ORDER", "SUPPORTED", "RUNTIME_PROBE", NOW - timedelta(days=3),
                 NOW - timedelta(days=2)),                              # stale -> UNKNOWN
                ("TRAILING_STOP", "UNSUPPORTED", "DOCUMENTATION", None, NOW + timedelta(days=30))):
            cur.execute(
                """INSERT INTO broker_account_capabilities
                   (broker, account_label, environment, capability, state, source, verified_at,
                    expires_at, adapter_version, notes)
                   VALUES ('alpaca','fixture_acct','SIMULATION',%s,%s,%s,%s,%s,'stage4-fixture','')
                   ON CONFLICT (broker, account_label, environment, capability)
                   DO UPDATE SET state=EXCLUDED.state, source=EXCLUDED.source,
                        verified_at=EXCLUDED.verified_at, expires_at=EXCLUDED.expires_at""",
                (cap, state, source, verified, expires))
        conn.commit()
        print("stage4 fixtures loaded (idempotent)")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
