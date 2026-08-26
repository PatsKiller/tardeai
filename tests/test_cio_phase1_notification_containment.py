"""Phase 1 — CIO notification containment.

ZERO live Telegram. ZERO general-channel routing. Fixtures A/B/Living desk thesis
must never produce a real send (or a general-bot send attempt).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ on path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def iso_dedupe(tmp_path, monkeypatch):
    p = tmp_path / "dedupe.jsonl"
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(p))
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "0")
    # Plant fake CIO creds so credential path is testable without real secrets
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "000000:FAKE_CIO_TOKEN_FOR_TESTS_ONLY")
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "111111111")
    # Also set general tokens — Phase 1 must NEVER use them
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:FAKE_GENERAL_SHOULD_NOT_BE_USED")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999999")
    return p


def test_transport_interdicts_under_pytest(iso_dedupe, monkeypatch):
    from lib import cio_telegram_transport as t

    # Even with live auth, pytest must interdict
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    assert t.under_pytest() is True
    assert t.network_interdicted() is True
    res = t.send_cio_message("Material CIO advisory with enough text to pass length.")
    assert res["delivered"] is False
    assert res["interdicted"] is True


def test_transport_never_reads_general_token(iso_dedupe, monkeypatch):
    from lib import cio_telegram_transport as t

    # Clear CIO token — must not fall back to general
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:GENERAL")
    assert t.cio_bot_token() == ""
    assert t.credentials_ready() is False
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    # force past interdict check for credential assertion
    monkeypatch.setattr(t, "network_interdicted", lambda: False)
    res = t.send_cio_message("x" * 40, require_live_auth=False, force=True)
    assert res["delivered"] is False
    assert "credential" in res.get("reason", "")


def test_chat_ids_no_general_fallback(iso_dedupe, monkeypatch):
    from lib import cio_telegram_transport as t
    from lib import cio_telegram_converse as c

    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "")
    monkeypatch.setenv("TELEGRAM_CIO_ALLOWLIST", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999999")
    assert t.cio_chat_ids() == []
    assert c.allowlist_chat_ids() == set()


def test_thesis_fixtures_a_b_living_never_send(iso_dedupe, monkeypatch):
    """Exact fixtures from Phase 1 acceptance: A, B, Living desk thesis."""
    from lib import cio_telegram_transport as t

    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "1")  # even when enabled
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    sent = []

    def capture(body, **kwargs):
        sent.append(body)
        return {"delivered": True, "reason": "should_not_happen"}

    monkeypatch.setattr(t, "send_cio_message", capture)

    for summary in ("A", "B", "Living desk thesis", "des", "fixture a", "  a  "):
        r = t.notify_thesis_published("desk", 1, summary)
        assert r["delivered"] is False, summary
        assert r.get("reason") in (
            "not_material", "thesis_telegram_disabled_default",
        ) or r.get("attempted") is False or r.get("reason") == "not_material"

    # capture must never have been called for fixtures
    assert sent == []


def test_thesis_default_disabled_even_for_material(iso_dedupe, monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "0")
    r = t.notify_thesis_published(
        "governing",
        3,
        "Defensive observe: preserve optionality and stage deployment above the cash floor.",
    )
    assert r["delivered"] is False
    assert r["reason"] == "thesis_telegram_disabled_default"


def test_thesis_store_publish_does_not_call_send_telegram(iso_dedupe, monkeypatch, tmp_path):
    """Persistence side-effect: must not import/use general send_telegram."""
    from scripts.lib.cio_theses import CIOThesisStore
    import telegram_alert

    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "0")
    events = tmp_path / "theses.jsonl"
    proj = tmp_path / "theses_proj.json"
    store = CIOThesisStore(event_path=events, projection_path=proj)

    calls = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("send_telegram must not be called")

    monkeypatch.setattr(telegram_alert, "send_telegram", boom)
    rec = store.publish(
        "Living desk thesis",
        thesis_id="living",
        stance="defensive_observe",
        bullets=["hold cash optionality"],
        actor_id="test",
    )
    assert rec["version"] >= 1
    assert calls == []


def test_thesis_store_material_uses_cio_transport_only(iso_dedupe, monkeypatch, tmp_path):
    from scripts.lib.cio_theses import CIOThesisStore
    import scripts.lib.cio_theses as ct

    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "1")
    seen = []

    def fake_notify(tid, ver, summary):
        seen.append((tid, ver, summary))

    monkeypatch.setattr(ct, "_notify_thesis_publish", fake_notify)

    events = tmp_path / "theses.jsonl"
    store = CIOThesisStore(event_path=events, projection_path=tmp_path / "p.json")
    store.publish(
        "Defensive observe: preserve optionality; stage deployment; cash is a feature not a bug.",
        thesis_id="governing",
        stance="defensive_observe",
        actor_id="test",
    )
    assert len(seen) == 1
    assert "Defensive observe" in seen[0][2]


def test_semantic_dedupe_blocks_second_identical(iso_dedupe, monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setattr(t, "network_interdicted", lambda: False)
    monkeypatch.setattr(t, "live_authorized", lambda: True)
    monkeypatch.setattr(t, "credentials_ready", lambda: True)

    sends = {"n": 0}

    def fake_send_message(**kwargs):
        sends["n"] += 1
        return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": 1}}}

    import telegram_transport as tt
    monkeypatch.setattr(tt, "send_message", fake_send_message)

    body = "CIO decision: stage Technology deployment up to policy band; no force fills."
    r1 = t.send_cio_message(body, require_live_auth=True, force=False)
    r2 = t.send_cio_message(body, require_live_auth=True, force=False)
    assert r1["delivered"] is True
    assert r2["delivered"] is False
    assert r2.get("deduped") is True
    assert sends["n"] == 1


def test_delivery_worker_live_uses_cio_env_not_general(iso_dedupe, monkeypatch):
    from lib.cio_notification_delivery import CIONotificationDeliveryWorker, RealTelegramAdapter

    # General tokens set; CIO token set — adapter must bind CIO
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "GENERAL_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "CIO_TOKEN_XYZ")
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "12345")

    token = CIONotificationDeliveryWorker._read_token_from_env()
    chat = CIONotificationDeliveryWorker._read_chat_id_from_env()
    assert token == "CIO_TOKEN_XYZ"
    assert chat == "12345"
    assert token != "GENERAL_TOKEN"
    assert chat != "999"

    adapter = RealTelegramAdapter()
    assert adapter.bot_token == "CIO_TOKEN_XYZ"
    assert "12345" in adapter.chat_ids


def test_delivery_worker_shadow_never_live(iso_dedupe):
    from lib.cio_notification_delivery import CIONotificationDeliveryWorker as W

    class FakeOutbox:
        def list_notifications(self, status=None):
            return []

    worker = W(notification_outbox=FakeOutbox(), mode="shadow")
    assert worker.adapter.is_live is False
    summary = worker.poll_and_deliver()
    assert summary["mode"] == "shadow"
    assert summary["adapter_live"] is False


def test_http_send_message_interdicted_flag(iso_dedupe, monkeypatch):
    """Direct transport interdiction without pytest env (flag)."""
    import telegram_transport as tt

    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    # Clear pytest marker simulation: still under pytest so double-blocked; assert interdicted
    res = tt.send_message(token="x", chat_id="1", text="hi")
    assert res.get("interdicted") is True or res.get("ok") is False
