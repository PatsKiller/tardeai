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
    outcome_at = src.index("_record_operator_outcome(msg, text, chat_id, handled=handled")
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
    # "the code= path …" NOW redacts "path": a keyed value ends at whitespace by design, which is what makes
    # `password=synth123 thanks` and `code=synth123 please retry` safe. Prose that names no credential key is untouched.
    for text in ("token budget is 240", "approve the restore", "please re-read WORKERS.md and continue"):
        assert redact_credentials(text) == text
    assert redact_credentials("the code= path is under review") == "the code= [redacted] is under review"
    # the credential parameters we claim to catch, case-insensitively, in a query string or a form paste
    for key in ("code", "access_token", "refresh_token", "id_token", "api_key", "client_secret", "password", "token"):
        assert redact_credentials(f"{key}=VALUE123") == f"{key}=[redacted]"


# ── behavioural F3: the pair is produced by the real poll loop, not by calling the writers directly ──


def test_a_command_through_poll_once_leaves_a_paired_outcome_line(tmp_path, monkeypatch):
    """The source-text test asserts the call site exists; this drives it. A handled command must leave BOTH lines,
    paired by message_id, with the outcome saying it was handled — and only then may the checkpoint advance."""
    from scripts import run_telegram_callback_poller as P
    handled_calls = []
    monkeypatch.setattr(P, "_handle_proposal_command", lambda msg, text, chat_id: handled_calls.append(text))
    commits, records, _ = _drive_updates(monkeypatch, tmp_path,
                                         [_msg(910, 5, text="/ptapprove 42")],
                                         inbox_blocked=False, queue_blocked=False, atomic=True)
    rows = [json.loads(line) for line in records]
    assert len(rows) == 2, rows
    assert rows[0]["message_id"] == 5 and "event" not in rows[0]
    assert rows[1]["event"] == "outcome" and rows[1]["message_id"] == 5 and rows[1]["handled"] is True
    assert handled_calls == ["/ptapprove 42"]
    assert commits == [910]          # the durable checkpoint advanced only after the pair was written


def test_a_plain_message_through_poll_once_is_recorded_as_not_handled(tmp_path, monkeypatch):
    commits, records, _ = _drive_updates(monkeypatch, tmp_path, [_msg(911, 6, text="please re-read WORKERS.md")],
                                         inbox_blocked=False, queue_blocked=False, atomic=True)
    rows = [json.loads(line) for line in records]
    assert rows[0]["text"] == "please re-read WORKERS.md" and "event" not in rows[0]
    assert rows[1]["event"] == "outcome" and rows[1]["handled"] is False
    assert commits == [911]


# ── cx-openai-2 F1/F2/F3 (2026-11-04): every sink, every encoding, no split fragment ──────────────────

_SECRET = "S3CR3T-oauth-CODE-9911"
_FORMS = [
    ("query", f"127.0.0.1?code={_SECRET}&state=abc"),
    ("json", '{"code": "%s"}' % _SECRET),
    ("json_compact", '"code":"%s"' % _SECRET),
    ("json_single_quotes", "{'code': '%s'}" % _SECRET),
    ("spaced_equals", f"code = {_SECRET}"),
    ("colon", f"code: {_SECRET}"),
    ("form", f"code={_SECRET}&state=abc"),
    ("other_key", f"client_secret={_SECRET}"),
]


@pytest.mark.parametrize("name,paste", _FORMS, ids=[f[0] for f in _FORMS])
def test_f2_every_encoding_is_redacted_at_the_inbox_and_the_queue(tmp_path, name, paste):
    """F2, through the REAL sin, not the helper: the inbox line and the queued line must both be clean."""
    from scripts.run_telegram_callback_poller import _append_or_queue
    assert _append_or_queue({"message_id": 1, "text": paste}, replies_dir=tmp_path) == "recorded"
    written = (tmp_path / "telegram.jsonl").read_text()
    assert _SECRET not in written, (name, written)
    assert "[redacted]" in written, (name, written)
    # the durable queue takes the same line: a failed inbox write must not be the weak sink
    queue = tmp_path / "pending" / "queue.jsonl"
    assert _append_or_queue({"message_id": 2, "text": paste},
                            replies_dir=tmp_path / "blocked", pending_path=queue) in ("recorded", "queued")
    for line in queue.read_text().splitlines() if queue.exists() else []:
        assert _SECRET not in line, (name, line)


def test_f2_ordinary_prose_keeps_its_text():
    """The narrowness that makes the redactor usable: the operator's own words survive."""
    from scripts.run_telegram_callback_poller import redact_credentials
    for text in ("the token budget grew", "approve the restore", "please re-read WORKERS.md and continue"):
        assert redact_credentials(text) == text, text
    # a keyed value ends at whitespace, so naming a key costs the next word — the documented price of catching
    # `code=synth123 please retry`
    assert redact_credentials("the code: path is under review") == "the code: [redacted] is under review"


