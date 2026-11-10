"""LQ-20261107-1815 r2 — the review's MUST-FIX items on the critical-alert consumer.

ANCHOR: ALERT_CRITICAL_DELIVERY_R2_20261110

Independent review (REVIEW-LQ1824-466443620, verdict CHANGES) found five must-fix defects in `466443620`:

  M1  the handover carried none of the alert's own text and said "No immediate action" for a critical;
  M2  an editor-held critical was written terminal `suppressed` and reported `ok=True`;
  M3  failed / exhausted / orphaned-claim / held rows were invisible to the hygiene lane;
  M4  nothing retried a failed handover;
  M5  a RETURNED handover failure printed nothing.

Plus S1 (one payload built outside the per-row guard aborted the batch), S2 (two attempt rows for one occurrence
were both sent) and S6 (the ACTIVE path never drained).

Every case here is synthetic: a scripted connection and an injected sender. No DB, no network, no Telegram token.
Each case fails against `466443620` and passes against the r2 tree.
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

_NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)

_COLS = ["id", "occurrence_id", "alert_id", "logical_destination", "attempt_seq", "retry_count",
         "delivery_status", "delivery_reason", "alert_type", "source_producer", "symbol", "severity",
         "operator_action_required", "payload", "observed_at"]


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
        if norm.startswith("WITH candidates"):
            # One row per occurrence (DISTINCT ON), never an occurrence already delivered, never out of attempts.
            sent_occ = {r["occurrence_id"] for r in self.conn.table if r["delivery_status"] == "sent"}
            picked: dict = {}
            for r in self.conn.table:
                if r["occurrence_id"] in sent_occ or r["retry_count"] >= alert_outbox.CRITICAL_MAX_ATTEMPTS:
                    continue
                if r["delivery_status"] in ("queued", "failed") or (
                        r["delivery_status"] == "claimed" and r.get("claimed_expired")):
                    picked.setdefault(r["occurrence_id"], r["id"])
            self.description = [_Desc("id")]
            self._rows = [(i,) for i in picked.values()]
        elif norm.startswith("SELECT 1 FROM alert_notification_deliveries"):
            hit = any(r["occurrence_id"] == params[0] and r["delivery_status"] == "sent" for r in self.conn.table)
            self.description = [_Desc("?column?")]
            self._rows = [(1,)] if hit else []
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
                    if status == "failed":
                        r["retry_count"] += 1
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
        self.executed: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):  # pragma: no cover
        pass


def _row(**kw):
    """The PRODUCTION shape: identity in the columns, the operator body in the occurrence's inner payload."""
    base = dict(id=1, occurrence_id=11, alert_id="al-11", logical_destination="CRITICAL_OPERATIONS",
                attempt_seq=1, retry_count=0, delivery_status="queued",
                delivery_reason=store.SHADOW_UNDELIVERED_REASON_PREFIX + "first_occurrence",
                alert_type="orphaned_stop", source_producer="pytest", symbol="ZZZZ", severity="critical",
                operator_action_required=True,
                payload={"bypass_router_requested": True, "intent_priority": "P1",
                         "message": "synthetic emergency kill"},
                observed_at=_NOW)
    base.update(kw)
    return base


def _sent_sender(record):
    def send(message, destination):
        record.append((message, destination))
        return {"status": "sent", "reason": None, "message_id": "9001"}
    return send


# ---------------------------------------------------------------- M1: the operator gets the alert's own text

def test_m1_handover_carries_the_alerts_text_symbol_and_an_action_line():
    message = alert_outbox._handover_message(_row(operator_action_required=False))
    assert "synthetic emergency kill" in message, "the alert's own body must reach the operator"
    assert "ZZZZ" in message, "the symbol was selected and never used"
    assert "Action required" in message
    assert "No immediate action" not in message, "a critical handover is never 'no immediate action'"


def test_m1_the_handover_marks_the_handover_and_keeps_the_body():
    message = alert_outbox._handover_message(_row())
    assert message.startswith(alert_outbox.HANDOVER_MARK)
    assert "synthetic emergency kill" in message


