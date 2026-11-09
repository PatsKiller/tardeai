"""LQ-20261107-1607 — the IMMEDIATE delivery queue: shadow rows are never work, the consumer never sends outside
ACTIVE, and the alert-delivery-queue-hygiene lane holds the "queued <= 10 min" contract (expire, never send; escalate
a dead consumer once).

ANCHOR: ALERT_DELIVERY_QUEUE_HYGIENE_20261109

Database cases need an isolated postgres (synthetic rows only), e.g.:
    ALERT_TEST_DSN=postgresql://postgres:x@127.0.0.1:55434/occtest pytest tests/test_alert_delivery_queue_hygiene_20261109.py
They refuse any DSN naming trade_ai. The pure cases run everywhere.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alert_delivery_queue_hygiene as hyg  # noqa: E402
import alert_outbox  # noqa: E402

DSN = os.getenv("ALERT_TEST_DSN")
MIGRATION = ROOT / "migrations" / "2026_07_28_alert_notification_outbox.sql"
VIEW_FIX = ROOT / "migrations" / "2026_07_29_alert_events_view_last_delivery.sql"


# ---------------------------------------------------------------- pure

def test_consumer_refuses_outside_active_and_never_calls_the_sender():
    calls = []
    for mode in ("SHADOW", "OFF"):
        out = alert_outbox.deliver_immediate(send_func=lambda **kw: calls.append(kw) or {"ok": True}, mode=mode)
        assert out["ok"] is False and out["sent"] == 0
        assert out["refused"] == f"runtime_mode_{mode.lower()}_legacy_owns_delivery"
    assert calls == []


def test_verdict_vocabulary():
    empty = {"shadow": [], "stale": [], "stuck": [], "fresh": []}
    assert hyg.verdict_for({"ids": dict(empty)}) == "OK"
    assert hyg.verdict_for({"ids": {**empty, "fresh": [1]}}) == "OK"
    assert hyg.verdict_for({"ids": {**empty, "shadow": [1]}}) == "DEGRADED"
    assert hyg.verdict_for({"ids": {**empty, "stale": [1]}}) == "DEGRADED"
    assert hyg.verdict_for({"ids": {**empty, "shadow": [1], "stuck": [2]}}) == "BROKEN"


def test_no_database_is_unverifiable_not_a_crash():
    class Dead:
        def cursor(self):
            raise RuntimeError("down")
    out = hyg.run(apply=True, conn=Dead(), escalate=lambda s: pytest.fail("must not escalate without a reading"))
    assert out["verdict"] == "UNVERIFIABLE" and out["expired"] == 0


# ---------------------------------------------------------------- database

def _connect():
    if not DSN:
        pytest.skip("ALERT_TEST_DSN absent; PostgreSQL proof is unmeasured")
    if "trade_ai" in DSN:
        pytest.skip("refusing to run against a DSN naming trade_ai (production)")
    psycopg2 = pytest.importorskip("psycopg2")
    try:
        return psycopg2.connect(DSN)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"no isolated postgres at {DSN} ({type(e).__name__})")


@pytest.fixture()
def conn():
    c = _connect()
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("DROP VIEW IF EXISTS alert_notification_events CASCADE")
        cur.execute(MIGRATION.read_text())
        cur.execute(VIEW_FIX.read_text())
        cur.execute("TRUNCATE alert_notification_deliveries, alert_occurrences, alert_incidents CASCADE")
        # Minimal synthetic stand-in for the escalation path's cooldown read.
        cur.execute("DROP TABLE IF EXISTS alert_events")
        cur.execute("CREATE TABLE alert_events (id serial, alert_type text, source_script text, "
                    "created_at timestamptz DEFAULT now())")
    c.autocommit = False
    yield c
    c.rollback()
    c.close()


def _seed_queued(cur, n, *, mode, age, incident="inc"):
    """Rows in the shape the pre-fix writer left: 'queued', IMMEDIATE, one per occurrence."""
    ids = []
    for i in range(n):
        iid = f"{incident}-{mode}-{i}"
        cur.execute(
            """INSERT INTO alert_incidents (incident_id, dedupe_key, alert_type, source_system, source_producer,
                   status, severity, route_mode, logical_destination, policy_version, environment, synthetic)
               VALUES (%s,%s,'orphaned_stop','t','t','open','critical','IMMEDIATE','CRITICAL_OPERATIONS','t','t',true)""",
            (iid, "dk-" + iid))
        cur.execute(
            """INSERT INTO alert_occurrences (alert_id, incident_id, occurrence_seq, dedupe_key, observed_at,
                   alert_type, source_producer, severity, payload, notify, decision_reason, runtime_mode,
                   route_mode, logical_destination)
               VALUES (%s,%s,1,%s, now() - %s,'orphaned_stop','t','critical','{}'::jsonb,true,'first_occurrence',
                       %s,'IMMEDIATE','CRITICAL_OPERATIONS') RETURNING occurrence_id""",
            ("al-" + iid, iid, "dk-" + iid, age, mode))
        occ = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO alert_notification_deliveries (occurrence_id, alert_id, incident_id, attempt_seq,
                   logical_destination, route_mode, delivery_status, delivery_reason, created_at)
               VALUES (%s,%s,%s,1,'CRITICAL_OPERATIONS','IMMEDIATE','queued','first_occurrence', now() - %s)
               RETURNING id""",
            (occ, "al-" + iid, iid, age))
        ids.append(cur.fetchone()[0])
    return ids