def test_f3_a_credential_straddling_the_truncation_point_leaves_no_fragment():
    """F3: truncating before redacting cut the secret in half and kept the half. Redact, then truncate."""
    from scripts.run_telegram_callback_poller import _log_text
    paste = "x" * 8 + f"?code={_SECRET}"          # the credential sits INSIDE the 40-character window
    shown = _log_text(paste, 40)
    assert _SECRET[:3] not in shown, shown          # not even a prefix of the value survives
    assert "[red" in shown, shown                   # the marker itself may be cut by the limit; the value may not


def test_f1_no_log_site_slices_raw_operator_text():
    """F1: a source guard for the whole file — a fifth log site added later must use _log_text, not a raw slice."""
    from pathlib import Path as _P
    source = (_P(__file__).resolve().parents[1] / "scripts" / "run_telegram_callback_poller.py").read_text()
    assert "text[:40]" not in source and "text[:80]" not in source, "raw operator text reaches a log slice"
    # R6-F1: a log line that echoes operator text must render the SANITISED text, from the same context as its rows —
    # `_log_text(...)` or `redact_credentials(...)`. A raw `{text` interpolation is the defect.
    for line in source.splitlines():
        if "log." in line and "{text" in line:
            raise AssertionError(f"raw operator text reaches a log line: {line.strip()}")
    assert source.count("_log_text(") >= 7, "every log site that echoes operator text must use _log_text"


# ── the two remaining P1s at aec6fe0d7 (2026-11-04) ───────────────────────────────────────────────────


def test_a_quoted_value_containing_its_own_other_quote_is_fully_redacted(tmp_path):
    """R2-F1 (cx3): `:203` rejected EITHER quote inside a quoted value, so a JSON password containing an apostrophe
    survived byte-for-byte. Fails at aec6fe0d7."""
    from scripts.run_telegram_callback_poller import _append_or_queue, redact_credentials
    raw = '{"password": "SYNTHETIC can\'t conceal tail"}'
    assert "conceal tail" not in redact_credentials(raw)
    assert _append_or_queue({"message_id": 7, "text": raw}, replies_dir=tmp_path) == "recorded"
    written = (tmp_path / "telegram.jsonl").read_text()
    assert "conceal tail" not in written, written


def test_a_json_escaped_quote_inside_a_value_does_not_leak_the_tail(tmp_path):
    """R2-F1: `json.dumps` produces an escaped quote inside the value; the redaction used to emit
    `{"code": "[redacted]"TAIL-REMAINS"}` and the suffix survived every sink. Fails at aec6fe0d7."""
    import json as _json  # noqa: PLC0415
    from scripts.run_telegram_callback_poller import _append_or_queue, redact_credentials
    raw = _json.dumps({"code": 'a"bTAIL-REMAINS'})
    assert "TAIL-REMAINS" not in redact_credentials(raw), redact_credentials(raw)
    assert _append_or_queue({"message_id": 8, "text": raw}, replies_dir=tmp_path) == "recorded"
    assert "TAIL-REMAINS" not in (tmp_path / "telegram.jsonl").read_text()


def test_a_credential_arriving_as_its_own_message_is_redacted(tmp_path):
    """R1 (cc5): the second half of F3. When the transport splits a paste, the value arrives as its own message with
    no key. It used to be stored and logged raw. Fails at aec6fe0d7."""
    from scripts.run_telegram_callback_poller import _append_or_queue
    standalone = "S3CR3T0oauth0CODE09911continued"
    assert _append_or_queue({"message_id": 9, "text": standalone}, replies_dir=tmp_path,
                            previous_text="127.0.0.1?code=") == "recorded"
    written = (tmp_path / "telegram.jsonl").read_text()
    assert "S3CR3T0oauth0CODE09911" not in written, written
    assert "[redacted]" in written


def test_ordinary_prose_is_still_not_mistaken_for_a_standalone_credential():
    """The quiet half: a long sentence, a file path and a command are not opaque tokens."""
    from scripts.run_telegram_callback_poller import redact_credentials
    for text in ("please re-read WORKERS.md and continue", "approve the restore",
                 "tradeai-wt-example", "git push origin HEAD:wt/example"):
        assert redact_credentials(text) == text, text