def test_m1_a_critical_with_no_stored_body_says_so_instead_of_rendering_empty():
    message = alert_outbox._handover_message(_row(payload={"bypass_router_requested": True}))
    assert alert_outbox.HANDOVER_NO_BODY in message
    assert "No immediate action" not in message


def test_s1_a_malformed_nested_payload_cannot_abort_the_batch():
    """One bad payload used to raise TypeError out of ``deliver_critical`` before the per-row guard, leaving every
    claimed row 'claimed' and the rest of the batch unsent."""
    bad = _row(id=1, occurrence_id=11, payload={"payload": {"alert_type": "orphaned_stop"}})
    good = _row(id=2, occurrence_id=12, alert_id="al-12")
    conn = _Conn([bad, good])
    sent: list = []
    out = alert_outbox.deliver_critical(conn=conn, send_func=_sent_sender(sent))
    assert out["claimed"] == 2 and out["sent"] == 2, "both rows are attempted"
    assert len(sent) == 2
    assert "synthetic emergency kill" in sent[1][0]


# ---------------------------------------------------------------- M2: a hold is not a delivery and not success

def test_m2_a_held_critical_is_failed_and_the_report_is_not_ok():
    conn = _Conn([_row()])
    out = alert_outbox.deliver_critical(conn=conn, send_func=lambda m, d: {"status": "failed",
                                                                         "reason": "editor_held",
                                                                         "message_id": None})
    assert out["ok"] is False
    assert conn.table[0]["delivery_status"] == "failed" and conn.table[0]["retry_count"] == 1
    assert out["rows"][0]["reason"] == "editor_held"


def test_m2_the_chokepoint_maps_an_editor_hold_to_a_retryable_failure(monkeypatch):
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("-100", None))
    monkeypatch.setattr(telegram_alert, "send_telegram_with_id",
                        lambda *a, **k: {"accepted": True, "message_id": None, "message_ids": []})
    monkeypatch.setattr(telegram_alert, "delivery_outcome", lambda accepted: {"status": "HELD"})
    assert alert_outbox._send_critical_default("synthetic", "CRITICAL_OPERATIONS")["status"] == "failed"


def test_m2_a_suppressed_row_is_never_counted_as_success():
    conn = _Conn([_row()])
    out = alert_outbox.deliver_critical(conn=conn, send_func=lambda m, d: {"status": "suppressed",
                                                                         "reason": "injected",
                                                                         "message_id": None})
    assert out["ok"] is False and out["suppressed"] == 1


# ---------------------------------------------------------------- S2: one occurrence, one send

def test_s2_two_attempt_rows_for_one_occurrence_are_sent_once():
    conn = _Conn([_row(id=1, occurrence_id=11, attempt_seq=1),
                  _row(id=2, occurrence_id=11, attempt_seq=2)])
    sent: list = []
    out = alert_outbox.deliver_critical(conn=conn, send_func=_sent_sender(sent))
    assert out["claimed"] == 1 and len(sent) == 1, "one Telegram message per occurrence, always"


def test_s2_a_row_already_delivered_after_the_claim_is_closed_without_sending(monkeypatch):
    conn = _Conn([_row()])
    sent: list = []
    monkeypatch.setattr(alert_outbox, "_occurrence_already_sent", lambda c, occ: True)
    out = alert_outbox.deliver_critical(conn=conn, send_func=_sent_sender(sent))
    assert sent == [], "no second message for an occurrence someone already delivered"
    assert conn.table[0]["delivery_status"] == "abandoned"
    assert conn.table[0]["delivery_reason"] == alert_outbox.REASON_ALREADY_SENT
    assert out["duplicates_skipped"] == 1 and out["ok"] is True, "a duplicate is not a failure"


# ---------------------------------------------------------------- M4 / M5: retries and the visible failure

