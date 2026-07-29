#!/usr/bin/env python3
"""DB-backed proof that _record_delivery() writes the occurrence model correctly.

Regression cover for the 2026-07-29 fix. The previous implementation ran

    UPDATE alert_notification_events SET last_delivery_status=..., delivery_count=delivery_count+1
    UPDATE alert_notification_events SET suppression_reason=..., last_suppression_at=now()

against what the migration makes a derived JOIN VIEW. Three defects, all from the
module being written against the first-draft schema where that name was a TABLE:
the view is not auto-updatable, last_suppression_at exists nowhere, and the
delivery row was inserted with a NULL occurrence_id — the column BOTH unique
indexes key on.

Every case here fails against the pre-fix implementation, which is the point.

Requires an ISOLATED PostgreSQL. Skips (never silently passes) when absent:

    docker run -d --name tgnorm-deliv -e POSTGRES_PASSWORD=x -e POSTGRES_DB=delivtest \
        -p 55435:5432 postgres:16-alpine
    ALERT_TEST_DSN=postgresql://postgres:x@127.0.0.1:55435/delivtest \
        pytest tests/test_alert_delivery_recording_db.py

Never touches the production database: it refuses any DSN naming trade_ai.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DSN = os.getenv("ALERT_TEST_DSN", "postgresql://postgres:x@127.0.0.1:55435/delivtest")
psycopg2 = pytest.importorskip("psycopg2")

MIGRATION = ROOT / "migrations" / "2026_07_28_alert_notification_outbox.sql"
VIEW_FIX = ROOT / "migrations" / "2026_07_29_alert_events_view_last_delivery.sql"


def _connect():
    if "trade_ai" in DSN:
        pytest.skip("refusing to run against a DSN naming trade_ai (production)")
    try:
        return psycopg2.connect(DSN)
    except Exception as e:                                          # pragma: no cover
        pytest.skip(f"no isolated postgres at {DSN} ({type(e).__name__}) — "
                    f"start the container in this module's docstring")


@pytest.fixture()
def cur():
    conn = _connect()
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute(MIGRATION.read_text())
        c.execute(VIEW_FIX.read_text())
        c.execute("TRUNCATE alert_notification_deliveries, alert_occurrences, alert_incidents CASCADE")
    conn.autocommit = False
    with conn.cursor() as c:
        yield c
    conn.rollback()
    conn.close()


def _seed(c, alert_id="a1", incident_id="i1", notify=True, route="IMMEDIATE"):
    c.execute(
        """INSERT INTO alert_incidents
           (incident_id, dedupe_key, alert_type, source_system, source_producer, status,
            severity, route_mode, logical_destination, policy_version, environment, synthetic)
           VALUES (%s,%s,'debug_or_success','t','t','open','info',%s,'GENERAL','t','t',true)
           ON CONFLICT DO NOTHING""",
        (incident_id, "dk-" + incident_id, route),
    )
    c.execute(
        """INSERT INTO alert_occurrences
           (alert_id, incident_id, occurrence_seq, dedupe_key, observed_at, alert_type,
            source_producer, severity, payload, notify, decision_reason, runtime_mode,
            route_mode, logical_destination)
           VALUES (%s,%s,1,%s, now(),'debug_or_success','t','info','{}'::jsonb,%s,
                   'seeded','SHADOW',%s,'GENERAL')""",
        (alert_id, incident_id, "dk-" + incident_id, notify, route),
    )


def test_sent_delivery_is_tied_to_its_occurrence(cur):
    """The pre-fix insert left occurrence_id NULL, so neither unique index applied."""
    import alert_outbox as ao
    _seed(cur)
    ao._record_delivery(cur, "a1", "IMMEDIATE", "GENERAL", "sent", None, "msg")
    cur.execute("SELECT occurrence_id, attempt_seq, delivery_status, completed_at IS NOT NULL "
                "FROM alert_notification_deliveries WHERE alert_id='a1'")
    occ, seq, status, completed = cur.fetchone()
    assert occ is not None, "delivery row must carry its occurrence_id"
    assert (seq, status, completed) == (1, "sent", True)


def test_sent_increments_the_incident_counter_not_the_view(cur):
    import alert_outbox as ao
    _seed(cur)
    ao._record_delivery(cur, "a1", "IMMEDIATE", "GENERAL", "sent", None, "msg")
    cur.execute("SELECT notified_count, last_notified_at IS NOT NULL FROM alert_incidents WHERE incident_id='i1'")
    assert cur.fetchone() == (1, True)


def test_retry_does_not_double_count(cur):
    """one_sent_per_occurrence must absorb the retry AND stop the counter moving."""
    import alert_outbox as ao
    _seed(cur)
    ao._record_delivery(cur, "a1", "IMMEDIATE", "GENERAL", "sent", None, "msg")
    ao._record_delivery(cur, "a1", "IMMEDIATE", "GENERAL", "sent", None, "msg")
    cur.execute("SELECT notified_count FROM alert_incidents WHERE incident_id='i1'")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM alert_notification_deliveries WHERE alert_id='a1' AND delivery_status='sent'")
    assert cur.fetchone()[0] == 1


def test_suppressed_increments_only_the_suppressed_counter(cur):
    import alert_outbox as ao
    _seed(cur, alert_id="a2", incident_id="i2", notify=False, route="DIGEST")
    ao._record_delivery(cur, "a2", "DIGEST", "GENERAL", "suppressed", "duplicate_within_fingerprint", "m")
    cur.execute("SELECT notified_count, suppressed_count FROM alert_incidents WHERE incident_id='i2'")
    assert cur.fetchone() == (0, 1)


def test_view_surfaces_last_delivery_state(cur):
    """The read path GET /api/v3/alerts/active depends on these two columns."""
    import alert_outbox as ao
    _seed(cur)
    ao._record_delivery(cur, "a1", "IMMEDIATE", "GENERAL", "sent", None, "msg")
    cur.execute("SELECT last_delivery_status, last_delivery_at IS NOT NULL, delivery_count "
                "FROM alert_notification_events WHERE alert_id='a1'")
    assert cur.fetchone() == ("sent", True, 1)


def test_delivered_alert_leaves_the_pending_queue(cur):
    """pending_immediate() claims on last_delivery_status — a sent alert must drop out,
    or the immediate lane re-delivers forever."""
    import alert_outbox as ao
    _seed(cur)
    cur.execute("""SELECT count(*) FROM alert_notification_events
                    WHERE route_mode='IMMEDIATE' AND COALESCE(last_delivery_status,'') <> 'sent'
                      AND alert_id='a1'""")
    assert cur.fetchone()[0] == 1, "must be claimable before delivery"
    ao._record_delivery(cur, "a1", "IMMEDIATE", "GENERAL", "sent", None, "msg")
    cur.execute("""SELECT count(*) FROM alert_notification_events
                    WHERE route_mode='IMMEDIATE' AND COALESCE(last_delivery_status,'') <> 'sent'
                      AND alert_id='a1'""")
    assert cur.fetchone()[0] == 0, "must not be claimable after delivery"


def test_unknown_alert_id_is_a_noop_not_an_orphan_row(cur):
    import alert_outbox as ao
    ao._record_delivery(cur, "does-not-exist", "IMMEDIATE", "GENERAL", "sent", None, "m")
    cur.execute("SELECT count(*) FROM alert_notification_deliveries")
    assert cur.fetchone()[0] == 0