def test_a_split_paste_value_under_24_chars_is_redacted(tmp_path):
    """cc5 (2026-11-04): the standalone floor was 24 and the R1 reproducer is 20 characters — a plausible Schwab
    authorization code. Fails at 48a6d44cceb2."""
    from scripts.run_telegram_callback_poller import _record_operator_reply
    from scripts.run_telegram_callback_poller import _append_or_queue
    value = "AbCdEf1234567890XyZq"
    assert len(value) == 20
    # the value alone carries no evidence; the PREVIOUS message ending in `code=` does (cc5's case, closed by context)
    assert _append_or_queue({"message_id": 11, "text": value}, replies_dir=tmp_path,
                            previous_text="https://127.0.0.1/?code=") == "recorded"
    written = (tmp_path / "telegram.jsonl").read_text()
    assert value not in written, written


def test_a_value_after_a_key_bearing_message_is_redacted_at_any_length(tmp_path):
    """The context rule: the evidence for a split paste is the PREVIOUS message ending in a key and separator, not the
    value's length. Fails at 48a6d44cceb2."""
    from scripts.run_telegram_callback_poller import redact_credentials
    assert redact_credentials("AbCd", previous="127.0.0.1?code=") == "[redacted]"
    assert redact_credentials("AbCd", previous="please approve the restore") == "AbCd"


def test_a_fact_the_operator_is_answering_with_is_never_redacted(tmp_path):
    """cx-openai-3 (2026-11-04): the shape heuristic erased SHAs, hashes, paths, filenames and version strings — the
    operator's actual answer — silently, with no warning. Nothing without a credential key is a credential now.
    Fails at 48a6d44cc."""
    from scripts.run_telegram_callback_poller import redact_credentials
    for fact in ("0123456789abcdef0123456789abcdef01234567",
                 "d41d8cd98f00b204e9800998ecf8427e",
                 "docs/designs/DSN-20261104-operator-replies.md",
                 "UmVjb3ZlcnktcmV2aWV3LTI1Nzk=.txt",
                 "v2026.11.04-recovery-round-4",
                 "review-2579-fix-poller-redaction"):
        assert redact_credentials(fact) == fact, fact


# ── the rule must be WIRED, not merely correct (cc5, 2026-11-04) ─────────────────────────────────────


def test_a_split_paste_through_the_REAL_poll_path_never_reaches_the_inbox(tmp_path, monkeypatch):
    """The control is the poller's own entry point, not _append_or_queue with a keyword the tests invented.

    Two updates in one poll: the first ends with `code=`, the second is the 20-character value a transport split off.
    At 67b219277b5a the keyword existed but no call site passed it, so the bare token was stored and logged.
    """
    value = "AbCdEf1234567890XyZq"
    commits, records, queued = _drive_updates(
        monkeypatch, tmp_path,
        [_msg(921, 7, text="127.0.0.1?code="), _msg(922, 8, text=value)],
        inbox_blocked=False, queue_blocked=False, atomic=True)
    assert commits == [921, 922]
    blob = "\n".join(records) + "\n" + (queued or "")
    assert value not in blob, blob
    assert "[redacted]" in blob


def test_with_no_previous_message_the_ambiguity_is_recorded_not_guessed(tmp_path):
    """The fallback, named: a first message after a restart has no context to consult. The value is stored (deleting on
    a guess is what erased the operator's SHAs) and the record SAYS it was not fully redacted."""
    from scripts.run_telegram_callback_poller import _append_or_queue
    import json as _json  # noqa: PLC0415
    assert _append_or_queue({"message_id": 12, "text": "AbCdEf1234567890XyZq"}, replies_dir=tmp_path) == "recorded"
    row = _json.loads((tmp_path / "telegram.jsonl").read_text().splitlines()[0])
    assert row["text"] == "AbCdEf1234567890XyZq" and row.get("redaction_incomplete") is True, row


def test_an_innocent_colon_does_not_redact_the_next_reply(tmp_path, monkeypatch):
    """R5-F2: the trailing-key matcher had no key boundary, so 'Please review the source code:' (and 'The field is
    zipcode:', 'The field is status code:') made the NEXT ordinary reply [redacted]. Fails at eb11cd3af62ae."""
    commits, records, _ = _drive_updates(
        monkeypatch, tmp_path,
        [_msg(931, 9, text="Please review the source code:"), _msg(932, 10, text="503 retry only; do not deploy")],
        inbox_blocked=False, queue_blocked=False, atomic=True)
    assert commits == [931, 932]
    assert "503 retry only; do not deploy" in "\n".join(records)


def test_a_json_split_paste_is_protected(tmp_path, monkeypatch):
    """The opposite gap: '{"code": ' did not match at all, so that split paste stayed unprotected even once context
    was supplied. Fails at eb11cd3af62ae."""
    value = "AbCdEf1234567890XyZq"
    commits, records, _ = _drive_updates(
        monkeypatch, tmp_path,
        [_msg(941, 11, text='{"code": '), _msg(942, 12, text=value)],
        inbox_blocked=False, queue_blocked=False, atomic=True)
    assert commits == [941, 942]
    assert value not in "\n".join(records)


