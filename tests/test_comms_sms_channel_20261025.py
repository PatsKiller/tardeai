"""Comms gateway SMS channel (2026-10-25, operator: "emailed, notified, and texted"). Off unless ENABLE_SMS=true;
config-driven (carrier email-to-SMS address or a Twilio SMS number); routed through send_via_gateway. Hermetic: SMTP
and Twilio are stubbed, nothing leaves the box."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import scripts.alerting as alerting
import scripts.lib.comms.channel_adapters as ca
from scripts.lib.comms import mode as mode_mod
from scripts.lib.comms.channel_adapters import SUPPORTED_CHANNELS, render_for_channel, send_via_gateway

SMS_KEYS = ("ENABLE_SMS", "OPERATOR_SMS_EMAIL", "TWILIO_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM", "TWILIO_SMS_TO")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in SMS_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.fixture.invalid")
    monkeypatch.setenv("REPORT_EMAIL_FROM", "from@fixture.invalid")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)


def test_off_by_default_sends_nothing(monkeypatch):
    send = MagicMock()
    monkeypatch.setattr(alerting, "_smtp_send", send)
    monkeypatch.setenv("OPERATOR_SMS_EMAIL", "5550000000@sms.fixture.invalid")
    assert alerting.send_sms("x") == {"ok": False, "error": "sms_disabled"}
    send.assert_not_called()


def test_enabled_but_not_configured(monkeypatch):
    monkeypatch.setenv("ENABLE_SMS", "true")
    assert alerting.send_sms("x") == {"ok": False, "error": "sms_not_configured"}


def test_email_to_sms_gateway_one_line(monkeypatch):
    sent = []
    monkeypatch.setattr(alerting, "_smtp_send", sent.append)
    monkeypatch.setenv("ENABLE_SMS", "true")
    monkeypatch.setenv("OPERATOR_SMS_EMAIL", "5550000000@sms.fixture.invalid")
    res = alerting.send_sms("TradeAI FAIL:\n release train\tROLLED_BACK " + "x" * 400)
    assert res["ok"] is True and res["provider"] == "email_to_sms"
    msg = sent[0]
    assert msg["To"] == "5550000000@sms.fixture.invalid"
    body = msg.get_content().strip()
    assert "\n" not in body and len(body) <= 300 and body.startswith("TradeAI FAIL: release train ROLLED_BACK")


def test_provider_number_path(monkeypatch):
    seen = {}

    def fake(sid, token, from_, to_, text):
        seen.update(from_=from_, to_=to_, text=text)
        return "SMfixture"

    monkeypatch.setattr(alerting, "_twilio_sms", fake)
    for k, v in {
        "ENABLE_SMS": "true",
        "TWILIO_SID": "ACfixture",
        "TWILIO_AUTH_TOKEN": "fixture",
        "TWILIO_SMS_FROM": "+15550000001",
        "TWILIO_SMS_TO": "+15550000002",
    }.items():
        monkeypatch.setenv(k, v)
    res = alerting.send_sms("hello")
    assert res == {"ok": True, "provider": "twilio_sms", "message_id": "SMfixture"}
    assert seen == {"from_": "+15550000001", "to_": "+15550000002", "text": "hello"}


def test_email_gateway_wins_over_number_when_both_set(monkeypatch):
    sent, num = [], MagicMock()
    monkeypatch.setattr(alerting, "_smtp_send", sent.append)
    monkeypatch.setattr(alerting, "_twilio_sms", num)
    for k in SMS_KEYS:
        monkeypatch.setenv(k, "true" if k == "ENABLE_SMS" else "fixture")
    assert alerting.send_sms("x")["provider"] == "email_to_sms" and len(sent) == 1
    num.assert_not_called()


def test_sms_is_a_gateway_channel_and_renders_plain():
    assert "sms" in SUPPORTED_CHANNELS and ca.ADAPTER_VERSIONS["sms"] == "sms@v1"
    out = render_for_channel("a\nb  c", "sms")
    assert out == {"ok": True, "channel": "sms", "text": "a b c", "format": "sms"}


def test_gateway_delivers_sms_through_the_adapter(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    mode_mod._cache["mode"] = None
    seen = []
    monkeypatch.setattr(alerting, "send_sms", lambda body: seen.append(body) or {"ok": True, "message_id": "m1"})
    res = send_via_gateway("sms", body="TradeAI FAIL: x", producer="ops.test", subject_key="test:sms:ok", deliver=True)
    assert res["ok"] is True and res["delivered"] is True and seen == ["TradeAI FAIL: x"]
    mode_mod._cache["mode"] = None


def test_gateway_records_not_configured_as_a_failed_delivery(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    mode_mod._cache["mode"] = None
    res = send_via_gateway("sms", body="x", producer="ops.test", subject_key="test:sms:off", deliver=True)
    assert res["delivered"] is False and res["error"] == "sms_disabled"
    mode_mod._cache["mode"] = None


def test_gateway_mode_off_blocks_before_the_adapter(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    mode_mod._cache["mode"] = None
    adapter = MagicMock()
    monkeypatch.setattr(alerting, "send_sms", adapter)
    res = send_via_gateway("sms", body="x", producer="ops.test", subject_key="test:sms:mode", deliver=True)
    assert res["error"] == "delivery_blocked_mode"
    adapter.assert_not_called()
