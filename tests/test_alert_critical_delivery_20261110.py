"""LQ-20261107-1815 — CRITICAL alerts must actually reach the operator.

ANCHOR: ALERT_CRITICAL_DELIVERY_20261110

Measured BEFORE (2026-11-10, read-only): 676 delivery rows, 0 'sent', 0 with a claimant, 0 with a
telegram_message_id; of the critical IMMEDIATE decisions since 11-07, 55 % were suppressed by the legacy router and
reached nobody, and the delivery row recorded "the legacy sender owns delivery" either way. The queue had a schema
with claim semantics, a producer and a janitor, and no consumer.

These cases pin the fix: the occurrence store queues a critical row only when the legacy send reports it did NOT
deliver; the consumer claims it, sends it through the Telegram chokepoint and records the provider id; the producer
triggers the consumer for the occurrence it just wrote; and the hygiene lane never abandons that row at 10 minutes.

Database cases are not required for any case here — the consumer's DB contract is exercised through a scripted fake
connection, so this file runs in the same default suite as the rest of the alert tests.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alert_delivery_queue_hygiene as hygiene  # noqa: E402
import alert_outbox  # noqa: E402
import alert_occurrence_store as store  # noqa: E402
import telegram_alert  # noqa: E402


# ---------------------------------------------------------------- the ownership rule (pure)

def test_active_immediate_decision_is_always_queued_work():
    row = store.immediate_delivery_row(runtime_mode="ACTIVE", notify=True, route_mode="IMMEDIATE",
                                       suppression_reason=None, severity="critical",
                                       decision_reason="first_occurrence", legacy_delivered=False)
    assert row == {"status": "queued", "reason": "first_occurrence", "queued": True, "handover": False}


def test_shadow_critical_the_legacy_path_did_not_deliver_is_handed_over():
    row = store.immediate_delivery_row(runtime_mode="SHADOW", notify=True, route_mode="IMMEDIATE",
                                       suppression_reason=None, severity="CRITICAL",
                                       decision_reason="first_occurrence", legacy_delivered=False)
    assert row["status"] == "queued" and row["queued"] is True and row["handover"] is True
    assert row["reason"] == store.SHADOW_UNDELIVERED_REASON_PREFIX + "first_occurrence"


def test_shadow_critical_with_no_observed_outcome_is_queued_not_recorded_as_delivered():
    """The safe direction for a critical is one possible duplicate, never a silent loss."""
    row = store.immediate_delivery_row(runtime_mode="SHADOW", notify=True, route_mode="IMMEDIATE",
                                       suppression_reason=None, severity="critical",
                                       decision_reason="first_occurrence", legacy_delivered=None)
    assert row["status"] == "queued" and row["handover"] is True


def test_shadow_critical_the_legacy_path_delivered_stays_terminal():
    row = store.immediate_delivery_row(runtime_mode="SHADOW", notify=True, route_mode="IMMEDIATE",
                                       suppression_reason=None, severity="critical",
                                       decision_reason="first_occurrence", legacy_delivered=True)
    assert row == {"status": "suppressed",
                   "reason": store.SHADOW_DELIVERY_REASON_PREFIX + "first_occurrence",
                   "queued": False, "handover": False}


def test_shadow_non_critical_keeps_the_lq_1607_rule_exactly():
    for delivered in (True, False, None):
        row = store.immediate_delivery_row(runtime_mode="SHADOW", notify=True, route_mode="IMMEDIATE",
                                           suppression_reason=None, severity="warning",
                                           decision_reason="dedupe_window_elapsed", legacy_delivered=delivered)
        assert row["status"] == "suppressed" and row["queued"] is False, "the shadow history is never re-sent"


def test_only_a_notifying_unsuppressed_immediate_decision_writes_a_delivery_row():
    base = dict(runtime_mode="SHADOW", notify=True, route_mode="IMMEDIATE", suppression_reason=None,
                severity="critical", decision_reason="first_occurrence")
    assert store.immediate_delivery_row(**{**base, "notify": False}) is None
    assert store.immediate_delivery_row(**{**base, "route_mode": "DIGEST"}) is None
    assert store.immediate_delivery_row(**{**base, "suppression_reason": "quiet_hours"}) is None


# ---------------------------------------------------------------- the consumer (scripted fake connection)

_COLS = ["id", "occurrence_id", "alert_id", "logical_destination", "attempt_seq", "retry_count",
         "delivery_status", "delivery_reason", "alert_type", "source_producer", "symbol", "severity",
         "payload", "observed_at"]


class _Desc:
    def __init__(self, name):
        self.name = name


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.executed.append(norm)
        self._rows = []
        self.description = None
        if norm.startswith("WITH due"):
            ids = [r["id"] for r in self.conn.table if r["delivery_status"] in ("queued", "failed")]
            self.description = [_Desc("id")]
            self._rows = [(i,) for i in ids]
        elif "WHERE d.id = ANY" in norm:
            wanted = set(params[0])
            self.description = [_Desc(c) for c in _COLS]
            self._rows = [tuple(r.get(c) for c in _COLS) for r in self.conn.table if r["id"] in wanted]
        elif norm.startswith("UPDATE alert_notification_deliveries"):
            status, reason, message_id, _message, _s1, _s2, row_id = params
            for r in self.conn.table:
                if r["id"] == row_id:
                    r["delivery_status"] = status
                    r["delivery_reason"] = reason
                    r["telegram_message_id"] = message_id
            self.rowcount = 1
        elif norm.startswith("SELECT") and "alert_notification_deliveries d" in norm:
            self.description = [_Desc(c) for c in _COLS]
            self._rows = [tuple(r.get(c) for c in _COLS) for r in self.conn.table]
        else:  # pragma: no cover - a query this test does not model is a test defect, not a skip
            raise AssertionError(f"unmodelled SQL: {norm[:80]}")
        return self

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, rows):
        self.table = [dict(r) for r in rows]
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):  # pragma: no cover - only when deliver_critical opens its own
        pass


def _row(**kw):
    base = dict(id=1, occurrence_id=11, alert_id="al-11", logical_destination="CRITICAL_OPERATIONS",
                attempt_seq=1, retry_count=0, delivery_status="queued",
                delivery_reason=store.SHADOW_UNDELIVERED_REASON_PREFIX + "first_occurrence",
                alert_type="orphaned_stop", source_producer="pytest", symbol="ZZZZ", severity="critical",
                payload={"payload": {"alert_type": "orphaned_stop", "source_system": "test",
                                     "source_producer": "pytest", "severity": "critical",
                                     "payload": {"message": "synthetic"}}},
                observed_at=datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc))
    base.update(kw)
    return base


def test_dry_run_claims_and_sends_nothing():
    conn = _Conn([_row()])
    sends = []
    out = alert_outbox.deliver_critical(conn=conn, dry_run=True, send_func=lambda *a: sends.append(a))
    assert out["outcome"] == "dry_run" and out["would_claim"] == 1 and out["sent"] == 0
    assert out["rows"][0]["id"] == 1 and out["rows"][0]["severity"] == "critical"
    assert len(conn.executed) == 1 and conn.executed[0].startswith("SELECT d.id"), "the read, never the claim"
    assert not any(sql.startswith("WITH due") or sql.startswith("UPDATE") for sql in conn.executed)
    assert sends == [] and conn.commits == 0


def test_apply_claims_sends_through_the_injected_sender_and_records_the_receipt():
    conn = _Conn([_row()])
    sent = []

    def send(message, destination):
        sent.append((message, destination))
        return {"status": "sent", "reason": None, "message_id": "9001"}

    out = alert_outbox.deliver_critical(conn=conn, send_func=send)
    assert out["ok"] is True and out["claimed"] == 1 and out["sent"] == 1
    assert out["rows"] == [{"id": 1, "occurrence_id": 11, "alert_id": "al-11", "status": "sent",
                            "reason": None, "telegram_message_id": "9001"}]
    assert sent and "critical alert re-delivered" in sent[0][0], "the operator is told the original was suppressed"
    assert sent[0][1] == "CRITICAL_OPERATIONS"
    assert conn.table[0]["delivery_status"] == "sent" and conn.table[0]["telegram_message_id"] == "9001"
    assert any(sql.startswith("WITH due") for sql in conn.executed)
    assert out["claimed_by"].startswith(alert_outbox.CRITICAL_CLAIM_OWNER_PREFIX + "@")


def test_a_delivered_alert_is_never_sent_twice():
    conn = _Conn([_row(delivery_status="sent", telegram_message_id="9001")])
    calls = []
    out = alert_outbox.deliver_critical(conn=conn, send_func=lambda *a: calls.append(a) or {"status": "sent",
                                                                                           "message_id": "9002"})
    assert out["claimed"] == 0 and calls == []


def test_a_failing_sender_is_a_failed_attempt_not_a_lost_claim():
    conn = _Conn([_row()])

    def boom(message, destination):
        raise ConnectionError("telegram down")

    out = alert_outbox.deliver_critical(conn=conn, send_func=boom)
    assert out["ok"] is False and out["failed"] == 1 and out["sent"] == 0
    assert out["rows"][0]["status"] == "failed" and out["rows"][0]["reason"] == "ConnectionError"
    assert conn.table[0]["delivery_status"] == "failed", "the row stays retryable (retry_count < max)"
    assert conn.table[0]["telegram_message_id"] is None


def test_the_chokepoint_call_is_a_declared_p1_intent_and_reports_the_provider_id(monkeypatch):
    """"Through the working Telegram path": the same chokepoint the legacy sender uses, with an explicit chat id."""
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("-100", "42"))
    seen = {}

    def fake_send(message, bypass_router, **kw):
        seen.update(kw, bypass_router=bypass_router)
        return {"accepted": True, "message_id": "9001", "message_ids": ["9001"]}

    monkeypatch.setattr(telegram_alert, "send_telegram_with_id", fake_send)
    out = alert_outbox._send_critical_default("synthetic", "CRITICAL_OPERATIONS")
    assert out == {"status": "sent", "reason": None, "message_id": "9001"}
    assert seen["chat_ids"] == ["-100"] and seen["thread_id"] == "42"
    assert seen["priority"] == "P1" and seen["dedupe_minutes"] == 0, "a critical is never quiet-held, digested or deduped"
    assert seen["bypass_router"] is False, "the intent router is the gate; bypass_router is not"


def test_an_editor_hold_is_reported_as_suppressed_from_this_calls_outcome(monkeypatch):
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("-100", None))
    monkeypatch.setattr(telegram_alert, "send_telegram_with_id",
                        lambda *a, **k: {"accepted": True, "message_id": None, "message_ids": []})
    monkeypatch.setattr(telegram_alert, "delivery_outcome", lambda accepted: {"status": "HELD"})
    assert alert_outbox._send_critical_default("synthetic", "CRITICAL_OPERATIONS") == {
        "status": "suppressed", "reason": "editor_held", "message_id": None}


def test_a_transport_failure_reports_its_typed_status(monkeypatch):
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("-100", None))
    monkeypatch.setattr(telegram_alert, "send_telegram_with_id",
                        lambda *a, **k: {"accepted": True, "message_id": None, "message_ids": []})
    monkeypatch.setattr(telegram_alert, "delivery_outcome", lambda accepted: {"status": "UNCONFIGURED"})
    assert alert_outbox._send_critical_default("synthetic", "CRITICAL_OPERATIONS")["reason"] == "telegram_unconfigured"


def test_an_unconfigured_destination_fails_loudly_rather_than_silently(monkeypatch):
    # Never reach the network: the channel resolution is the variable under test, and the tester's environment may
    # carry a real chat id. Patching it is what keeps this case safe to run anywhere.
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("", None))
    conn = _Conn([_row(logical_destination="CRITICAL_OPERATIONS")])
    out = alert_outbox.deliver_critical(conn=conn, send_func=alert_outbox._send_critical_default)
    # No TELEGRAM chat id: the consumer must say so, not claim a delivery.
    assert out["rows"][0]["status"] == "failed"
    assert out["rows"][0]["reason"] == "telegram_channel_not_configured"


# ---------------------------------------------------------------- the producer trigger

def test_a_shadow_critical_the_legacy_path_suppressed_triggers_the_consumer(monkeypatch):
    import alert_runtime_mode

    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda *a, **k: "SHADOW")
    monkeypatch.setattr(alert_runtime_mode, "can_persist_shadow", lambda: True)
    seen = {}

    def fake_publish(message, **kw):
        seen.update(kw)
        return {"ok": True, "alert_id": "al-1", "incident_id": "i-1", "occurrence_id": 5,
                "send_immediate": True}

    calls = []
    monkeypatch.setattr(alert_outbox, "publish_legacy_message", fake_publish)
    monkeypatch.setattr(alert_outbox, "deliver_critical",
                        lambda **kw: calls.append(kw) or {"ok": True, "outcome": "applied", "sent": 1})
    monkeypatch.setattr(telegram_alert, "_legacy_send", lambda *a, **k: False)

    out = telegram_alert.publish_operator_message("synthetic critical", bypass_router=True)
    assert seen["legacy_delivered"] is False, "the occurrence store is told what the legacy send OBSERVED"
    assert calls == [{"occurrence_id": 5, "limit": 1}], "the producer drains the row it just wrote"
    assert out["critical_delivery"] == {"ok": True, "outcome": "applied", "sent": 1}
    # The legacy outcome is unchanged for the 182 send_telegram callers.
    assert out["delivered"] is False and out["suppressed"] is True and out["queued"] is False


def test_a_shadow_send_the_legacy_path_delivered_does_not_call_the_consumer(monkeypatch):
    import alert_runtime_mode

    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda *a, **k: "SHADOW")
    monkeypatch.setattr(alert_runtime_mode, "can_persist_shadow", lambda: True)
    seen = {}

    def fake_publish(message, **kw):
        seen.update(kw)
        return {"ok": True, "alert_id": "al-2", "incident_id": "i-2", "occurrence_id": 6,
                "send_immediate": False}

    monkeypatch.setattr(alert_outbox, "publish_legacy_message", fake_publish)

    def never(**kw):
        raise AssertionError("nothing was queued; nothing to drain")

    monkeypatch.setattr(alert_outbox, "deliver_critical", never)
    monkeypatch.setattr(telegram_alert, "_legacy_send", lambda *a, **k: True)

    out = telegram_alert.publish_operator_message("synthetic critical", bypass_router=True)
    assert seen["legacy_delivered"] is True
    assert out["critical_delivery"] is None and out["delivered"] is True


def test_a_delivery_failure_never_breaks_the_legacy_send(monkeypatch):
    import alert_runtime_mode

    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda *a, **k: "SHADOW")
    monkeypatch.setattr(alert_runtime_mode, "can_persist_shadow", lambda: True)
    monkeypatch.setattr(alert_outbox, "publish_legacy_message",
                        lambda message, **kw: {"ok": True, "occurrence_id": 7, "send_immediate": True})

    def boom(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(alert_outbox, "deliver_critical", boom)
    monkeypatch.setattr(telegram_alert, "_legacy_send", lambda *a, **k: False)

    out = telegram_alert.publish_operator_message("synthetic critical", bypass_router=True)
    assert out["critical_delivery"] == {"ok": False, "outcome": "delivery_failed:RuntimeError"}
    assert out["accepted"] is True, "bookkeeping can never fail the alert the caller is sending"


# ---------------------------------------------------------------- the janitor must not erase the new work

def test_hygiene_classifies_undelivered_critical_rows_like_active_work():
    sql = " ".join(hygiene.CLASSIFY_SQL.split())
    undelivered = sql.index(hygiene.UNDELIVERED_PREFIX)
    shadow = sql.index("<> 'ACTIVE'")
    assert undelivered < shadow, ("the reason branch must be tested before the runtime-mode branch, or a SHADOW "
                                  "undelivered row is classed 'shadow' and abandoned at 10 minutes")
    assert hygiene.UNDELIVERED_PREFIX == store.SHADOW_UNDELIVERED_REASON_PREFIX, (
        "producer and janitor must agree on the vocabulary; a typo here silently returns to abandoning the work")


# ---------------------------------------------------------------- the operator-facing plan

def test_the_drain_plan_reports_rows_and_destination_presence_but_no_secret(monkeypatch):
    import alert_critical_drain as drain

    monkeypatch.setattr(alert_outbox, "critical_due", lambda **kw: [_row()])
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("-1001234567890", "42"))
    out = drain.plan(limit=5, min_age_s=0)
    assert out["would_claim"] == 1 and out["sends"] == 0
    assert out["destinations"] == {"CRITICAL_OPERATIONS": {"chat_configured": True}}
    assert out["rows"][0]["undelivered_reason"].startswith(store.SHADOW_UNDELIVERED_REASON_PREFIX)
    assert "-1001234567890" not in repr(out), "the dry run never prints a chat id or a token"