def test_m4_the_retry_sweep_is_bounded_and_never_reattempts_the_row_it_just_tried():
    assert telegram_alert.CRITICAL_RETRY_MIN_AGE_S > 0
    assert 0 < telegram_alert.CRITICAL_RETRY_SWEEP_LIMIT <= 10
    calls: list = []

    def fake_publish(message, **kw):
        return {"ok": True, "alert_id": "al-1", "incident_id": "i-1", "occurrence_id": 5, "send_immediate": True}

    import alert_runtime_mode
    original = (alert_runtime_mode.get_mode, alert_runtime_mode.can_persist_shadow)
    alert_runtime_mode.get_mode = lambda *a, **k: "SHADOW"
    alert_runtime_mode.can_persist_shadow = lambda: True
    saved = (alert_outbox.publish_legacy_message, alert_outbox.deliver_critical, telegram_alert._legacy_send)
    alert_outbox.publish_legacy_message = fake_publish
    alert_outbox.deliver_critical = lambda **kw: calls.append(kw) or {"ok": True, "sent": 1}
    telegram_alert._legacy_send = lambda *a, **k: False
    try:
        telegram_alert.publish_operator_message("synthetic critical", bypass_router=True)
    finally:
        alert_runtime_mode.get_mode, alert_runtime_mode.can_persist_shadow = original
        alert_outbox.publish_legacy_message, alert_outbox.deliver_critical, telegram_alert._legacy_send = saved
    assert calls[0] == {"occurrence_id": 5, "limit": 1}
    assert calls[1] == {"min_age_s": telegram_alert.CRITICAL_RETRY_MIN_AGE_S,
                        "limit": telegram_alert.CRITICAL_RETRY_SWEEP_LIMIT}


def test_m5_a_returned_handover_failure_is_printed(monkeypatch, capsys):
    import alert_runtime_mode
    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda *a, **k: "SHADOW")
    monkeypatch.setattr(alert_runtime_mode, "can_persist_shadow", lambda: True)
    monkeypatch.setattr(alert_outbox, "publish_legacy_message",
                        lambda message, **kw: {"ok": True, "alert_id": "al-1", "occurrence_id": 5,
                                               "send_immediate": True})
    monkeypatch.setattr(alert_outbox, "deliver_critical",
                        lambda **kw: {"ok": False, "claimed": 1, "failed": 1, "outcome": "applied",
                                      "rows": [{"status": "failed", "reason": "editor_held"}]})
    monkeypatch.setattr(telegram_alert, "_legacy_send", lambda *a, **k: False)
    telegram_alert.publish_operator_message("synthetic critical", bypass_router=True)
    err = capsys.readouterr().out
    assert "did NOT reach the operator" in err
    assert "editor_held" in err


# ---------------------------------------------------------------- S5: a gateway-owned class is named, never faked

def test_s5_a_gateway_owned_class_cannot_be_reported_as_a_delivery(monkeypatch):
    """If `ops` ever becomes gateway-owned, send_telegram takes the gateway branch before the explicit chat_ids
    branch: the handover may land somewhere else and return no message id. The row must stay FAILED (retryable) and
    say why, never claim a receipt it does not have."""
    monkeypatch.setattr(alert_outbox, "resolve_channel_secret", lambda dest: ("-100", None))
    monkeypatch.setattr(telegram_alert, "send_telegram_with_id",
                        lambda *a, **k: {"accepted": True, "message_id": None, "message_ids": []})
    monkeypatch.setattr(telegram_alert, "delivery_outcome", lambda accepted: {"status": "UNCONFIGURED"})
    monkeypatch.setattr(telegram_alert, "_comms_gateway_owns", lambda cls: True)
    out = alert_outbox._send_critical_default("synthetic", "CRITICAL_OPERATIONS")
    assert out["status"] == "failed" and out["message_id"] is None
    assert out["reason"] == "telegram_unconfigured_gateway_owned"


# ---------------------------------------------------------------- S6: ACTIVE drains too

def test_s6_active_mode_drains_the_critical_it_queued(monkeypatch):
    import alert_runtime_mode
    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda *a, **k: "ACTIVE")
    monkeypatch.setattr(alert_runtime_mode, "require_active_capability", lambda *a, **k: None)
    monkeypatch.setattr(alert_outbox, "publish_legacy_message",
                        lambda message, **kw: {"ok": True, "alert_id": "al-9", "occurrence_id": 9,
                                               "send_immediate": True})
    calls: list = []
    monkeypatch.setattr(alert_outbox, "deliver_critical",
                        lambda **kw: calls.append(kw) or {"ok": True, "sent": 1})
    out = telegram_alert.publish_operator_message("synthetic critical", bypass_router=True)
    assert calls and calls[0] == {"occurrence_id": 9, "limit": 1}, "ACTIVE queues every immediate row; it must drain"
    assert out["critical_delivery"] == {"ok": True, "sent": 1}


