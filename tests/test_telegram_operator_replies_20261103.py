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


def test_the_record_happens_before_classification_and_before_the_responder():
    """F3: a handled command must still leave a coordinator copy, so the record precedes the branches."""
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    record_at = src.index("reply_status = _record_operator_reply(")
    classify_at = src.index("# Route all recognized commands")
    responder_at = src.index("cio_poller_reply.maybe_answer")
    outcome_at = src.index("_record_operator_outcome(msg, text, chat_id, handled=handled)")
    commit_at = src.index("_commit_if_legacy()", record_at)
    assert record_at < classify_at < outcome_at < responder_at
    assert record_at < commit_at
    assert "chat_type=(msg.get(\"chat\") or {}).get(\"type\")" in src[record_at:classify_at]
    assert "sender_id=(msg.get(\"from\") or {}).get(\"id\")" in src[record_at:classify_at]


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


def test_an_outcome_line_pairs_with_the_message_line(tmp_path):
    """F3: a handled command leaves a message line AND an outcome line, paired by message_id."""
    from scripts.run_telegram_callback_poller import _record_operator_outcome
    _record_operator_reply({"message_id": 77}, "approve the restore code=abc", "555",
                           replies_dir=tmp_path, chat_type="private", sender_id="555")
    _record_operator_outcome({"message_id": 77}, "approve the restore code=abc", "555", handled=True,
                             replies_dir=tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "telegram.jsonl").read_text().splitlines()]
    assert rows[0]["message_id"] == 77 and "event" not in rows[0]
    assert rows[1]["event"] == "outcome" and rows[1]["message_id"] == 77 and rows[1]["handled"] is True
    assert rows[1]["text"] == "approve the restore code=abc"


def test_a_malformed_envelope_or_unknown_sender_is_refused_not_written(tmp_path):
    """cx-openai-3 F2: a fallback path must not write a line with null provenance."""
    assert _record_operator_reply({}, "hi", "555", replies_dir=tmp_path,
                                  chat_type="private", sender_id=None) == "refused_sender"
    assert _record_operator_reply({"message_id": 1}, "hi", "555", replies_dir=tmp_path,
                                  chat_type="private", sender_id="999") == "refused_sender"
    assert not (tmp_path / "telegram.jsonl").exists()
