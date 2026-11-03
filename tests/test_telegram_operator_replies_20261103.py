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

from scripts.run_telegram_callback_poller import (_flush_operator_replies, _record_operator_reply)

ROOT = Path(__file__).resolve().parents[1]


def test_a_plain_operator_message_is_appended_with_id_and_time(tmp_path):
    recorded = _record_operator_reply({"message_id": 4242, "date": 1762267200}, "approve the restore",
                                      "12345", replies_dir=tmp_path, allowed={"12345"},
                                      chat_type="private", sender_id="12345")
    assert recorded == "recorded"
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
        _record_operator_reply({"message_id": i, "date": 0}, f"message {i}", "9", replies_dir=tmp_path,
                               chat_type="private", sender_id="9")
    recs = [json.loads(line) for line in (tmp_path / "telegram.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["message_id"] for r in recs] == [1, 2]


def test_only_the_operator_chat_is_recorded(tmp_path):
    assert _record_operator_reply({"message_id": 1}, "hi", "999", replies_dir=tmp_path,
                                  allowed={"123"}, chat_type="private", sender_id="999") == "refused_chat"
    assert not (tmp_path / "telegram.jsonl").exists()


def test_empty_or_blank_text_is_not_recorded(tmp_path):
    assert _record_operator_reply({"message_id": 1}, "", "123", replies_dir=tmp_path,
                                  chat_type="private", sender_id="123") == "blank"
    assert _record_operator_reply({"message_id": 2}, "   ", "123", replies_dir=tmp_path,
                                  chat_type="private", sender_id="123") == "blank"
    assert not (tmp_path / "telegram.jsonl").exists()


def test_a_broken_inbox_never_raises_and_queues_durably(tmp_path):
    """cx-openai-4 R2: an unwritable inbox must not lose the reply — it is queued before the checkpoint."""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    queue = tmp_path / "pending.jsonl"
    status = _record_operator_reply({"message_id": 1}, "hi", "1", replies_dir=blocker / "sub",
                                    chat_type="private", sender_id="1", pending_path=queue)
    assert status == "queued"
    assert json.loads(queue.read_text().splitlines()[0])["text"] == "hi"
    # The next poll flushes it into the inbox once the inbox is writable again.
    assert _flush_operator_replies(replies_dir=tmp_path / "inbox", pending_path=queue) == 1
    assert json.loads((tmp_path / "inbox" / "telegram.jsonl").read_text().splitlines()[0])["message_id"] == 1
    assert queue.read_text() == ""


def test_the_call_site_is_the_free_text_branch_before_the_responder():
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    assert "if not handled:" in src
    free_text = src.split("if not handled:", 1)[1]
    record_at = free_text.index("reply_status = _record_operator_reply(")
    responder_at = free_text.index("cio_poller_reply.maybe_answer")
    assert record_at < responder_at  # an answer that fails to compose cannot lose the message
    # and the record carries the SENDER, not only the room (R1)
    assert "chat_type=(msg.get(\"chat\") or {}).get(\"type\")" in free_text
    assert "sender_id=(msg.get(\"from\") or {}).get(\"id\")" in free_text


# ── R1: the ROOM is not the OPERATOR (cx-openai-4, 2026-11-03) ──────────────────────────────────────────
def test_a_group_chat_member_cannot_speak_as_the_operator(tmp_path):
    """Holding the allowed supergroup constant and changing the sender used to RECORD 1 and return True."""
    status = _record_operator_reply({"message_id": 7}, "approve the restore", "-100123", replies_dir=tmp_path,
                                    allowed={"-100123"}, chat_type="supergroup", sender_id="777")
    assert status == "refused_room"
    assert not (tmp_path / "telegram.jsonl").exists()


def test_a_missing_chat_type_is_refused(tmp_path):
    assert _record_operator_reply({"message_id": 8}, "hi", "123", replies_dir=tmp_path,
                                  chat_type=None, sender_id="123") == "refused_room"


def test_a_private_chat_from_a_different_sender_is_refused(tmp_path):
    """Even in a private chat, the sender must BE the operator chat, not merely be in an allowed room."""
    assert _record_operator_reply({"message_id": 9}, "hi", "123", replies_dir=tmp_path,
                                  chat_type="private", sender_id="999") == "refused_sender"
    assert _record_operator_reply({"message_id": 10}, "hi", "123", replies_dir=tmp_path,
                                  chat_type="private", sender_id=None) == "refused_sender"
    assert not (tmp_path / "telegram.jsonl").exists()


def test_nothing_recorded_or_queued_is_reported_as_failed_so_the_checkpoint_holds(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    status = _record_operator_reply({"message_id": 11}, "hi", "1", replies_dir=blocker / "sub",
                                    chat_type="private", sender_id="1",
                                    pending_path=blocker / "queue.jsonl")
    assert status == "failed"


def test_the_record_happens_before_the_checkpoint_commit():
    """R2 ordering: the reply is recorded/queued BEFORE _commit_if_legacy, and a failed record skips it."""
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    region = src.split("reply_status = _record_operator_reply(", 1)[1]
    record_call = src.index("reply_status = _record_operator_reply(")
    commit = src.index("_commit_if_legacy()", record_call)
    assert record_call < commit
    assert 'if reply_status == "failed":' in region
    after = region.split('if reply_status == "failed":', 1)[1].splitlines()
    assert any(line.strip() == "continue" for line in after[:3])
