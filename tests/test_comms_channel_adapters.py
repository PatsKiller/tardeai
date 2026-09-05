#!/usr/bin/env python3
"""Phase 10 — gateway channel adapters (email/slack/whatsapp). No real network."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.comms.channel_adapters import send_via_gateway  # noqa: E402
from scripts.lib.comms.client import memory_store_snapshot, reset_memory_store  # noqa: E402
from scripts.lib.comms.delivery import (  # noqa: E402
    memory_delivery_snapshot,
    reset_memory_deliveries,
)
from scripts.lib.comms.enforcement import MissingCommunicationEventId  # noqa: E402
from scripts.lib.comms.mode import MODE_ACTIVE, MODE_OFF, get_gateway_mode  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None
    # Unit tests assert in-memory ledger; force no DB even when localhost has one.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    reset_memory_store()
    reset_memory_deliveries()
    yield
    reset_memory_store()
    reset_memory_deliveries()
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None


def test_default_deliver_false_records_event_no_network(monkeypatch):
    """deliver=False publishes + reserves only; underlying adapters never called."""
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("hit")
        raise AssertionError("provider must not be called when deliver=False")

    monkeypatch.setattr(
        "scripts.alerting.send_email", _boom, raising=False
    )
    # Ensure import path used by adapter is patched once loaded via lazy import
    import scripts.alerting as alerting

    monkeypatch.setattr(alerting, "send_email", _boom)
    monkeypatch.setattr(alerting, "send_slack", _boom)
    monkeypatch.setattr(alerting, "send_whatsapp", _boom)

    result = send_via_gateway(
        "email",
        body="hello body",
        subject="hello subject",
        producer="ops.test",
        subject_key="test:channel_adapters:email",
    )
    assert result["ok"] is True
    assert result["delivered"] is False
    assert result["delivery_owned"] is False
    assert result["event_id"]
    assert result["gateway_mode"] == MODE_OFF
    assert not calls

    snap = memory_store_snapshot()
    assert result["event_id"] in snap
    assert snap[result["event_id"]]["sanitized_body"] == "hello body"
    deliveries = memory_delivery_snapshot()
    assert len(deliveries) >= 1
    drow = next(iter(deliveries.values()))
    assert drow["event_id"] == result["event_id"]
    assert drow["channel"] == "email"
    assert drow["status"] == "RESERVED"
    assert result["delivery_id"] == drow["delivery_id"]


def test_deliver_true_in_off_mode_blocked(monkeypatch):
    import scripts.alerting as alerting

    monkeypatch.setattr(
        alerting, "send_slack", MagicMock(side_effect=AssertionError("no net"))
    )

    assert get_gateway_mode(refresh=True) == MODE_OFF
    result = send_via_gateway(
        "slack",
        body="blocked send",
        producer="ops.test",
        subject_key="test:channel_adapters:blocked",
        deliver=True,
    )
    assert result["ok"] is False
    assert result["error"] == "delivery_blocked_mode"
    assert result["delivered"] is False
    assert result["delivery_owned"] is False
    assert result["event_id"]  # still recorded
    alerting.send_slack.assert_not_called()
    deliveries = memory_delivery_snapshot()
    assert any(d["status"] == "RESERVED" for d in deliveries.values())


def test_deliver_true_active_settles_sent(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    mode_mod._cache["mode"] = None

    import scripts.alerting as alerting

    mock_email = MagicMock(return_value=None)
    monkeypatch.setattr(alerting, "send_email", mock_email)

    result = send_via_gateway(
        "email",
        body="live body",
        subject="live subject",
        producer="ops.test",
        subject_key="test:channel_adapters:active_email",
        deliver=True,
    )
    assert result["ok"] is True
    assert result["delivered"] is True
    assert result["delivery_owned"] is True
    assert result["gateway_mode"] == MODE_ACTIVE
    mock_email.assert_called_once()
    args, kwargs = mock_email.call_args
    assert args[0] == "live subject"
    assert args[1] == "live body"

    deliveries = memory_delivery_snapshot()
    assert result["delivery_id"] in deliveries
    assert deliveries[result["delivery_id"]]["status"] == "SENT"


def test_require_event_id_before_provider(monkeypatch):
    """Provider path must call require_event_id; missing id fails closed."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    mode_mod._cache["mode"] = None

    import scripts.alerting as alerting
    import scripts.lib.comms.channel_adapters as ca

    mock_slack = MagicMock()
    monkeypatch.setattr(alerting, "send_slack", mock_slack)

    # Force require_event_id to reject so we prove the gate sits before send.
    def _reject(_event_id, *, adapter="transport"):
        raise MissingCommunicationEventId(f"{adapter}: forced")

    monkeypatch.setattr(ca, "require_event_id", _reject)

    with pytest.raises(MissingCommunicationEventId):
        send_via_gateway(
            "slack",
            body="gate check",
            producer="ops.test",
            subject_key="test:channel_adapters:require_id",
            deliver=True,
        )
    mock_slack.assert_not_called()


