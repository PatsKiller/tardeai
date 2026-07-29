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


# ============================================================================
# publish_event() over the occurrence model — DD/alerts 2026-07-29
#
# The previous implementation wrote INSERT ... ON CONFLICT (fingerprint) DO UPDATE
# into what the migration makes a derived VIEW, keyed the dedupe on the identity of
# the condition, and inferred the notify decision from "was the row new" instead of
# from should_notify() against persisted prior state. Every case below fails against
# it: the first three raise, and the rest assert behaviour it could not express.
# ============================================================================

from datetime import datetime, timedelta, timezone            # noqa: E402


def _event(sev="warning", action=False, sv="1", at=None):
    from operator_alert_policy_v2 import AlertEvent
    return AlertEvent(
        alert_type="debug_or_success", source_system="t", source_producer="t",
        entity_id="E1", symbol="ZZZZ", severity=sev,
        operator_action_required=action, state_version=sv,
        created_at=at or datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc),
        payload={"n": 1},
    )


@pytest.fixture()
def outbox(cur, monkeypatch):
    """Point alert_outbox at the isolated test connection."""
    import alert_outbox as ao
    monkeypatch.setattr(ao, "_db", lambda: cur.connection)
    monkeypatch.setattr(ao, "get_mode", lambda: "ACTIVE")
    return ao


T0 = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)


def test_alert_id_is_distinct_per_occurrence(outbox):
    """alert_occurrences.alert_id is UNIQUE and conditions recur — an id derived
    from the fingerprint alone collides on the second observation."""
    a = outbox.publish_event(_event(at=T0))
    b = outbox.publish_event(_event(at=T0 + timedelta(seconds=30)))
    assert a["alert_id"] != b["alert_id"]


def test_first_observation_notifies(outbox):
    r = outbox.publish_event(_event(at=T0))
    assert r["decision"]["notify"] is True
    assert r["decision"]["reason"] == "first_occurrence"


def test_repeat_inside_the_window_is_suppressed_but_still_recorded(outbox):
    """The old model overwrote the row and lost the occurrence. History is kept."""
    outbox.publish_event(_event(at=T0))
    r = outbox.publish_event(_event(at=T0 + timedelta(seconds=30)))
    assert r["decision"]["notify"] is False
    assert r["suppression_reason"] == "duplicate_within_dedupe_window"
    cur = outbox._db().cursor()
    cur.execute("SELECT count(*) FROM alert_occurrences")
    assert cur.fetchone()[0] == 2, "the suppressed observation must still be recorded"


def test_severity_escalation_breaks_through_the_window(outbox):
    """Invisible to the old model, which only knew 'was the row new'."""
    outbox.publish_event(_event(sev="warning", at=T0))
    r = outbox.publish_event(_event(sev="critical", at=T0 + timedelta(seconds=30)))
    assert r["decision"]["notify"] is True
    assert r["decision"]["reason"] == "severity_increased"
    assert r["material_transition"] is True


def test_window_elapsed_notifies_again(outbox):
    outbox.publish_event(_event(at=T0))
    r = outbox.publish_event(_event(at=T0 + timedelta(hours=2)))
    assert r["decision"]["notify"] is True
    assert r["decision"]["reason"] == "dedupe_window_elapsed"


def test_one_open_incident_per_condition(outbox):
    for i in range(4):
        outbox.publish_event(_event(at=T0 + timedelta(seconds=30 * i)))
    cur = outbox._db().cursor()
    cur.execute("SELECT count(*) FROM alert_incidents WHERE status='open'")
    assert cur.fetchone()[0] == 1


def test_incident_counters_track_notified_and_suppressed(outbox):
    outbox.publish_event(_event(at=T0))                                  # notify
    outbox.publish_event(_event(at=T0 + timedelta(seconds=30)))          # suppress
    outbox.publish_event(_event(sev="critical", at=T0 + timedelta(seconds=60)))  # notify
    cur = outbox._db().cursor()
    cur.execute("SELECT occurrence_count, notified_count, suppressed_count FROM alert_incidents")
    assert cur.fetchone() == (3, 2, 1)


def test_payload_history_is_never_overwritten(outbox):
    """The first draft's ON CONFLICT DO UPDATE SET payload = EXCLUDED.payload
    destroyed the record of what was actually observed."""
    outbox.publish_event(_event(at=T0))
    outbox.publish_event(_event(at=T0 + timedelta(seconds=30)))
    cur = outbox._db().cursor()
    cur.execute("SELECT count(DISTINCT occurrence_id) FROM alert_occurrences")
    assert cur.fetchone()[0] == 2
