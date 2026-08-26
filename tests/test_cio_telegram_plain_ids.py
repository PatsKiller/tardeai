"""CIO Telegram must not Markdown-eat decision_id underscores."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_telegram_transport as tg
from scripts.telegram_transport import send_message


def test_send_message_accepts_parse_mode_none():
    sig = inspect.signature(send_message)
    assert "parse_mode" in sig.parameters


def test_cio_send_passes_plain_parse_mode(monkeypatch):
    seen = {}

    def fake_send_message(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "response": {"ok": True, "result": {"message_id": 1}}}

    monkeypatch.setattr("telegram_transport.send_message", fake_send_message)
    monkeypatch.setattr(tg, "network_interdicted", lambda: False)
    monkeypatch.setattr(tg, "live_authorized", lambda: True)
    monkeypatch.setattr(tg, "credentials_ready", lambda: True)
    monkeypatch.setattr(tg, "cio_bot_token", lambda: "t")
    monkeypatch.setattr(tg, "cio_chat_ids", lambda: ["1"])
    monkeypatch.setattr(tg, "was_recently_sent", lambda *a, **k: False)
    monkeypatch.setattr(tg, "mark_sent", lambda *a, **k: None)
    res = tg.send_cio_message(
        "Decision: dec_5866156741de9046 ACT_NOW",
        require_live_auth=True,
        decision_id="dec_5866156741de9046",
    )
    assert res.get("delivered") is True
    assert seen.get("parse_mode") is None
    assert "dec_5866156741de9046" in seen.get("text", "")


def test_cio_send_passes_html_parse_mode(monkeypatch):
    seen = {}

    def fake_send_message(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "response": {"ok": True, "result": {"message_id": 2}}}

    monkeypatch.setattr("telegram_transport.send_message", fake_send_message)
    monkeypatch.setattr(tg, "network_interdicted", lambda: False)
    monkeypatch.setattr(tg, "live_authorized", lambda: True)
    monkeypatch.setattr(tg, "credentials_ready", lambda: True)
    monkeypatch.setattr(tg, "cio_bot_token", lambda: "t")
    monkeypatch.setattr(tg, "cio_chat_ids", lambda: ["1"])
    monkeypatch.setattr(tg, "was_recently_sent", lambda *a, **k: False)
    monkeypatch.setattr(tg, "mark_sent", lambda *a, **k: None)
    res = tg.send_cio_message(
        "⚪ <b>CIO book update</b>",
        require_live_auth=True,
        parse_mode="HTML",
    )
    assert res.get("delivered") is True
    assert seen.get("parse_mode") == "HTML"
