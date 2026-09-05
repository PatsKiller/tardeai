#!/usr/bin/env python3
"""Telegram CANARY/ACTIVE ownership via communications gateway (no dual-send)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.comms.client import reset_memory_store  # noqa: E402
from scripts.lib.comms.delivery import reset_memory_deliveries  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    reset_memory_store()
    reset_memory_deliveries()
    yield
    reset_memory_store()
    reset_memory_deliveries()
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None


def test_off_still_legacy_no_gateway_deliver(monkeypatch):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    assert mode_mod.get_gateway_mode(refresh=True) == "OFF"

    legacy = MagicMock(return_value=True)
    gateway = MagicMock(side_effect=AssertionError("gateway must not own in OFF"))
    monkeypatch.setattr(ta, "_legacy_send", legacy)
    monkeypatch.setattr(ta, "_send_via_comms_gateway", gateway)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", MagicMock())
    monkeypatch.setattr(
        ta, "publish_operator_message", MagicMock(return_value={"accepted": True, "delivered": True, "route_mode": "LEGACY"})
    )

    assert ta.send_telegram("hello off", bypass_router=True) is True
    legacy.assert_not_called()  # publish_operator_message path used
    gateway.assert_not_called()
    ta.publish_operator_message.assert_called_once()


def test_canary_allowlisted_uses_gateway_no_dual_send(monkeypatch):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "operator_alert,ops")
    mode_mod._cache["mode"] = None

    gateway = MagicMock(return_value=True)
    legacy = MagicMock(side_effect=AssertionError("no dual-send"))
    monkeypatch.setattr(ta, "_send_via_comms_gateway", gateway)
    monkeypatch.setattr(ta, "_legacy_send", legacy)
    monkeypatch.setattr(
        ta, "publish_operator_message", MagicMock(side_effect=AssertionError("no legacy outbox"))
    )

    assert ta.send_telegram("canary msg", bypass_router=True, message_class="operator_alert") is True
    gateway.assert_called_once()
    assert gateway.call_args.kwargs.get("message_class") == "operator_alert"
    legacy.assert_not_called()


def test_canary_without_allowlist_stays_legacy(monkeypatch):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    # empty CANARY_CLASSES → fail closed for ownership; legacy path remains
    mode_mod._cache["mode"] = None

    gateway = MagicMock(side_effect=AssertionError("must not own without allowlist"))
    monkeypatch.setattr(ta, "_send_via_comms_gateway", gateway)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", MagicMock())
    monkeypatch.setattr(
        ta,
        "publish_operator_message",
        MagicMock(return_value={"accepted": True, "delivered": True, "route_mode": "LEGACY"}),
    )

    assert ta.send_telegram("still legacy", bypass_router=True) is True
    gateway.assert_not_called()
    ta.publish_operator_message.assert_called_once()


def test_active_empty_allowlist_stays_legacy(monkeypatch):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    mode_mod._cache["mode"] = None

    gateway = MagicMock(side_effect=AssertionError("ACTIVE empty must not own telegram"))
    monkeypatch.setattr(ta, "_send_via_comms_gateway", gateway)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", MagicMock())
    monkeypatch.setattr(
        ta,
        "publish_operator_message",
        MagicMock(return_value={"accepted": True, "delivered": True, "route_mode": "LEGACY"}),
    )

    assert ta.send_telegram("active empty", bypass_router=True, message_class="ops") is True
    gateway.assert_not_called()


def test_gateway_owned_kwarg_skips_reentry(monkeypatch):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "operator_alert")
    mode_mod._cache["mode"] = None

    gateway = MagicMock(side_effect=AssertionError("recursion"))
    legacy = MagicMock(return_value=True)
    monkeypatch.setattr(ta, "_send_via_comms_gateway", gateway)
    monkeypatch.setattr(ta, "_legacy_send", legacy)

    assert (
        ta.send_telegram(
            "owned leaf",
            bypass_router=True,
            message_class="operator_alert",
            _gateway_owned=True,
        )
        is True
    )
    gateway.assert_not_called()
    legacy.assert_called_once()


def test_send_via_comms_gateway_publishes_then_delivers_no_legacy(monkeypatch):
    import telegram_alert as ta
    import scripts.lib.comms.channel_adapters as ca

    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "operator_alert")
    mode_mod._cache["mode"] = None

    published_ids: list[str] = []

    class _Pub:
        ok = True
        event_id = "evt_test_1"
        delivery_ids = ["dlv_test_1"]
        errors: list = []

    def _pub(_event):
        published_ids.append(_event.event_id or "x")
        return _Pub()

    def _svg(channel, **kwargs):
        assert channel == "telegram"
        assert kwargs.get("deliver") is True
        assert kwargs.get("event_id") == "evt_test_1"
        assert kwargs.get("_existing_delivery_id") == "dlv_test_1"
        return {
            "ok": True,
            "delivered": True,
            "delivery_owned": True,
            "event_id": "evt_test_1",
        }

    monkeypatch.setattr(
        "scripts.lib.comms.client.publish_communication", _pub, raising=False
    )
    monkeypatch.setattr(ca, "send_via_gateway", _svg)
    # Also patch import path used inside helper after local import
    import scripts.lib.comms.client as client_mod

    monkeypatch.setattr(client_mod, "publish_communication", _pub)

    legacy = MagicMock(side_effect=AssertionError("no dual"))
    monkeypatch.setattr(ta, "_legacy_send", legacy)

    assert ta._send_via_comms_gateway("body", message_class="operator_alert") is True
    assert published_ids
    legacy.assert_not_called()
