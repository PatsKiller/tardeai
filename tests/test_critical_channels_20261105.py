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
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the test-private loader lives beside this file
from _critical_module_loader import load  # noqa: E402

cc = load("critical_channels")  # AGENTS.md:484: loaded by file path, never through the package
cd = load("critical_delivery")  # AGENTS.md:484: loaded by file path, never through the package
cc.cd = cd  # same file, loaded copy: bind it so the module under test raises the class this suite catches


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


def test_the_email_subject_starts_with_the_prefix_and_the_body_carries_the_what(monkeypatch):
    _delivery, calls = run(monkeypatch)
    to, subject, body = calls["email"][0]
    assert subject.startswith("CRITICAL —") and subject.endswith("SPCX stop rejected by the broker")
    assert body.startswith("SPCX stop rejected by the broker")


def test_the_event_action_and_link_reach_both_the_email_and_the_telegram_text(monkeypatch):
    """codex P1: `what` is only the trigger. B4 puts its re-authorisation URL exclusively in action/link, so both
    fallback bodies must carry the action and the link or the operator cannot act from the message."""
    url = "https://cc-host.example.invalid/v3/system/schwab-reauth"
    event = dict(EVENT, what="Schwab refresh token expires in 2 days",
                 action=f"Schwab login expiring — renew it: {url}", link=url)
    calls = {"email": [], "telegram": []}
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    delivery = cc.deliver(event, contact=contact(), policy=policy(),
                          email_sender=lambda to, s, b: (calls["email"].append((to, s, b)), "smtp-ok")[1],
                          telegram_sender=lambda c, t: (calls["telegram"].append(t), "tg-42")[1],
                          text_sender=lambda e: {"sent": True})
    assert all(r.status == "sent" for r in delivery.receipts), [r.as_dict() for r in delivery.receipts]
    email_body = calls["email"][0][2]
    telegram_text = calls["telegram"][0]
    for body in (email_body, telegram_text):
        assert "renew it" in body and url in body, body
    # the trigger is stated once, not repeated by the subject prefix and again in the body
    assert telegram_text.count("Schwab refresh token expires in 2 days") == 1, telegram_text
    assert telegram_text.startswith("CRITICAL — "), telegram_text


