"""Typed operator replies reach the coordinator (operator request #7, 2026-11-03).

The poller already owns the bot's getUpdates consumer, so a second poller would steal updates from
it and break the working callback buttons. The fix extends the existing loop: a plain-text message
from the operator's chat is appended to the coordinator inbox with its message id and timestamps.
These tests exercise the append helper and the call site; no network, no live service.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.run_telegram_callback_poller import _record_operator_reply

ROOT = Path(__file__).resolve().parents[1]


def test_a_plain_operator_message_is_appended_with_id_and_time(tmp_path):
    recorded = _record_operator_reply({"message_id": 4242, "date": 1762267200}, "approve the restore",
                                      "12345", replies_dir=tmp_path, allowed={"12345"})
    assert recorded is True
    lines = (tmp_path / "telegram.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["message_id"] == 4242
    assert rec["date"] == 1762267200
    assert rec["chat_id"] == "12345"
    assert rec["text"] == "approve the restore"
    parsed = datetime.fromisoformat(rec["recorded_at"])
    assert parsed.tzinfo is not None  # an unambiguous, UTC-stamped record


def test_appends_and_never_truncates(tmp_path):
    for i in (1, 2):
        _record_operator_reply({"message_id": i, "date": 0}, f"message {i}", "9", replies_dir=tmp_path)
    recs = [json.loads(line) for line in (tmp_path / "telegram.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["message_id"] for r in recs] == [1, 2]


def test_only_the_operator_chat_is_recorded(tmp_path):
    assert _record_operator_reply({"message_id": 1}, "hi", "999", replies_dir=tmp_path,
                                  allowed={"123"}) is False
    assert not (tmp_path / "telegram.jsonl").exists()


def test_empty_or_blank_text_is_not_recorded(tmp_path):
    assert _record_operator_reply({"message_id": 1}, "", "123", replies_dir=tmp_path) is False
    assert _record_operator_reply({"message_id": 2}, "   ", "123", replies_dir=tmp_path) is False
    assert not (tmp_path / "telegram.jsonl").exists()


def test_a_broken_inbox_never_raises(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    assert _record_operator_reply({"message_id": 1}, "hi", "1",
                                  replies_dir=blocker / "sub") is False


def test_the_call_site_is_the_free_text_branch_before_the_responder():
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    assert "if not handled:" in src
    free_text = src.split("if not handled:", 1)[1]
    record_at = free_text.index("_record_operator_reply(msg, text, chat_id, allowed=allowed)")
    responder_at = free_text.index("cio_poller_reply.maybe_answer")
    assert record_at < responder_at  # an answer that fails to compose cannot lose the message
