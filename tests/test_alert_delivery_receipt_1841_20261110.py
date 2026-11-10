"""ANCHOR: ALERT_DELIVERY_RECEIPT_1841_20261110 — the sender writes its outcome against the occurrence.

LQ-20261107-1841 (C1). Measured 2026-11-10 by ``scripts/alert_delivery_chain_probe.py``: 124 of 138 critical
occurrences were ``receipt_unobservable:legacy_delivery_unreported`` because the normalized plane handed delivery to
the legacy sender (``shadow_legacy_owns_delivery:<reason>``) and that sender recorded no result anywhere the chain
can read. The alert may well have arrived; the system could not say so.

This file pins the writer half and the reader half, and that they agree:

  * ``alert_occurrence_store.immediate_delivery_row`` — delivered-with-id stores the id, delivered-without-id stays
    None, a proven failure names the failure (``legacy_send_failed:``) instead of claiming "the legacy sender owns
    delivery", and the critical handover is unchanged.
  * ``alert_outbox.publish_legacy_message`` / ``publish_event`` — the id reaches ``record_occurrence``, which writes
    it on ``alert_notification_deliveries.telegram_message_id``.
  * ``telegram_alert.publish_operator_message`` — the id comes from the send this call just made, never from a
    previous one, and is never attached to a failed send.
  * ``alert_delivery_chain_probe._legacy_claim`` — a delivery-row id is a receipt (the same evidence class the
    ``sent`` branch already accepted), while a bare ``legacy_delivered: true`` flag stays a self-report.

Synthetic fixtures only (the repo is public), every sender stubbed, no database, no network, no alert sent.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alert_delivery_chain_probe as probe  # noqa: E402
import alert_occurrence_store as store  # noqa: E402

NOW = datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc)
T0 = NOW - timedelta(minutes=30)
REASON = "first_occurrence"


def _row(**kw):
    base = {"runtime_mode": "SHADOW", "notify": True, "route_mode": "IMMEDIATE", "suppression_reason": None,
            "severity": "critical", "decision_reason": REASON, "legacy_delivered": True, "legacy_message_id": None,
            "legacy": None}
    base.update(kw)
    return store.immediate_delivery_row(**{k: v for k, v in base.items() if k != "legacy"})


# ── the delivery row: what the sender observed ───────────────────────────────


def test_a_delivered_send_stores_its_provider_message_id():
    r = _row(legacy_delivered=True, legacy_message_id="67095,67096")
    assert r["status"] == "suppressed"
    assert r["reason"] == f"shadow_legacy_owns_delivery:{REASON}"
    assert r["telegram_message_id"] == "67095,67096", "the receipt the chain needs"
    assert r["queued"] is False


def test_a_delivered_send_without_an_id_stays_none():
    """A held chunk or a caller outside the transport: the truth is 'no id', never an invented one."""
    r = _row(legacy_delivered=True, legacy_message_id=None)
    assert r["telegram_message_id"] is None
    assert r["status"] == "suppressed"


def test_a_proven_failure_names_the_failure_not_the_owner():
    """Before this, a non-critical failed send recorded 'the legacy sender owns delivery' — about a message nobody got."""
    r = _row(severity="urgent", legacy_delivered=False)
    assert r["status"] == "suppressed"
    assert r["reason"] == f"legacy_send_failed:{REASON}"
    assert r["reason"] != f"shadow_legacy_owns_delivery:{REASON}"
    assert r["telegram_message_id"] is None


def test_a_critical_failure_is_still_handed_over_as_work():
    r = _row(severity="critical", legacy_delivered=False)
    assert (r["status"], r["queued"], r["handover"]) == ("queued", True, True)
    assert r["reason"] == f"shadow_legacy_undelivered:{REASON}"
    assert r["telegram_message_id"] is None, "a queued row has no send yet; the consumer writes the id"


def test_an_unobserved_critical_is_queued_never_assumed_delivered():
    r = _row(severity="critical", legacy_delivered=None, legacy_message_id="999")
    assert (r["status"], r["queued"]) == ("queued", True)
    assert r["telegram_message_id"] is None, "an id cannot ride a row for a send nobody observed"


def test_an_unobserved_non_critical_keeps_the_old_terminal_row():
    r = _row(severity="urgent", legacy_delivered=None)
    assert (r["status"], r["reason"]) == ("suppressed", f"shadow_legacy_owns_delivery:{REASON}")


def test_active_mode_queues_and_stores_no_legacy_id():
    r = _row(runtime_mode="ACTIVE", legacy_delivered=True, legacy_message_id="67095")
    assert (r["status"], r["queued"]) == ("queued", True)
    assert r["telegram_message_id"] is None


def test_a_non_notifying_decision_writes_no_row():
    assert _row(notify=False) is None
    assert _row(route_mode="DIGEST") is None
    assert _row(suppression_reason="duplicate_within_dedupe_window") is None


# ── record_occurrence writes the id on the delivery row ──────────────────────


class _Cur:
    """A cursor answering the four statements record_occurrence runs with prior state stubbed out, in order.

    No database is contacted. Order: INSERT alert_incidents (new incident), INSERT alert_occurrences,
    UPDATE alert_incidents, INSERT alert_notification_deliveries.
    """

    def __init__(self):
        self.statements = []
        self.description = None
        self._next = None
        self.summaries = [("inc_synthetic",), (42,), None, (7,)]

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self._next = self.summaries[len(self.statements) - 1]

    def fetchone(self):
        return self._next

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Conn:
    def __init__(self):
        self.cur = _Cur()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def _record(monkeypatch, severity="critical", **kw):
    monkeypatch.setattr(store, "load_prior_state", lambda *a, **k: (None, None))
    monkeypatch.setattr(store, "should_notify", lambda *a, **k: _Decision())
    conn = _Conn()
    out = store.record_occurrence(
        conn, incident_id="inc_synthetic", alert_id="al_synthetic", dedupe_key="dk",
        event=_Event(severity), route=_Route(), observed_at=T0, runtime_mode="SHADOW", **kw)
    return conn, out


class _Decision:
    """Just enough of alert_dedupe.Decision for record_occurrence: notify, a reason, no escalation."""

    notify = True
    reason = REASON
    occurrence_seq = 1
    is_escalation = False
    is_resolution = False
    suppressed_until = None

    def as_dict(self):
        return {"notify": True, "reason": REASON}


class _Event:
    alert_type = "emergency_kill_or_revoke"
    source_system = "synthetic"
    source_producer = "test"
    account_id = None
    symbol = "SPCX"
    operator_action_required = True
    operator_action_type = "review"
    state_version = "1"
    payload = {"message": "synthetic alert body"}
    created_at = T0

    def __init__(self, severity="critical"):
        self.severity = severity


class _Route:
    route_mode = "IMMEDIATE"
    logical_destination = "operator"
    digest_bucket = None
    suppression_reason = None
    policy_version = "v-test"
    dedupe_window_seconds = 900
    escalate_after_seconds = 3600
    ttl_seconds = 86400


def test_record_occurrence_writes_the_receipt_on_the_delivery_row(monkeypatch):
    conn, out = _record(monkeypatch, legacy_delivered=True, legacy_message_id="67095,67096")
    insert = [s for s in conn.cur.statements if "INSERT INTO alert_notification_deliveries" in s[0]]
    assert len(insert) == 1
    assert "telegram_message_id" in insert[0][0], "the column must be in the statement, not only in the params"
    assert "67095,67096" in insert[0][1], "the provider id reaches the row"
    assert out["delivery_id"] == 7 and conn.committed


def test_record_occurrence_writes_the_failure_reason_and_no_id(monkeypatch):
    conn, _ = _record(monkeypatch, severity="urgent", legacy_delivered=False)
    sql, params = [s for s in conn.cur.statements if "INSERT INTO alert_notification_deliveries" in s[0]][0]
    assert any(str(p).startswith("legacy_send_failed:") for p in params if p is not None)
    assert not any(str(p) == "67095" for p in params if p is not None)


# ── alert_outbox threads the id to the occurrence store ──────────────────────


def test_publish_legacy_message_carries_the_id_both_ways(monkeypatch):
    import alert_outbox as outbox

    seen = {}

    def _capture(event, **kw):
        seen["payload"] = dict(event.payload)
        seen.update(kw)
        return {"ok": True}

    monkeypatch.setattr(outbox, "publish_event", _capture)
    outbox.publish_legacy_message("synthetic body", legacy_delivered=True, legacy_message_id="67095")
    assert seen["legacy_message_id"] == "67095"
    assert seen["payload"]["legacy_message_id"] == "67095"
    assert seen["payload"]["legacy_delivered"] is True


def test_publish_legacy_message_without_an_id_keeps_the_old_call_shape(monkeypatch):
    import alert_outbox as outbox

    seen = {}

    def _capture(event, **kw):
        seen["payload"] = dict(event.payload)
        seen.update(kw)
        return {"ok": True}

    monkeypatch.setattr(outbox, "publish_event", _capture)
    outbox.publish_legacy_message("synthetic body")
    assert "legacy_message_id" not in seen, "a caller that observed nothing must not gain the kwarg"
    assert "legacy_message_id" not in seen["payload"]
    assert seen == {"payload": seen["payload"], "resolving": False}, "the pre-1841 call shape, unchanged"


# ── the sender: this call's id, never the previous one ──────────────────────


def _sender(monkeypatch, *, delivered, ids, mode="SHADOW"):
    import alert_runtime_mode
    import telegram_alert as ta

    seen = {}
    monkeypatch.setattr(ta, "get_mode", lambda: mode, raising=False)
    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda: mode, raising=True)
    monkeypatch.setattr(ta, "_legacy_send", lambda *a, **k: delivered, raising=True)
    monkeypatch.setattr(ta, "last_message_ids", lambda: list(ids), raising=True)
    monkeypatch.setattr(alert_runtime_mode, "can_persist_shadow", lambda: True, raising=True)

    import alert_outbox
    monkeypatch.setattr(alert_outbox, "publish_legacy_message",
                        lambda message, **kw: seen.update(kw) or {"persisted": True,
                                                                 "alert_id": "al", "incident_id": "inc"},)
    monkeypatch.setattr(ta, "_drain_critical_if_queued", lambda shadow: (None, None), raising=True)
    ta.publish_operator_message("synthetic body")
    return seen


def test_publish_operator_message_passes_the_id_of_the_send_it_just_made(monkeypatch):
    seen = _sender(monkeypatch, delivered=True, ids=["67095", "67096"])
    assert seen["legacy_message_id"] == "67095,67096"
    assert seen["legacy_delivered"] is True


def test_publish_operator_message_never_attaches_an_id_to_a_failed_send(monkeypatch):
    seen = _sender(monkeypatch, delivered=False, ids=["66001"])
    assert seen["legacy_message_id"] is None, "a stale ambient id must not become this alert's receipt"
    assert seen["legacy_delivered"] is False


def test_publish_operator_message_omits_the_id_when_the_send_returned_none(monkeypatch):
    seen = _sender(monkeypatch, delivered=True, ids=[])
    assert seen["legacy_message_id"] is None


# ── the reader: the probe accepts the row this writer produces ───────────────

OCC = {"occurrence_id": 1, "alert_id": "al_synthetic", "incident_id": "inc_synthetic", "recorded_at": T0,
       "severity": "critical", "alert_type": "emergency_kill_or_revoke", "route_mode": "IMMEDIATE",
       "notify": True, "decision_reason": REASON, "intent_priority": "P1", "legacy_delivered": True,
       "delivery_id": 10, "delivery_status": "suppressed", "delivery_reason": None, "delivery_msg_id": None,
       "delivery_created_at": T0, "delivery_completed_at": T0, "delivery_retry_count": 0,
       "digest_queued_at": None, "digest_claimed_at": None, "digest_included_at": None,
       "provider_message_id": None, "provider_settlement_state": None, "provider_settled_at": None,
       "event_ack_at": None}


def test_the_probe_counts_the_written_receipt_as_received():
    row = dict(OCC, delivery_reason=f"shadow_legacy_owns_delivery:{REASON}", delivery_msg_id="67095,67096")
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["receipt"], c["evidence"]) == ("received", "67095,67096", "delivery_row")
    assert c["delivered_at"] == c["received_at"]


def test_a_self_report_without_an_id_is_still_not_a_receipt():
    row = dict(OCC, delivery_reason=f"shadow_legacy_owns_delivery:{REASON}", delivery_msg_id=None)
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"]) == ("delivered", "receipt_unobservable:legacy_self_report")


def test_the_probe_counts_the_written_failure_as_proven_undelivered():
    row = dict(OCC, severity="urgent", legacy_delivered=False,
               delivery_reason=f"legacy_send_failed:{REASON}")
    c = probe.classify(row, now=NOW)
    assert c["stage"] == "queued" and c["defect"].startswith("not_delivered")


def test_an_unknown_outcome_is_still_not_observable():
    row = dict(OCC, legacy_delivered=None, delivery_reason=f"shadow_legacy_owns_delivery:{REASON}")
    c = probe.classify(row, now=NOW)
    assert c["stage"] == "queued"
    assert c["defect"] == "receipt_unobservable:legacy_delivery_unreported"