def test_a_failed_email_does_not_stop_telegram_or_the_text(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("smtp refused")

    delivery, calls = run(monkeypatch, email_sender=boom)
    by = {r.channel: r for r in delivery.receipts}
    # cc-deepseek F5: the exception's own safe reason, not its class name, is what the Home page shows.
    assert by["email"].status == "failed" and by["email"].reason == "smtp refused"
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

def _chokepoint(monkeypatch, *, outcome, route=None, held=None):
    """Stub ``telegram_alert``'s chokepoint entry and return the kwargs the default sender hands it."""
    from scripts import telegram_alert as ta

    seen: dict = {}

    def send_telegram_outcome(text, **kwargs):
        seen["text"] = text
        seen.update(kwargs)
        return outcome

    monkeypatch.setattr(ta, "send_telegram_outcome", send_telegram_outcome)
    monkeypatch.setattr(ta, "last_intent_route", lambda: dict(route or {}))
    monkeypatch.setattr(ta, "last_held_chunks", lambda: list(held or []))
    return seen


def test_the_default_telegram_sender_goes_through_the_communications_chokepoint(monkeypatch):
    """codex P1: a direct `telegram_transport.send_message` call wrote no communications ledger row and routed no P1
    intent. The default sender must enter through `telegram_alert`, the one path that does both."""
    seen = _chokepoint(monkeypatch, outcome={"status": "DELIVERED", "delivered": True, "accepted": True,
                                             "message_ids": ["4242"]})
    assert cc._default_telegram_sender("chat-fixture", "hello") == "4242"
    assert seen["text"] == "hello"
    assert seen["chat_ids"] == ["chat-fixture"], "the Critical chat, not the default chat"
    assert seen["priority"] == "P1", "an actionable Critical alert is a P1 notification, never an ordinary held message"
    assert seen["message_class"] == "operator_alert"
    assert seen["producer"] == "critical_channels"
    assert seen["dedupe_minutes"] == 0, (
        "the router's ordinary default window would report a NEW actionable recurrence as DEDUPED and never reach "
        "the operator; the producer keeps its own ledger, so the router's dedupe must be off"
    )


def test_a_repeated_critical_body_still_reaches_the_operator_through_the_real_router():
    """cx-openai D52 triage on #2680, executed against the real router rather than a stub.

    Same body twice inside the router's default window: with the default (no `dedupe_minutes`) the second send is
    DEDUPED and never reaches the transport; with `dedupe_minutes=0` — what the Critical sender now passes — both
    route to delivery, because a recurrence of a live Critical condition is actionable.
    """
    from scripts import telegram_alert_router as router

    router._intent_sent.clear()
    body = "CRITICAL — synthetic: the disk lane stopped reporting"
    default_route = router.route_intent(body, "P1", producer="critical_channels")
    assert default_route["deliver"] is True
    router._intent_sent[default_route["dedupe_key"]] = __import__("time").time()
    again_default = router.route_intent(body, "P1", producer="critical_channels")
    assert again_default["decision"] == "DEDUPED" and again_default["deliver"] is False, again_default

    router._intent_sent.clear()
    first = router.route_intent(body, "P1", producer="critical_channels", dedupe_minutes=0)
    assert first["deliver"] is True
    router._intent_sent[first["dedupe_key"]] = __import__("time").time()
    again_critical = router.route_intent(body, "P1", producer="critical_channels", dedupe_minutes=0)
    assert again_critical["decision"] == "DELIVER" and again_critical["deliver"] is True, again_critical


def test_the_default_telegram_sender_refuses_without_a_token(monkeypatch):
    _chokepoint(monkeypatch, outcome={"status": "UNCONFIGURED", "delivered": False, "accepted": False,
                                      "message_ids": []})
    with pytest.raises(RuntimeError) as exc:
        cc._default_telegram_sender("chat-fixture", "hello")
    assert str(exc.value) == "telegram_token_not_configured"


def test_the_default_telegram_sender_refuses_a_hold_instead_of_returning_ok(monkeypatch):
    """The chokepoint reports a Communications Editor hold as HELD with no id. The editor's own reason is kept, and a
    hold is never a delivery."""
    _chokepoint(monkeypatch, outcome={"status": "HELD", "delivered": False, "accepted": True, "message_ids": []},
                held=[{"chat_id": "chat-fixture", "chunk": 0, "reason": "duplicate"}])
    with pytest.raises(cc.ChannelSuppressed) as exc:
        cc._default_telegram_sender("chat-fixture", "hello")
    assert str(exc.value) == "telegram_suppressed:duplicate"


def test_the_default_telegram_sender_refuses_an_ok_with_no_message_id(monkeypatch):
    """ok is not a receipt. Without a message id there is no evidence anything was sent, so it is a failure."""
    _chokepoint(monkeypatch, outcome={"status": "UNCONFIRMED", "delivered": False, "accepted": True,
                                      "message_ids": []})
    with pytest.raises(RuntimeError) as exc:
        cc._default_telegram_sender("chat-fixture", "hello")
    assert str(exc.value) == "telegram_message_id_missing"


def test_a_deduped_or_gateway_routed_message_is_skipped_not_sent(monkeypatch):
    """ROUTED means no transport attempt in this process. It is not a delivery, so it never becomes a sent receipt."""
    _chokepoint(monkeypatch, outcome={"status": "ROUTED", "delivered": False, "accepted": True, "message_ids": []},
                route={"decision": "DEDUPED"})
    with pytest.raises(cc.ChannelSuppressed) as exc:
        cc._default_telegram_sender("chat-fixture", "hello")
    assert str(exc.value) == "telegram_routed:deduped"
    # and a routed path that accepted nothing is a failure, not a deliberate skip
    _chokepoint(monkeypatch, outcome={"status": "ROUTED", "delivered": False, "accepted": False, "message_ids": []})
    with pytest.raises(RuntimeError) as exc:
        cc._default_telegram_sender("chat-fixture", "hello")
    assert str(exc.value) == "telegram_send_refused"


def test_the_real_chokepoint_records_the_send_in_the_communications_ledger(monkeypatch):
    """The wiring behind the test above: with the real ``send_telegram``, the default sender's send reaches
    ``_best_effort_comms_publish`` (the communication_events writer) and still returns the provider message id."""
    from scripts import telegram_alert as ta

    ledger = []

    def fake_publish(message, **kwargs):
        ledger.append((message, kwargs))
        return {"ok": True, "errors": [], "status": "SENT", "settled": 1, "provider_message_id": "4242"}

    def fake_raw(message, chat_ids=None, **_kwargs):
        ta._LAST_MESSAGE_IDS.clear()
        ta._LAST_MESSAGE_IDS.extend(["4242"])
        ta._record_attempt(ok=True, reason=None, message_ids=1, held=0, chunks=1)
        return {"ok": True, "message_ids": ["4242"], "chat_ids": [str(c) for c in (chat_ids or [])], "held": []}

    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_comms_gateway_owns", lambda _message_class: False)
    monkeypatch.setattr(ta, "_intent_send", lambda message, priority, send_fn, **_kwargs: send_fn())
    monkeypatch.setattr(ta, "_raw_send_telegram_result", fake_raw)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", fake_publish)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-fixture")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-fixture")

    assert cc._default_telegram_sender("chat-fixture", "CRITICAL — test") == "4242"
    assert len(ledger) == 1, "the chokepoint must publish the send to the communications ledger"
    message, kwargs = ledger[0]
    assert message == "CRITICAL — test"
    assert kwargs["message_class"] == "operator_alert" and kwargs["delivered"] is True


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


