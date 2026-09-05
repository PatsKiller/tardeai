#!/usr/bin/env python3
"""Rich telegram_alert APIs keep keyboards/documents on the approved chokepoint."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_send_telegram_passes_reply_markup_to_transport(monkeypatch):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    seen = {}

    def fake_send_message(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "status_code": 200, "message_id": 1}

    monkeypatch.setattr(ta, "send_message", fake_send_message)
    kb = {"inline_keyboard": [[{"text": "A", "callback_data": "a"}]]}
    assert ta.send_telegram("hello", bypass_router=True, reply_markup=kb) is True
    assert seen.get("reply_markup") == kb
    assert seen.get("chat_id") == "123"


def test_send_telegram_document_uses_transport(monkeypatch, tmp_path):
    import telegram_alert as ta

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    f = tmp_path / "r.pdf"
    f.write_bytes(b"%PDF")
    seen = {}

    def fake_send_document(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "status_code": 200, "message_id": 9}

    monkeypatch.setattr(ta, "send_document", fake_send_document)
    assert ta.send_telegram_document(str(f), caption="cap") is True
    assert seen.get("file_path") == str(f)
    assert seen.get("caption") == "cap"
