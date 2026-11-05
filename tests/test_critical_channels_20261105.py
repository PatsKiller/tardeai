"""FQ-143: one CRITICAL event fans out to three channels, and a dead channel never eats the event.

No address, token or number appears here — the repository is public and HOUSE RULE E puts the real ones in the private
contact file. Senders are injected, so nothing leaves the process.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import critical_channels as cc  # noqa: E402
from scripts.lib import critical_delivery as cd  # noqa: E402

CLASS = "B2_stop_cancelled_expired_rejected"


def contact():
    return {
        "schema": "OperatorContact@v1",
        "critical_email_to": "operator@example.invalid",
        "critical_sms_email_gateways": [{"address": "gateway-one@example.invalid", "label": "line one", "verified": True}],
        "critical_sms_email_gateway": "gateway-one@example.invalid",
    }


def policy(enabled: bool = True):
    return {"schema": "CriticalTextClasses@v1", "classes": {CLASS: {"enabled": enabled}}}


EVENT = {"alert_class": CLASS, "what": "SPCX stop rejected by the broker", "symbol": "SPCX",
         "action": "Re-place the stop"}


def run(monkeypatch, **kwargs):
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    calls = {"email": [], "telegram": [], "text": []}

    def email(to, subject, body):
        calls["email"].append((to, subject, body))
        return "smtp-ok"

    def telegram(chat, text):
        calls["telegram"].append((chat, text))
        return "tg-42"

    def text(event):
        calls["text"].append(event)
        return {"sent": True}

    delivery = cc.deliver(EVENT, contact=kwargs.pop("contact", contact()),
                          policy=kwargs.pop("policy", policy()),
                          email_sender=kwargs.pop("email_sender", email),
                          telegram_sender=kwargs.pop("telegram_sender", telegram),
                          text_sender=kwargs.pop("text_sender", text), **kwargs)
    return delivery, calls


def test_one_event_reaches_all_three_channels(monkeypatch):
    delivery, calls = run(monkeypatch)
    assert [r.channel for r in delivery.receipts] == ["telegram_critical", "email", "text_gateway"]
    assert all(r.status == "sent" for r in delivery.receipts), [r.as_dict() for r in delivery.receipts]
    assert delivery.delivered is True
    assert len(calls["email"]) == 1 and len(calls["telegram"]) == 1 and len(calls["text"]) == 1


def test_the_email_subject_starts_with_the_prefix_and_the_first_line_is_the_what(monkeypatch):
    _delivery, calls = run(monkeypatch)
    to, subject, body = calls["email"][0]
    assert subject.startswith("CRITICAL —") and subject.endswith("SPCX stop rejected by the broker")
    assert body.startswith("SPCX stop rejected by the broker")


def test_a_failed_email_does_not_stop_telegram_or_the_text(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("smtp refused")

    delivery, calls = run(monkeypatch, email_sender=boom)
    by = {r.channel: r for r in delivery.receipts}
    assert by["email"].status == "failed" and by["email"].reason == "RuntimeError"
    assert by["telegram_critical"].status == "sent"
    assert by["text_gateway"].status == "sent"
    assert delivery.delivered is True


def test_a_disabled_class_never_touches_the_text_channel(monkeypatch):
    delivery, calls = run(monkeypatch, policy=policy(enabled=False))
    by = {r.channel: r for r in delivery.receipts}
    assert by["text_gateway"].status == "skipped"
    assert by["text_gateway"].reason == "class_not_enabled_for_text"
    assert calls["text"] == []
    # the other two still carried it — a class the operator turned off is not an event they should miss
    assert by["email"].status == "sent" and by["telegram_critical"].status == "sent"


def test_a_class_outside_the_allowlist_is_refused_before_anything_is_sent(monkeypatch):
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    sent = []
    with pytest.raises(cd.CriticalDeliveryRefused):
        cc.deliver({"alert_class": "digest", "what": "x"}, contact=contact(), policy=policy(),
                   email_sender=lambda *a: sent.append(a), telegram_sender=lambda *a: sent.append(a),
                   text_sender=lambda e: sent.append(e))
    assert sent == []


def test_a_missing_chat_and_a_missing_email_are_receipts_not_exceptions(monkeypatch):
    monkeypatch.delenv(cd.CRITICAL_CHAT_ENV, raising=False)
    doc = contact()
    doc.pop("critical_email_to")
    delivery = cc.deliver(EVENT, contact=doc, policy=policy(), text_sender=lambda e: {"sent": False, "reason": "capped"})
    by = {r.channel: r for r in delivery.receipts}
    assert by["telegram_critical"].status == "skipped" and by["telegram_critical"].reason == "critical_chat_not_configured"
    assert by["email"].status == "skipped" and by["email"].reason == "critical_email_not_configured"
    assert by["text_gateway"].status == "skipped" and by["text_gateway"].reason == "capped"
    assert delivery.delivered is False


def test_no_receipt_carries_an_address(monkeypatch):
    delivery, _calls = run(monkeypatch)
    blob = repr(delivery.as_dict())
    assert "example.invalid" not in blob and "@" not in blob


# ── the default senders: the tests above inject senders, which is exactly why two broken signatures shipped once ─────────

def test_the_default_telegram_sender_passes_the_token_by_keyword(monkeypatch):
    """`telegram_transport.send_message` is keyword-only and needs a token; a positional call raises TypeError."""
    calls = {}
    mod = type(sys)("telegram_transport")

    def send_message(*args, **kwargs):
        assert args == (), f"positional call would raise TypeError: {args}"
        calls.update(kwargs)
        return {"ok": True, "result": {"message_id": 4242}}

    mod.send_message = send_message
    monkeypatch.setitem(sys.modules, "telegram_transport", mod)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-fixture")
    receipt = cc._default_telegram_sender("chat-fixture", "hello")
    assert calls["token"] == "token-fixture" and calls["chat_id"] == "chat-fixture" and calls["text"] == "hello"
    assert receipt == "4242"


def test_the_default_telegram_sender_refuses_without_a_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as exc:
        cc._default_telegram_sender("chat-fixture", "hello")
    assert str(exc.value) == "telegram_token_not_configured"


def test_the_default_email_sender_gives_the_recipient_to_the_adapter_that_takes_one(monkeypatch):
    """`alerting.send_email` has no recipient parameter; using it would put the address in the subject line."""
    seen = {}
    mod = type(sys)("email_notifier")

    def send_email(subject, body, to=None, attachments=None):
        seen.update({"subject": subject, "body": body, "to": to})
        return True

    mod.send_email = send_email
    monkeypatch.setitem(sys.modules, "email_notifier", mod)
    cc._default_email_sender("operator@example.invalid", "CRITICAL — test", "body")
    assert seen["to"] == "operator@example.invalid"
    assert seen["subject"].startswith("CRITICAL —")


def test_the_default_email_sender_turns_a_refused_send_into_a_failure(monkeypatch):
    mod = type(sys)("email_notifier")
    mod.send_email = lambda subject, body, to=None, attachments=None: False
    monkeypatch.setitem(sys.modules, "email_notifier", mod)
    with pytest.raises(RuntimeError) as exc:
        cc._default_email_sender("operator@example.invalid", "s", "b")
    assert str(exc.value) == "email_send_refused"


# ── "returned without raising" is not "delivered" (cc-deepseek-2 F1, cc-deepseek-8 F2/F3) ────────────────────────

def test_a_sender_that_returns_no_receipt_is_not_recorded_as_sent(monkeypatch):
    """A capped, suppressed or no-op sender returns falsy without raising. It must not publish DELIVERED."""
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    calls = {"email": [], "telegram": []}
    delivery = cc.deliver(EVENT, contact=contact(), policy=policy(),
                          email_sender=lambda *a: (calls["email"].append(a), None)[1],
                          telegram_sender=lambda *a: (calls["telegram"].append(a), None)[1],
                          text_sender=lambda e: {"sent": False, "reason": "capped"})
    by = {r.channel: r for r in delivery.receipts}
    assert by["telegram_critical"].status == "failed", by["telegram_critical"].as_dict()
    assert by["telegram_critical"].reason == "sender_returned_no_receipt"
    assert by["email"].status == "failed" and by["email"].reason == "sender_returned_no_receipt"
    assert len(calls["telegram"]) == 1 and len(calls["email"]) == 1, "the send was still attempted"
    assert delivery.delivered is False, "an unconfirmed send must never publish the event as delivered"


def test_a_truthy_receipt_is_still_a_delivery(monkeypatch):
    """The fix must not make every send look failed: the default adapters return a message id / accepted marker."""
    delivery, _calls = run(monkeypatch)
    by = {r.channel: r for r in delivery.receipts}
    assert by["telegram_critical"].status == "sent" and by["email"].status == "sent"
    assert delivery.delivered is True


def test_a_text_result_without_an_explicit_sent_true_is_not_sent(monkeypatch):
    """The old test was negative (`result.get('sent') is not False`), so `{}`, `{'ok': False}` and `{'reason': …}`
    all came back as sent. Only an explicit True may."""
    for result in ({}, {"ok": False}, {"reason": "hourly_cap"}, None, "unexpected-shape"):
        delivery, _calls = run(monkeypatch, text_sender=lambda e, r=result: r)
        text = {r.channel: r for r in delivery.receipts}["text_gateway"]
        assert text.status != "sent", (result, text.as_dict())
    delivery, _calls = run(monkeypatch, text_sender=lambda e: {"sent": True})
    assert {r.channel: r for r in delivery.receipts}["text_gateway"].status == "sent"
    delivery, _calls = run(monkeypatch, text_sender=lambda e: {"sent": False, "reason": "capped"})
    text = {r.channel: r for r in delivery.receipts}["text_gateway"]
    assert text.status == "skipped" and text.reason == "capped"


def test_a_missing_text_allowlist_does_not_stop_email_and_telegram(monkeypatch):
    """cc-deepseek-8 F3: the text config is the TEXT channel's; its absence must not silence the other two."""
    def missing(*_a, **_k):
        raise cd.CriticalDeliveryRefused("text_allowlist_missing")

    monkeypatch.setattr(cd, "load_text_allowlist", missing)
    delivery, calls = run(monkeypatch)  # run() passes the fixture policy, so drop it to exercise the loader
    assert delivery.delivered is True

    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    calls = {"email": [], "telegram": [], "text": []}
    delivery = cc.deliver(EVENT, contact=contact(),
                          email_sender=lambda *a: (calls["email"].append(a), "smtp-ok")[1],
                          telegram_sender=lambda *a: (calls["telegram"].append(a), "tg-42")[1],
                          text_sender=lambda e: {"sent": True})
    by = {r.channel: r for r in delivery.receipts}
    assert len(calls["email"]) == 1 and len(calls["telegram"]) == 1, "the other two channels were still attempted"
    assert by["email"].status == "sent" and by["telegram_critical"].status == "sent"
    assert by["text_gateway"].status == "skipped" and by["text_gateway"].reason == "text_allowlist_missing"