def test_a_held_or_deduplicated_telegram_message_is_not_a_delivery(monkeypatch):
    """codex P1: the transport's hold shape is `ok=True, message_id=None, suppressed=...` — it sent nothing. The
    truthy `ok` must not become a `sent` receipt, and DELIVERED must stay false when nothing else confirmed."""
    hold = {"ok": True, "status_code": 200, "response": {}, "edited": False,
            "message_id": None, "suppressed": "duplicate"}
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    delivery = cc.deliver(EVENT, contact=contact(), policy=policy(),
                          email_sender=lambda *a: None,
                          telegram_sender=lambda *a: dict(hold),
                          text_sender=lambda e: {"sent": False, "reason": "capped"})
    by = {r.channel: r for r in delivery.receipts}
    assert by["telegram_critical"].status == "skipped", by["telegram_critical"].as_dict()
    assert by["telegram_critical"].reason == "telegram_suppressed:duplicate", by["telegram_critical"].as_dict()
    assert delivery.delivered is False, "a held message reached nobody and must never publish DELIVERED"
    assert "message body" not in repr(delivery.as_dict())


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


def test_a_missing_allowlist_refuses_the_event_instead_of_inventing_a_taxonomy(monkeypatch):
    """cc-deepseek F3: `config/critical_text_classes.json` is BOTH the text setting and the CRITICAL taxonomy. When it
    cannot be read the taxonomy is unknown, so no caller-supplied class may be promoted to CRITICAL; refuse with the
    named reason (the honest reading of "a class absent from the file is refused everywhere")."""
    def missing(*_a, **_k):
        raise cd.CriticalDeliveryRefused("text_allowlist_missing")

    monkeypatch.setattr(cd, "load_text_allowlist", missing)
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    sent = []
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cc.deliver({"alert_class": "digest", "what": "x"}, contact=contact(),
                   email_sender=lambda *a: sent.append(a), telegram_sender=lambda *a: sent.append(a),
                   text_sender=lambda e: sent.append(e))
    assert str(exc.value) == "text_allowlist_missing"
    assert sent == [], "nothing may be sent under a taxonomy the module could not read"
    with pytest.raises(cd.CriticalDeliveryRefused):
        cc.deliver(EVENT, contact=contact(), email_sender=lambda *a: sent.append(a),
                   telegram_sender=lambda *a: sent.append(a), text_sender=lambda e: sent.append(e))
    assert sent == []