def _statuses(cur):
    cur.execute("SELECT delivery_status, split_part(delivery_reason, '|', 1), count(*) "
                "FROM alert_notification_deliveries GROUP BY 1, 2 ORDER BY 1, 2")
    return cur.fetchall()


def test_shadow_writer_records_a_terminal_row_not_queue_work(conn):
    from alert_occurrence_store import SHADOW_DELIVERY_REASON_PREFIX, record_occurrence
    from alert_routing_resolver import resolve_route
    from operator_alert_policy_v2 import AlertEvent

    ev = AlertEvent(alert_type="orphaned_stop", source_system="test", source_producer="pytest",
                    entity_id="e1", account_id="acct1", symbol="ZZZZ", severity="critical")
    route = resolve_route(ev, mode="ACTIVE", preferences={"general_telegram": "IMMEDIATE",
                                                          "dedupe_window_seconds": 900})
    t0 = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
    shadow = record_occurrence(conn, incident_id="i-s", alert_id="a-s", dedupe_key="FP-S", event=ev, route=route,
                               observed_at=t0, runtime_mode="SHADOW")
    active = record_occurrence(conn, incident_id="i-a", alert_id="a-a", dedupe_key="FP-A", event=ev, route=route,
                               observed_at=t0, runtime_mode="ACTIVE")
    assert shadow["queued"] is False and active["queued"] is True
    with conn.cursor() as cur:
        cur.execute("SELECT alert_id, delivery_status, delivery_reason, completed_at IS NOT NULL "
                    "FROM alert_notification_deliveries ORDER BY alert_id")
        rows = cur.fetchall()
    assert rows == [("a-a", "queued", "first_occurrence", False),
                    ("a-s", "suppressed", SHADOW_DELIVERY_REASON_PREFIX + "first_occurrence", True)]


def test_consumer_claims_only_queued_or_failed_and_closes_the_queued_row(conn, monkeypatch):
    with conn.cursor() as cur:
        [qid] = _seed_queued(cur, 1, mode="ACTIVE", age=timedelta(minutes=1), incident="q")
        _seed_queued(cur, 1, mode="SHADOW", age=timedelta(minutes=1), incident="s")
        cur.execute("UPDATE alert_notification_deliveries SET delivery_status='suppressed' WHERE id <> %s", (qid,))
    conn.commit()
    monkeypatch.setattr(alert_outbox, "_db", lambda: conn)
    pending = alert_outbox.pending_immediate()
    assert [p["alert_id"] for p in pending] == ["al-q-ACTIVE-0"], "a suppressed (shadow) row is never work"
    with conn.cursor() as cur:
        alert_outbox._record_delivery(cur, "al-q-ACTIVE-0", "IMMEDIATE", "CRITICAL_OPERATIONS", "sent", "200", "m")
        cur.execute("SELECT delivery_status, delivery_reason FROM alert_notification_deliveries "
                    "WHERE id = %s", (qid,))
        assert cur.fetchone() == ("abandoned", "superseded_by_attempt")
    assert alert_outbox.pending_immediate() == []


def test_lane_emulated_slot_dry_run_then_apply_expires_and_escalates_once(conn):
    with conn.cursor() as cur:
        _seed_queued(cur, 3, mode="SHADOW", age=timedelta(days=30), incident="sh")
        _seed_queued(cur, 1, mode="ACTIVE", age=timedelta(hours=7), incident="st")
        _seed_queued(cur, 1, mode="ACTIVE", age=timedelta(minutes=25), incident="sk")
        _seed_queued(cur, 1, mode="ACTIVE", age=timedelta(minutes=2), incident="fr")
    conn.commit()

    escalations = []
    dry = hyg.run(apply=False, conn=conn, escalate=lambda s: escalations.append(s) or True)
    assert dry["verdict"] == "BROKEN" and dry["counts"] == {"shadow": 3, "stale": 1, "stuck": 1, "fresh": 1}
    assert dry["expired"] == 0 and escalations == []
    with conn.cursor() as cur:
        assert _statuses(cur) == [("queued", "first_occurrence", 6)], "the dry run wrote nothing"

    live = hyg.run(apply=True, conn=conn, escalate=lambda s: escalations.append(s) or True)
    assert live["expired"] == 4 and live["escalated"] is True and live["sends"] == 0
    with conn.cursor() as cur:
        assert _statuses(cur) == [("abandoned", hyg.REASON_SHADOW, 3), ("abandoned", hyg.REASON_STALE, 1),
                                  ("queued", "first_occurrence", 2)]
        cur.execute("SELECT delivery_reason FROM alert_notification_deliveries WHERE delivery_status='abandoned' "
                    "LIMIT 1")
        assert cur.fetchone()[0].endswith("|was:first_occurrence"), "the original reason is kept"
        cur.execute("INSERT INTO alert_events (alert_type, source_script) VALUES ('system_health', %s)",
                    (hyg.ESCALATION_SOURCE,))
    conn.commit()

    again = hyg.run(apply=True, conn=conn, escalate=lambda s: escalations.append(s) or True)
    assert again["verdict"] == "BROKEN" and again["escalated"] is False and again["escalation_suppressed_cooldown"]
    assert len(escalations) == 1, "one system_health CRITICAL per cooldown, never a flood"


def test_lane_is_ok_on_a_drained_queue(conn):
    out = hyg.run(apply=True, conn=conn, escalate=lambda s: pytest.fail("nothing to escalate"))
    assert out["verdict"] == "OK" and out["expired"] == 0