def test_require_event_id_receives_minted_id(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    mode_mod._cache["mode"] = None

    import scripts.alerting as alerting
    import scripts.lib.comms.channel_adapters as ca

    seen: dict[str, str] = {}

    def _track(event_id, *, adapter="transport"):
        seen["event_id"] = event_id
        seen["adapter"] = adapter
        return str(event_id).strip()

    monkeypatch.setattr(ca, "require_event_id", _track)
    monkeypatch.setattr(alerting, "send_whatsapp", MagicMock())

    result = send_via_gateway(
        "whatsapp_twilio",
        body="wa body",
        producer="ops.test",
        subject_key="test:channel_adapters:require_track",
        deliver=True,
    )
    assert result["ok"] is True
    assert seen["event_id"] == result["event_id"]
    assert seen["adapter"] == "whatsapp_twilio"


def test_whatsapp_meta_optional_path(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    mode_mod._cache["mode"] = None

    import scripts.lib.cio_whatsapp_egress as egress

    mock_send = MagicMock(
        return_value={"ok": True, "message_id": "wamid.test_1"}
    )
    monkeypatch.setattr(egress, "send_whatsapp_text", mock_send)

    result = send_via_gateway(
        "whatsapp_meta",
        body="meta body",
        producer="ops.test",
        subject_key="test:channel_adapters:meta",
        deliver=True,
        to_wa_id="15551234567",
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["delivered"] is True
    assert result.get("provider_message_id") == "wamid.test_1"
    mock_send.assert_called_once()
    assert memory_delivery_snapshot()[result["delivery_id"]]["status"] == "SENT"


def test_unsupported_channel():
    result = send_via_gateway(
        "carrier_pigeon",
        body="nope",
        producer="ops.test",
        subject_key="test:channel_adapters:bad",
    )
    assert result["ok"] is False
    assert result["error"] == "unsupported_channel"
    assert memory_store_snapshot() == {}


def test_telegram_supported_record_only(monkeypatch):
    import scripts.lib.comms.channel_adapters as ca

    monkeypatch.setattr(
        ca,
        "_provider_send_telegram",
        MagicMock(side_effect=AssertionError("no net")),
    )
    result = send_via_gateway(
        "telegram",
        body="tg body",
        producer="ops.test",
        subject_key="test:channel_adapters:tg_record",
        message_class="operator_alert",
    )
    assert result["ok"] is True
    assert result["delivered"] is False
    assert result["channel"] == "telegram"
    assert result["event_id"]


def test_telegram_canary_empty_allowlist_blocks_deliver(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    mode_mod._cache["mode"] = None

    import scripts.lib.comms.channel_adapters as ca

    mock_tg = MagicMock(side_effect=AssertionError("must not send"))
    monkeypatch.setattr(ca, "_provider_send_telegram", mock_tg)

    result = send_via_gateway(
        "telegram",
        body="blocked",
        producer="ops.test",
        subject_key="test:channel_adapters:tg_canary_empty",
        message_class="operator_alert",
        deliver=True,
    )
    assert result["ok"] is False
    assert result["error"] == "delivery_blocked_allowlist"
    assert result["delivered"] is False
    assert result["delivery_owned"] is False
    assert result["event_id"]
    mock_tg.assert_not_called()


def test_telegram_active_empty_allowlist_blocks_deliver(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    mode_mod._cache["mode"] = None

    import scripts.lib.comms.channel_adapters as ca

    mock_tg = MagicMock(side_effect=AssertionError("must not send"))
    monkeypatch.setattr(ca, "_provider_send_telegram", mock_tg)

    result = send_via_gateway(
        "telegram",
        body="blocked active",
        producer="ops.test",
        subject_key="test:channel_adapters:tg_active_empty",
        message_class="ops",
        deliver=True,
    )
    assert result["ok"] is False
    assert result["error"] == "delivery_blocked_allowlist"
    assert result["delivered"] is False
    assert result["delivery_owned"] is False
    mock_tg.assert_not_called()


def test_telegram_canary_allowlist_delivers(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops,operator_alert")
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    mode_mod._cache["mode"] = None

    import scripts.lib.comms.channel_adapters as ca

    mock_tg = MagicMock(return_value={"ok": True, "provider_message_id": None})
    monkeypatch.setattr(ca, "_provider_send_telegram", mock_tg)

    result = send_via_gateway(
        "telegram",
        body="canary ok",
        producer="ops.test",
        subject_key="test:channel_adapters:tg_canary_ok",
        message_class="operator_alert",
        deliver=True,
    )
    assert result["ok"] is True
    assert result["delivered"] is True
    assert result["delivery_owned"] is True
    mock_tg.assert_called_once()
    assert memory_delivery_snapshot()[result["delivery_id"]]["status"] == "SENT"


def test_telegram_canary_class_not_allowlisted_blocks(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None

    import scripts.lib.comms.channel_adapters as ca

    mock_tg = MagicMock(side_effect=AssertionError("must not send"))
    monkeypatch.setattr(ca, "_provider_send_telegram", mock_tg)

    result = send_via_gateway(
        "telegram",
        body="wrong class",
        producer="ops.test",
        subject_key="test:channel_adapters:tg_wrong_class",
        message_class="research_digest",
        deliver=True,
    )
    assert result["ok"] is False
    assert result["error"] == "delivery_blocked_allowlist"
    mock_tg.assert_not_called()


def test_telegram_provider_uses_raw_not_send_telegram(monkeypatch):
    """Recursion safety: provider path must call _raw_send_telegram_result, not send_telegram."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "operator_alert")
    mode_mod._cache["mode"] = None

    import scripts.telegram_alert as ta
    import scripts.lib.comms.channel_adapters as ca

    calls = {"raw": 0, "send": 0}

    def _raw_result(*_a, **_k):
        calls["raw"] += 1
        return {
            "ok": True,
            "message_ids": ["4242"],
            "chat_ids": ["999"],
        }

    def _send(*_a, **_k):
        calls["send"] += 1
        raise AssertionError("send_telegram must not be called from provider path")

    monkeypatch.setattr(ta, "_raw_send_telegram_result", _raw_result)
    monkeypatch.setattr(ta, "send_telegram", _send)
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["999"])

    result = ca._provider_send_telegram(
        body="no recurse",
        kwargs={},
        mode="CANARY",
    )
    assert result["ok"] is True
    assert result.get("provider_message_id") == "4242"
    assert calls["raw"] == 1
    assert calls["send"] == 0


def test_telegram_provider_joins_multiple_message_ids(monkeypatch):
    import scripts.telegram_alert as ta
    import scripts.lib.comms.channel_adapters as ca

    monkeypatch.setattr(
        ta,
        "_raw_send_telegram_result",
        lambda *_a, **_k: {
            "ok": True,
            "message_ids": ["11", "22"],
            "chat_ids": ["1", "2"],
        },
    )
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["1", "2"])
    result = ca._provider_send_telegram(body="multi", kwargs={}, mode="ACTIVE")
    assert result["ok"] is True
    assert result["provider_message_id"] == "11,22"
    assert result["provider_coordinates"]["message_ids"] == ["11", "22"]