# ---------------------------------------------------------------- M3: the lane sees the consumer's states

def test_m3_the_lane_classifies_failed_claimed_and_held_rows():
    sql = " ".join(hygiene.CLASSIFY_SQL.split())
    for frag in ("delivery_status = 'failed'", "delivery_status = 'claimed'", "delivery_status = 'suppressed'"):
        assert frag in sql
    for klass in ("exhausted", "retrying", "orphaned_claim", "held"):
        assert f"'{klass}'" in sql
    assert "d.delivery_status = 'queued' AND" not in sql, "the old queued-only filter is the defect itself"


def test_m3_the_lane_mirrors_the_consumers_own_bounds():
    assert hygiene.CONSUMER_MAX_ATTEMPTS == alert_outbox.CRITICAL_MAX_ATTEMPTS
    assert hygiene.CONSUMER_CLAIM_TTL_MIN == alert_outbox.CRITICAL_CLAIM_TTL_MIN


def test_m3_every_consumer_failure_state_is_broken_and_retrying_is_not():
    rows = [("1", "exhausted", "CRITICAL_OPERATIONS", _NOW)]
    assert hygiene.verdict_for(hygiene.classify(rows)) == "BROKEN"
    rows = [("1", "orphaned_claim", "CRITICAL_OPERATIONS", _NOW)]
    assert hygiene.verdict_for(hygiene.classify(rows)) == "BROKEN"
    rows = [("1", "held", "CRITICAL_OPERATIONS", _NOW)]
    assert hygiene.verdict_for(hygiene.classify(rows)) == "BROKEN"
    rows = [("1", "retrying", "CRITICAL_OPERATIONS", _NOW)]
    assert hygiene.verdict_for(hygiene.classify(rows)) == "OK", "a row with attempts left is normal, not a verdict"


def test_m3_the_escalation_names_every_broken_class(monkeypatch):
    captured: dict = {}

    class _Writer:
        @staticmethod
        def save_alert_event(**kw):
            captured.update(kw)
            return object()

    import types
    module = types.ModuleType("alert_event_writer")
    module.save_alert_event = _Writer.save_alert_event
    monkeypatch.setitem(sys.modules, "alert_event_writer", module)

    summary = {"counts": {"stuck": 0, "exhausted": 2, "orphaned_claim": 1, "held": 0, "retrying": 1,
                          "shadow": 0, "stale": 0, "fresh": 0},
               "oldest": {"exhausted": _NOW.isoformat(), "orphaned_claim": _NOW.isoformat()},
               "by_destination": {"CRITICAL_OPERATIONS": 3}}
    assert hygiene._escalate_default(summary) is True
    assert captured["alert_type"] == "system_health" and captured["severity"] == "critical"
    assert "exhausted=2" in captured["raw_text"] and "orphaned_claim=1" in captured["raw_text"]
    assert captured["parsed_payload"]["broken_classes"] == ["exhausted", "orphaned_claim"]


def test_m3_the_lane_still_never_expires_a_failed_claimed_or_held_row():
    sql = " ".join(hygiene.EXPIRE_SQL.split())
    assert "delivery_status = 'queued'" in sql
    assert "failed" not in sql and "claimed" not in sql and "suppressed" not in sql


# ---------------------------------------------------------------- S3: documentation drift

def test_s3_the_shadow_contract_documents_the_handover():
    mode_src = (ROOT / "scripts" / "alert_runtime_mode.py").read_text()
    yaml_src = (ROOT / "config" / "operator_alert_policy.yaml").read_text()
    assert "never used for sending" not in mode_src
    assert "SHADOW legacy delivery unchanged" not in yaml_src
    assert "deliver_critical" in mode_src
    assert "handed over" in yaml_src