# ── configuration failures are each channel's own receipt (codex P2) ──────────────────────────────────────

def test_an_unreadable_contact_file_does_not_stop_the_critical_chat(monkeypatch):
    """The Critical chat is configured independently (`TRADEAI_CRITICAL_ALERT_CHAT_ID`) and needs no contact file.
    A missing private contact file must fail email and text only."""
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")

    def unreadable(*_a, **_k):
        raise cd.CriticalDeliveryRefused("operator_contact_missing")

    monkeypatch.setattr(cd, "load_operator_contact", unreadable)
    calls = {"telegram": []}
    delivery = cc.deliver(EVENT, policy=policy(),
                          email_sender=lambda *a: "smtp-ok",
                          telegram_sender=lambda c, t: (calls["telegram"].append(t), "tg-42")[1],
                          text_sender=lambda e: {"sent": True})
    by = {r.channel: r for r in delivery.receipts}
    assert len(calls["telegram"]) == 1, "the independently configured chat was still attempted"
    assert by["telegram_critical"].status == "sent"
    assert by["email"].status == "failed" and by["email"].reason == "operator_contact_missing"
    assert by["text_gateway"].status == "failed" and by["text_gateway"].reason == "operator_contact_missing"
    assert delivery.delivered is True


def test_a_malformed_gateway_address_does_not_stop_email_or_telegram(monkeypatch):
    """One bad line in the contact file is the text channel's configuration error; the valid email and chat still go."""
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    doc = contact()
    doc["critical_sms_email_gateways"] = [{"address": "555-0100", "label": "bad line"}]
    doc.pop("critical_sms_email_gateway", None)
    calls = {"email": [], "telegram": []}
    delivery = cc.deliver(EVENT, contact=doc, policy=policy(),
                          email_sender=lambda to, s, b: (calls["email"].append((to, s, b)), "smtp-ok")[1],
                          telegram_sender=lambda c, t: (calls["telegram"].append(t), "tg-42")[1],
                          text_sender=lambda e: {"sent": True})
    by = {r.channel: r for r in delivery.receipts}
    assert len(calls["email"]) == 1 and len(calls["telegram"]) == 1
    assert by["email"].status == "sent" and by["telegram_critical"].status == "sent"
    assert by["text_gateway"].status == "skipped" and by["text_gateway"].reason == "text_gateway_not_an_address"
    assert delivery.delivered is True


def test_a_stale_stub_in_the_package_path_cannot_satisfy_this_suite():
    """AGENTS.md:484's cause, reproduced deliberately — and it must not reach the module under test.

    2026-09-14: an earlier suite left an empty stub in ``sys.modules`` and every later ``from scripts.lib import …``
    asserted against it. This suite loads its subject by file path, and this test pins that property rather than
    assuming it: poison the package path first, then load the file, and require the real implementation.
    """
    import importlib.util
    import types

    saved = sys.modules.get("scripts.lib.critical_channels")
    stub = types.ModuleType("scripts.lib.critical_channels")
    sys.modules["scripts.lib.critical_channels"] = stub
    isolated_name = "_under_test_critical_channels_poisoned"
    try:
        path = ROOT / "scripts" / "lib" / "critical_channels.py"
        spec = importlib.util.spec_from_file_location(isolated_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[isolated_name] = module
        spec.loader.exec_module(module)

        assert module is not stub, "the file-path load returned the poisoned package entry"
        assert hasattr(module, "deliver"), "the loaded module is not the implementation"
        # and the module this suite actually holds came from the file
        assert cc is not stub
        assert Path(cc.__spec__.origin) == ROOT / "scripts" / "lib" / "critical_channels.py"
        assert sys.modules[cc.__spec__.name] is cc
    finally:
        sys.modules.pop(isolated_name, None)
        if saved is None:
            sys.modules.pop("scripts.lib.critical_channels", None)
        else:
            sys.modules["scripts.lib.critical_channels"] = saved