def test_the_six_identifiers_still_pass_through_the_real_poll_path(tmp_path, monkeypatch):
    """Tightening a matcher is how the identifier loss reopens: the six facts cx3 listed must survive poll_once."""
    facts = ["0123456789abcdef0123456789abcdef01234567", "d41d8cd98f00b204e9800998ecf8427e",
             "docs/designs/DSN-20261104-operator-replies.md", "UmVjb3ZlcnktcmV2aWV3LTI1Nzk=.txt",
             "v2026.11.04-recovery-round-4", "review-2579-fix-poller-redaction"]
    updates = [_msg(950 + i, 20 + i, text=f) for i, f in enumerate(facts)]
    commits, records, _ = _drive_updates(monkeypatch, tmp_path, updates,
                                         inbox_blocked=False, queue_blocked=False, atomic=True)
    blob = "\n".join(records)
    for f in facts:
        assert f in blob, f
    assert "[redacted]" not in blob


def test_a_split_paste_row_carries_a_marker_not_the_credential(tmp_path):
    """The context is never persisted as text: a redacted continuation row is marked, so a restart or a queue flush
    carries no raw credential. Tested at the durable record."""
    import json as _json  # noqa: PLC0415
    from scripts.run_telegram_callback_poller import _append_or_queue, REDACTION_CONTEXT
    assert _append_or_queue({"message_id": 13, "text": "AbCdEf1234567890XyZq"}, replies_dir=tmp_path,
                            previous_text="127.0.0.1?code=") == "recorded"
    row = _json.loads((tmp_path / "telegram.jsonl").read_text().splitlines()[0])
    assert row["text"] == "[redacted]" and row.get("redaction_context") == REDACTION_CONTEXT, row


def test_the_incomplete_redaction_marker_has_a_consumer(tmp_path, caplog):
    """cc5 (2026-11-04): a flag nothing reads is 'stored silently' renamed. The poller log is the operator surface, so
    the warning must actually be emitted for a row that carries the marker."""
    import logging as _logging  # noqa: PLC0415
    from scripts.run_telegram_callback_poller import _append_or_queue
    with caplog.at_level(_logging.WARNING):
        assert _append_or_queue({"message_id": 14, "text": "AbCdEf1234567890XyZq"}, replies_dir=tmp_path) == "recorded"
    assert any("UNVERIFIED-REDACTION" in r.message for r in caplog.records), [r.message for r in caplog.records]


def test_the_split_paste_does_not_reach_the_ACTUAL_LOG(tmp_path, monkeypatch, caplog):
    """R6-F1 (cx-openai-3, 2026-11-04): the rows were correct and the log printed the raw value. A test that inspects
    only the rows passed at 31f82894be20; this one asserts on the captured log."""
    import logging as _logging  # noqa: PLC0415
    value = "AbCdEf1234567890XyZq"
    with caplog.at_level(_logging.INFO):
        _drive_updates(monkeypatch, tmp_path,
                       [_msg(961, 30, text='{"code": '), _msg(962, 31, text=value)],
                       inbox_blocked=False, queue_blocked=False, atomic=True)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert value not in logged, logged


def test_a_refused_group_member_cannot_set_or_clear_the_operator_context(tmp_path, monkeypatch):
    """R6-F2 (cx3, 2026-11-04): the context was keyed by ROOM and advanced after the record attempt regardless of
    authentication, so an outsider in an allowlisted supergroup could (1) make the operator's next reply [redacted] and
    (2) clear a real credential predecessor and let the credential through raw. Fails at 0b60520c7cda."""
    value = "AbCdEf1234567890XyZq"
    # (1) outsider's refused key prefix must NOT become the operator's predecessor
    _c, records, _q = _drive_updates(
        monkeypatch, tmp_path,
        [_msg(971, 40, text='{"code": ', sender="999"),
         _msg(972, 41, text="503 retry only; do not deploy", sender="555")],
        inbox_blocked=False, queue_blocked=False, atomic=True)
    blob = "\n".join(records)
    assert "503 retry only; do not deploy" in blob, blob

    # (2) outsider's refused ordinary text must NOT clear the operator's key-bearing predecessor
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    _c2, records2, _q2 = _drive_updates(
        monkeypatch, tmp2,
        [_msg(973, 42, text='{"code": ', sender="555"),
         _msg(974, 43, text="hello there", sender="999"),
         _msg(975, 44, text=value, sender="555")],
        inbox_blocked=False, queue_blocked=False, atomic=True)
    assert value not in "\n".join(records2), "\n".join(records2)
