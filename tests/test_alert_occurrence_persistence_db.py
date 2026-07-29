#!/usr/bin/env python3
"""DB-backed proof that should_notify() is authoritative in persistence.

Requires an ISOLATED PostgreSQL. Skips (does not silently pass) when absent:

    docker run -d --name tgnorm-occ -e POSTGRES_PASSWORD=x -e POSTGRES_DB=occtest \
        -p 55434:5432 postgres:16-alpine
    ALERT_TEST_DSN=postgresql://postgres:x@127.0.0.1:55434/occtest pytest tests/test_alert_occurrence_persistence_db.py

Never touches the production database: it refuses any DSN naming trade_ai.

Every case here fails under the old one-row-per-fingerprint model, which is the point.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DSN = os.getenv("ALERT_TEST_DSN", "postgresql://postgres:x@127.0.0.1:55434/occtest")
psycopg2 = pytest.importorskip("psycopg2")

from alert_routing_resolver import resolve_route            # noqa: E402
from operator_alert_policy_v2 import AlertEvent             # noqa: E402
from alert_occurrence_store import record_occurrence        # noqa: E402

T0 = datetime(2026, 7, 28, 14, 0, 0, tzinfo=timezone.utc)
MIGRATION = ROOT / "migrations" / "2026_07_28_alert_notification_outbox.sql"
DOWN = ROOT / "migrations" / "2026_07_28_alert_notification_outbox.down.sql"


def _connect():
    if "trade_ai" in DSN:
        pytest.fail("refusing to run against the production database")
    try:
        return psycopg2.connect(DSN, connect_timeout=3)
    except Exception as e:
        pytest.skip(f"no isolated postgres at {DSN} ({type(e).__name__}) — "
                    f"migration/concurrency verification NOT performed")


@pytest.fixture()
def conn():
    c = _connect()
    with c.cursor() as cur:
        cur.execute(DOWN.read_text())
        cur.execute(MIGRATION.read_text())
    c.commit()
    yield c
    c.rollback()
    c.close()


def ev(alert_type="orphaned_stop", **kw):
    base = dict(alert_type=alert_type, source_system="test", source_producer="pytest",
                entity_id="e1", account_id="acct1", symbol="AAPL", severity="warning")
    base.update(kw)
    return AlertEvent(**base)


def publish(conn, event, *, at, dedupe="FP", window=900, escalate=None,
            resolving=False, incident="inc1", alert_id=None, corr=None):
    route = resolve_route(event, mode="ACTIVE",
                          preferences={"general_telegram": "IMMEDIATE",
                                       "dedupe_window_seconds": window,
                                       "escalate_after_seconds": escalate})
    return record_occurrence(
        conn, incident_id=incident, alert_id=alert_id or f"al_{at.timestamp()}",
        dedupe_key=dedupe, event=event, route=route, observed_at=at,
        correlation_key=corr, resolving=resolving, runtime_mode="ACTIVE")


def _counts(conn, dedupe="FP"):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM alert_occurrences WHERE dedupe_key=%s", (dedupe,))
        occ = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM alert_occurrences WHERE dedupe_key=%s AND notify", (dedupe,))
        notified = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM alert_incidents WHERE dedupe_key=%s", (dedupe,))
        inc = cur.fetchone()[0]
    return occ, notified, inc


class TestOccurrencePersistence:
    def test_first_occurrence_notifies_and_creates_incident(self, conn):
        r = publish(conn, ev(), at=T0)
        assert r["accepted"] and r["suppressed"] is False
        assert r["decision"]["reason"] == "first_occurrence"
        assert _counts(conn) == (1, 1, 1)

    def test_duplicate_inside_window_persists_but_suppresses(self, conn):
        publish(conn, ev(), at=T0)
        r = publish(conn, ev(), at=T0 + timedelta(minutes=5), alert_id="al_dup")
        assert r["suppressed"] and r["suppression_reason"] == "duplicate_within_dedupe_window"
        occ, notified, inc = _counts(conn)
        # history preserved: 2 occurrences, only 1 notified, still ONE incident
        assert (occ, notified, inc) == (2, 1, 1)

    def test_recurrence_after_window_notifies_again(self, conn):
        """Impossible under UNIQUE(fingerprint): the row already existed forever.

        Escalation is pushed far out so the WINDOW rule is the one under test.
        orphaned_stop's policy default is escalate_after_seconds=1800, which would
        otherwise fire first at T+3h — also a notify, but a different rule.
        """
        publish(conn, ev(), at=T0)
        r = publish(conn, ev(), at=T0 + timedelta(hours=3), alert_id="al_later",
                    escalate=30 * 86400)
        assert r["suppressed"] is False
        assert r["decision"]["reason"] == "dedupe_window_elapsed"
        assert _counts(conn) == (2, 2, 1)

    def test_escalation_takes_precedence_over_window_elapsed(self, conn):
        """Both notify; escalation is the more specific reason and wins by design.

        Pinned deliberately: an unacknowledged live condition past its escalation
        deadline should be reported as an escalation, not as a routine recurrence,
        because the operator response differs.
        """
        publish(conn, ev(), at=T0)
        r = publish(conn, ev(), at=T0 + timedelta(hours=3), alert_id="al_prec",
                    window=900, escalate=1800)
        assert r["suppressed"] is False
        assert r["decision"]["reason"] == "escalation_deadline_passed"
        assert r["decision"]["is_escalation"] is True

    def test_payload_history_is_immutable(self, conn):
        publish(conn, ev(payload={"occ": 1}), at=T0)
        publish(conn, ev(payload={"occ": 2}), at=T0 + timedelta(hours=3), alert_id="al_2")
        with conn.cursor() as cur:
            cur.execute("SELECT payload->>'occ' FROM alert_occurrences "
                        "WHERE dedupe_key='FP' ORDER BY occurrence_seq")
            got = [r[0] for r in cur.fetchall()]
        assert got == ["1", "2"], "earlier occurrence payload was overwritten"

    def test_severity_increase_breaks_window(self, conn):
        publish(conn, ev(severity="warning"), at=T0)
        r = publish(conn, ev(severity="critical"), at=T0 + timedelta(minutes=2), alert_id="al_sev")
        assert r["suppressed"] is False
        assert r["decision"]["reason"] == "severity_increased"
        assert r["material_transition"] is True

    def test_action_required_transition_breaks_window(self, conn):
        publish(conn, ev(operator_action_required=False), at=T0)
        r = publish(conn, ev(operator_action_required=True),
                    at=T0 + timedelta(minutes=2), alert_id="al_act")
        assert r["decision"]["reason"] == "operator_action_now_required"

    def test_state_version_change_breaks_window(self, conn):
        publish(conn, ev(state_version="1"), at=T0)
        r = publish(conn, ev(state_version="2"), at=T0 + timedelta(minutes=2), alert_id="al_sv")
        assert r["decision"]["reason"] == "state_version_changed"

    def test_resolution_then_recurrence_opens_a_new_incident(self, conn):
        publish(conn, ev(), at=T0)
        r = publish(conn, ev(), at=T0 + timedelta(minutes=30), alert_id="al_res", resolving=True)
        assert r["decision"]["is_resolution"] is True
        again = publish(conn, ev(), at=T0 + timedelta(hours=2),
                        alert_id="al_recur", incident="inc2")
        assert again["suppressed"] is False
        occ, notified, inc = _counts(conn)
        assert inc == 2, "a resolved condition must be able to recur as a NEW incident"

    def test_escalation_deadline_reraises(self, conn):
        publish(conn, ev(), at=T0)
        r = publish(conn, ev(), at=T0 + timedelta(minutes=40), alert_id="al_esc",
                    window=86400, escalate=1800)
        assert r["suppressed"] is False
        assert r["decision"]["reason"] == "escalation_deadline_passed"
        assert r["decision"]["is_escalation"] is True

    def test_decision_inputs_are_auditable(self, conn):
        publish(conn, ev(), at=T0)
        publish(conn, ev(), at=T0 + timedelta(minutes=5), alert_id="al_aud")
        with conn.cursor() as cur:
            cur.execute("SELECT decision_reason, decision_inputs FROM alert_occurrences "
                        "WHERE alert_id='al_aud'")
            reason, inputs = cur.fetchone()
        assert reason == "duplicate_within_dedupe_window"
        assert inputs["prior"]["notified_count"] == 1
        assert inputs["dedupe_window_seconds"] == 900

    def test_restart_durability_state_comes_from_db_not_memory(self, conn):
        publish(conn, ev(), at=T0)
        conn.commit()
        fresh = _connect()                       # simulates a process restart
        try:
            r = publish(fresh, ev(), at=T0 + timedelta(minutes=5), alert_id="al_restart")
            assert r["suppressed"], "prior state was not read from the database"
        finally:
            fresh.close()

    def test_concurrent_duplicate_publication_notifies_once(self, conn):
        """Two publishers, same condition, same instant."""
        a, b = _connect(), _connect()
        try:
            r1 = publish(a, ev(), at=T0, alert_id="al_c1")
            r2 = publish(b, ev(), at=T0, alert_id="al_c2")
            notified = [r for r in (r1, r2) if not r["suppressed"]]
            assert len(notified) == 1, f"expected exactly one notify, got {len(notified)}"
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM alert_incidents WHERE dedupe_key='FP'")
                assert cur.fetchone()[0] == 1, "duplicate open incidents created"
        finally:
            a.close(); b.close()

    def test_only_one_sent_delivery_per_occurrence(self, conn):
        r = publish(conn, ev(), at=T0)
        occ = r["occurrence_id"]
        with conn.cursor() as cur:
            cur.execute("UPDATE alert_notification_deliveries SET delivery_status='sent' "
                        "WHERE occurrence_id=%s", (occ,))
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO alert_notification_deliveries "
                    "(occurrence_id, alert_id, attempt_seq, route_mode, delivery_status) "
                    "VALUES (%s,'dup',2,'IMMEDIATE','sent')", (occ,))
        conn.rollback()
