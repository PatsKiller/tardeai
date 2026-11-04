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

import pytest

from scripts.run_telegram_callback_poller import (_flush_operator_replies, _record_operator_reply)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_host_operator_ids(monkeypatch):
    """The operator-id set must come from this test's allowlist, never from the host environment."""
    monkeypatch.delenv("TRADEAI_OPERATOR_FROM_IDS", raising=False)


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
                               allowed={"9"}, chat_type="private", sender_id="9")
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
                                    allowed={"1"}, chat_type="private", sender_id="1", pending_path=queue)
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
    # the copy sits before the inbound persist, which is where the ATOMIC checkpoint is committed (R2a)
    assert record_at < src.index("published = _persist_inbound_update(update)")
    assert "chat_type=(early_msg.get(\"chat\") or {}).get(\"type\")" in src[record_at:classify_at]
    assert "sender_id=(early_msg.get(\"from\") or {}).get(\"id\")" in src[record_at:classify_at]


# ── R1: the ROOM is not the OPERATOR (cx-openai-4, 2026-11-03) ──────────────────────────────────────────
def test_a_group_chat_member_cannot_speak_as_the_operator(tmp_path):
    """Holding the allowed supergroup constant and changing the sender used to RECORD 1 and return True.

    Settled rule: the SENDER must be an operator user id (market_risk_ack_telegram.operator_from_ids), so a
    member whose id is not an operator is refused even though the room is allowlisted.
    """
    status = _record_operator_reply({"message_id": 7}, "approve the restore", "-100123", replies_dir=tmp_path,
                                    allowed={"-100123"}, chat_type="supergroup", sender_id="777")
    assert status == "refused_sender"
    assert not (tmp_path / "telegram.jsonl").exists()


def test_a_group_message_from_the_operator_id_is_the_operator(tmp_path, monkeypatch):
    """Identity, not room: the operator speaking in a group is still the operator when his id is configured."""
    monkeypatch.setenv("TRADEAI_OPERATOR_FROM_IDS", "123")
    status = _record_operator_reply({"message_id": 12}, "approve the restore", "-100123", replies_dir=tmp_path,
                                    allowed={"-100123"}, chat_type="supergroup", sender_id="123")
    assert status == "recorded"


def test_a_missing_chat_type_does_not_by_itself_block_the_operator_id(tmp_path):
    """Auth is the sender id; the chat type is context, and its absence must not silently widen anything."""
    assert _record_operator_reply({"message_id": 8}, "hi", "123", replies_dir=tmp_path,
                                  allowed={"123"}, chat_type=None, sender_id="123") == "recorded"
    assert _record_operator_reply({"message_id": 9}, "hi", "123", replies_dir=tmp_path,
                                  allowed={"123"}, chat_type=None, sender_id="999") == "refused_sender"


def test_a_private_chat_from_a_different_sender_is_refused(tmp_path):
    """In a private chat the operator id is the chat id (operator_from_ids' default), so a foreign sender fails."""
    assert _record_operator_reply({"message_id": 9}, "hi", "123", replies_dir=tmp_path,
                                  chat_type="private", sender_id="999") == "refused_sender"
    assert _record_operator_reply({"message_id": 10}, "hi", "123", replies_dir=tmp_path,
                                  chat_type="private", sender_id=None) == "refused_sender"
    assert not (tmp_path / "telegram.jsonl").exists()


