"""WS3-21 (2026-10-15): send_telegram returned True when nothing was delivered.

In SHADOW (the live mode) publish_operator_message reports accepted:True for every message, so a send that failed
on every chat, or found no token, still returned True to its ~38 checking callers. The fix keeps the boolean
contract for routed / digested / deduped messages (accepted, no transport attempt) and returns False when a
transport attempt delivered nothing; delivery_outcome() / send_telegram_outcome() give the typed result.

The transport is a stub in every test (and the suite-wide conftest interdict stays underneath it). Nothing is sent."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import telegram_alert as TA  # noqa: E402


@pytest.fixture
def shadow(monkeypatch):
    """SHADOW runtime mode, a configured bot, no shadow persistence, no comms-hub publish, no report capture."""
    import alert_runtime_mode as M

    monkeypatch.setattr(M, "get_mode", lambda **_k: M.MODE_SHADOW)
    monkeypatch.setattr(M, "can_persist_shadow", lambda: False, raising=False)
    monkeypatch.setattr(TA, "_enabled", lambda: True)
    monkeypatch.setattr(TA, "_token", lambda: "test-token")
    monkeypatch.setattr(TA, "_chat_ids", lambda: ["c1"])
    monkeypatch.setattr(TA, "_comms_gateway_owns", lambda _mc: False)
    monkeypatch.setattr(TA, "_best_effort_comms_publish", lambda *a, **k: None)
    try:
        import report_capture

        monkeypatch.setattr(report_capture, "capture", lambda *a, **k: None)
        monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: {"id": 1})
    except ImportError:
        pass
    calls: list[dict] = []

    def ok(**kw):
        calls.append(kw)
        return {"ok": True, "status_code": 200, "message_id": 100 + len(calls)}

    monkeypatch.setattr(TA, "send_message", ok)
    return calls


def test_every_chat_failing_is_false_and_failed(shadow, monkeypatch):
    monkeypatch.setattr(TA, "send_message", lambda **kw: {"ok": False, "status_code": 502})
    assert TA.send_telegram("disk 95%", bypass_router=True) is False
    out = TA.delivery_outcome(False)
    assert out["status"] == "FAILED" and out["delivered"] is False and out["message_ids"] == []


def test_the_pytest_interdict_is_a_failure_not_a_delivery(shadow, monkeypatch):
    monkeypatch.setattr(TA, "send_message", lambda **kw: {"ok": False, "status_code": 0, "interdicted": True})
    out = TA.send_telegram_outcome("x", bypass_router=True)
    assert out == {**out, "status": "FAILED", "delivered": False, "accepted": False}


def test_unconfigured_bot_is_false_and_unconfigured(shadow, monkeypatch):
    monkeypatch.setattr(TA, "_token", lambda: "")
    assert TA.send_telegram("x", bypass_router=True) is False
    assert TA.delivery_outcome(False)["status"] == "UNCONFIGURED"


def test_a_delivery_is_true_with_its_message_id(shadow):
    out = TA.send_telegram_outcome("hello", bypass_router=True)
    assert out["status"] == "DELIVERED" and out["delivered"] and out["accepted"]
    assert out["message_ids"] == ["101"] and out["attempts"] == 1


def test_partial_failure_is_delivered_and_flagged(shadow, monkeypatch):
    monkeypatch.setattr(TA, "_chat_ids", lambda: ["c1", "c2"])
    monkeypatch.setattr(
        TA,
        "send_message",
        lambda chat_id=None, **kw: (
            {"ok": True, "message_id": 7} if chat_id == "c1" else {"ok": False, "status_code": 403}
        ),
    )
    # c1 has it: True, so the caller does not retry and duplicate it there; the outcome flags the failed chat
    assert TA.send_telegram("x", bypass_router=True) is True
    out = TA.delivery_outcome(True)
    assert out["status"] == "DELIVERED" and out["partial_failure"] is True and out["message_ids"] == ["7"]


def test_editor_hold_keeps_the_bool_but_is_not_a_delivery(shadow, monkeypatch):
    monkeypatch.setattr(TA, "send_message", lambda **kw: {"ok": True, "suppressed": "cio_decision_missing"})
    assert TA.send_telegram("x", bypass_router=True) is True  # unchanged: a hold is a decision, not a failure
    out = TA.delivery_outcome(True)
    assert out["status"] == "HELD" and out["delivered"] is False and out["held_chunks"] == 1


def test_router_digest_stays_accepted_and_reports_routed(shadow, monkeypatch):
    import telegram_alert_router as R

    monkeypatch.setattr(R, "should_send_telegram", lambda _m: False)
    monkeypatch.setattr(R, "classify_alert", lambda _m: "P1_DIGEST")
    sent: list = []
    monkeypatch.setattr(TA, "send_message", lambda **kw: sent.append(kw) or {"ok": True, "message_id": 1})
    assert TA.send_telegram("routine digest line") is True  # accepted: the digest owns it; callers must not retry
    out = TA.delivery_outcome(True)
    assert out["status"] == "ROUTED" and out["delivered"] is False and sent == []


def test_attempts_do_not_leak_between_sends(shadow, monkeypatch):
    monkeypatch.setattr(TA, "send_message", lambda **kw: {"ok": False, "status_code": 500})
    assert TA.send_telegram("a", bypass_router=True) is False
    monkeypatch.setattr(TA, "send_message", lambda **kw: {"ok": True, "message_id": 5})
    assert TA.send_telegram("b", bypass_router=True) is True
    assert TA.delivery_outcome(True)["status"] == "DELIVERED"


def test_disabled_telegram_is_false_and_disabled(monkeypatch):
    monkeypatch.setattr(TA, "_enabled", lambda: False)
    assert TA.send_telegram("x", bypass_router=True) is False
    assert TA.delivery_outcome(False)["status"] == "DISABLED"