def test_nothing_recorded_or_queued_is_reported_as_failed_so_the_checkpoint_holds(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    status = _record_operator_reply({"message_id": 11}, "hi", "1", replies_dir=blocker / "sub",
                                    allowed={"1"}, chat_type="private", sender_id="1",
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
    assert any(line.strip() == "break" for line in after[:6])   # stops the BATCH, not just this update (R2b)


def test_an_outcome_line_pairs_with_the_message_line(tmp_path):
    """F3: a handled command leaves a message line AND an outcome line, paired by message_id."""
    from scripts.run_telegram_callback_poller import _record_operator_outcome
    _record_operator_reply({"message_id": 77}, "approve the restore code=abc", "555",
                           replies_dir=tmp_path, allowed={"555"}, chat_type="private", sender_id="555")
    _record_operator_outcome({"message_id": 77}, "approve the restore code=abc", "555", handled=True,
                             replies_dir=tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "telegram.jsonl").read_text().splitlines()]
    assert rows[0]["message_id"] == 77 and "event" not in rows[0]
    assert rows[1]["event"] == "outcome" and rows[1]["message_id"] == 77 and rows[1]["handled"] is True
    # 2026-11-04 (#2533 follow-up): the value of a credential-bearing parameter is redacted at the write boundary,
    # in BOTH lines of the pair. This assertion used to pin the raw value to the inbox — i.e. it encoded the leak.
    assert rows[1]["text"] == "approve the restore code=[redacted]"
    assert rows[0]["text"] == "approve the restore code=[redacted]"
    assert "code=abc" not in (tmp_path / "telegram.jsonl").read_text()


def test_a_malformed_envelope_or_unknown_sender_is_refused_not_written(tmp_path):
    """cx-openai-3 F2: a fallback path must not write a line with null provenance."""
    assert _record_operator_reply({}, "hi", "555", replies_dir=tmp_path, allowed={"555"},
                                  chat_type="private", sender_id=None) == "refused_sender"
    assert _record_operator_reply({"message_id": 1}, "hi", "555", replies_dir=tmp_path, allowed={"555"},
                                  chat_type="private", sender_id="999") == "refused_sender"
    assert not (tmp_path / "telegram.jsonl").exists()


# ── R2a/R2b: the ATOMIC path (cx-openai-4) ───────────────────────────────────────────────────────────────
import io as _io
import urllib.request as _urllib_request


class _Resp(_io.BytesIO):
    pass


def _drive_updates(monkeypatch, tmp_path, updates, *, inbox_blocked: bool, queue_blocked: bool, atomic: bool):
    """Drive poll_once with a fake update source; returns (commits, records, queued)."""
    from scripts import run_telegram_callback_poller as P

    replies = tmp_path / "replies"
    queue = tmp_path / "pending.jsonl"
    if inbox_blocked:
        replies.write_text("x")
    if queue_blocked:
        queue.parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "pending_dir").write_text("x")
        queue = tmp_path / "pending_dir" / "pending.jsonl"
    commits = []
    inbound = {
        "claim_update": lambda u: type("C", (), {"already_processed": False})(),
        "quarantine_callback": lambda *a, **k: None,
        "commit_checkpoint": lambda u: commits.append(u),
        "get_checkpoint_offset": lambda: 0,
    }
    monkeypatch.setattr(P, "_token", lambda: "tok")
    monkeypatch.setattr(P, "_allowed_chats", lambda: {"555"})
    monkeypatch.setattr(P, "_inbound_api", lambda: inbound)
    monkeypatch.setattr(P, "_persist_inbound_update",
                        lambda u: (commits.append(u.get("update_id")) or type("R", (), {"ok": True})()))
    monkeypatch.setattr(P, "atomic_inbound_enabled", lambda env=None: atomic)
    monkeypatch.setattr(P, "_operator_replies_dir", lambda: replies)
    monkeypatch.setattr(P, "_operator_replies_pending_path", lambda: queue)
    monkeypatch.setattr(_urllib_request, "urlopen",
                        lambda req, timeout=None: _Resp(json.dumps({"ok": True, "result": updates}).encode()))
    monkeypatch.setattr(P.urllib.request, "urlopen", _urllib_request.urlopen)
    P.poll_once(timeout=0)
    inbox = replies / "telegram.jsonl"
    return commits, (inbox.read_text().splitlines() if inbox.exists() else []), (queue.read_text() if queue.exists() else "")


def _msg(uid, mid, text="approve the restore", sender="555", chat="555", chat_type="private"):
    return {"update_id": uid, "message": {"message_id": mid, "date": 1762267200, "text": text,
                                          "chat": {"id": chat, "type": chat_type}, "from": {"id": sender}}}


def test_atomic_path_does_not_commit_when_the_handoff_fails(tmp_path, monkeypatch):
    """R2a: process_update_atomically commits inside the persist call, so the handoff must precede it."""
    commits, records, queued = _drive_updates(monkeypatch, tmp_path, [_msg(901, 1)], inbox_blocked=True,
                                              queue_blocked=True, atomic=True)
    assert commits == []          # the atomic commit never ran (it would be appended by _persist_inbound_update)
    assert records == [] and queued == ""


def test_a_queued_handoff_allows_the_atomic_commit(tmp_path, monkeypatch):
    commits, records, queued = _drive_updates(monkeypatch, tmp_path, [_msg(902, 2)], inbox_blocked=True,
                                              queue_blocked=False, atomic=True)
    assert commits == [902]       # durable in the queue, so the checkpoint may advance
    assert queued.strip()         # message + outcome lines
    assert records == []


def test_a_failed_handoff_stops_the_batch_so_a_later_update_cannot_stride_over_it(tmp_path, monkeypatch):
    """R2b: update 904 must not be committed after update 903's reply failed to become durable."""
    commits, records, queued = _drive_updates(monkeypatch, tmp_path, [_msg(903, 3), _msg(904, 4, text="second message")],
                                              inbox_blocked=True, queue_blocked=True, atomic=False)
    assert commits == []
    assert records == [] and queued == ""


# ── credential redaction at the persistence boundary (2026-11-04, #2533 follow-up) ────────────────────


def test_a_pasted_oauth_redirect_is_redacted_everywhere_it_is_written(tmp_path):
    """The handler still receives the raw text; the inbox and the queue never see the code."""
    from scripts.run_telegram_callback_poller import _record_operator_reply, _record_operator_outcome, redact_credentials
    paste = "127.0.0.1?code=S3CR3T-oauth-code&state=abc"
    raw = "https://" + paste
    assert _record_operator_reply({"message_id": 91}, raw, "555", replies_dir=tmp_path, allowed={"555"},
                                  chat_type="private", sender_id="555") == "recorded"
    _record_operator_outcome({"message_id": 91}, raw, "555", handled=True, replies_dir=tmp_path)
    written = (tmp_path / "telegram.jsonl").read_text()
    assert "S3CR3T-oauth-code" not in written, written
    assert "code=[redacted]" in written and "state=abc" in written   # the value goes, the rest of the URL stays
    assert redact_credentials(raw).endswith("code=[redacted]&state=abc")


def test_redaction_is_narrow_and_never_mangles_ordinary_prose():
    from scripts.run_telegram_callback_poller import redact_credentials
    for text in ("the code= path is under review", "token budget is 240", "approve the restore",
                 "please re-read WORKERS.md and continue"):
        assert redact_credentials(text) == text
    # the credential parameters we claim to catch, case-insensitively, in a query string or a form paste
    for key in ("code", "access_token", "refresh_token", "id_token", "api_key", "client_secret", "password", "token"):
        assert redact_credentials(f"{key}=VALUE123") == f"{key}=[redacted]"
