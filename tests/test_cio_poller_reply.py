#!/usr/bin/env python3
"""The operator asks in free text and gets an answer — on the bot that was asked.

Fake transport, no network, no DB. The regression that motivates the whole
design is test 3: `send_cio_message` discards chat_id and fans out to a
DIFFERENT bot token, so an answer composed correctly could still arrive in the
wrong room from the wrong bot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import cio_poller_reply as R  # noqa: E402

GENERAL_TOKEN = "8653682012:AA-general-bot"
CIO_TOKEN = "8751620457:AA-cio-bot"
CHAT = "12345"
MSG = {"message_id": 777, "chat": {"id": int(CHAT)}, "from": {"id": 9, "username": "op"}}


class FakeTransport:
    def __init__(self):
        self.sends: list[dict] = []

    def send_message(self, **kw):
        self.sends.append(dict(kw))
        return {"ok": True, "message_id": 888}


def _captures():
    seen: list[dict] = []

    def cap(body, *, role, chat_id, message_id=None, reply_to_message_id=None):
        seen.append({"body": body, "role": role, "chat_id": chat_id,
                     "message_id": message_id,
                     "reply_to_message_id": reply_to_message_id})

    return seen, cap


def _processor(calls, *, send_body="ANSWER", handled=True):
    def proc(**kw):
        calls.append(dict(kw))
        fn = kw.get("send_fn")
        if fn is not None and send_body is not None:
            fn(kw["chat_id"], send_body)
        return {"handled": handled, "reason": "answered"}

    return proc


def test_flag_off_never_calls_responder():
    calls: list[dict] = []
    out = R.maybe_answer(MSG, text="What are the latest analyst predictions on Walmart",
                         chat_id=CHAT, token=GENERAL_TOKEN, allowlist={CHAT},
                         env={}, processor=_processor(calls))
    assert out["answered"] is False
    assert out["reason"] == "flag_off"
    assert calls == []


def test_flag_on_calls_responder_with_asking_chat():
    calls: list[dict] = []
    tx = FakeTransport()
    seen, cap = _captures()
    out = R.maybe_answer(MSG, text="What are the latest analyst predictions on Walmart",
                         chat_id=CHAT, token=GENERAL_TOKEN, allowlist={CHAT},
                         env={"CIO_REPLY_ENABLED": "1"},
                         transport=tx, capture=cap, processor=_processor(calls))
    assert out["answered"] is True
    assert len(calls) == 1
    assert calls[0]["chat_id"] == CHAT
    assert calls[0]["channel"] == "telegram"
    assert calls[0]["message_id"] == 777


def test_reply_goes_out_on_the_bot_that_received_it():
    """THE regression. Not cio_bot_token() — the token that was asked."""
    calls: list[dict] = []
    tx = FakeTransport()
    seen, cap = _captures()
    R.maybe_answer(MSG, text="ADBE — what did Q3 actually show on user growth?",
                   chat_id=CHAT, token=GENERAL_TOKEN, allowlist={CHAT},
                   env={"CIO_REPLY_ENABLED": "1"},
                   transport=tx, capture=cap, processor=_processor(calls))
    assert len(tx.sends) == 1
    assert tx.sends[0]["token"] == GENERAL_TOKEN
    assert tx.sends[0]["token"] != CIO_TOKEN
    assert tx.sends[0]["chat_id"] == CHAT


def test_reply_threads_under_the_question():
    calls: list[dict] = []
    tx = FakeTransport()
    seen, cap = _captures()
    R.maybe_answer(MSG, text="what is WMT doing", chat_id=CHAT, token=GENERAL_TOKEN,
                   allowlist={CHAT}, env={"CIO_REPLY_ENABLED": "1"},
                   transport=tx, capture=cap, processor=_processor(calls))
    assert tx.sends[0]["reply_to_message_id"] == 777
    # And the agent half is captured with the same thread anchor.
    assert seen and seen[0]["role"] == "agent"
    assert seen[0]["reply_to_message_id"] == 777


def test_responder_exception_is_contained():
    def boom(**kw):
        raise RuntimeError("compose failed")

    out = R.maybe_answer(MSG, text="why is ADBE down", chat_id=CHAT,
                         token=GENERAL_TOKEN, allowlist={CHAT},
                         env={"CIO_REPLY_ENABLED": "1"}, processor=boom)
    assert out["answered"] is False
    assert out["reason"].startswith("error:")


@pytest.mark.parametrize("text,reason", [
    ("YES", "bare_confirmation"),
    ("ok", "bare_confirmation"),
    ("no.", "bare_confirmation"),
    ("http://127.0.0.1?code=abc123", "oauth_callback_shape"),
    ("here is the code=xyz", "oauth_callback_shape"),
    ("   ", "empty"),
])
def test_traffic_that_belongs_to_another_handler_is_declined(text, reason):
    ok, why = R.should_answer(text)
    assert ok is False
    assert why == reason


def test_real_questions_are_accepted():
    for t in ("What are the latest analyst predictions on Walmart",
              "ADBE — what did Q3 actually show on user growth?",
              "why did we trim NVDA"):
        ok, why = R.should_answer(t)
        assert ok is True, t
        assert why == "free_text"


def test_not_allowlisted_chat_is_refused():
    calls: list[dict] = []
    out = R.maybe_answer(MSG, text="what about WMT", chat_id="999",
                         token=GENERAL_TOKEN, allowlist={CHAT},
                         env={"CIO_REPLY_ENABLED": "1"}, processor=_processor(calls))
    assert out["reason"] == "not_allowlisted"
    assert calls == []


def test_explicit_reply_chat_ids_narrows_the_inherited_allowlist():
    assert R.reply_allowlist({CHAT, "555"}, {"CIO_REPLY_CHAT_IDS": CHAT}) == {CHAT}
    assert R.reply_allowlist({CHAT, "555"}, {}) == {CHAT, "555"}


def test_send_path_is_the_interdict_honouring_chokepoint():
    """The poller's own _post_message/_send/_send_reply build their own HTTP
    and bypass CIO_TELEGRAM_INTERDICT. This module must not reach for them."""
    import ast

    src = (ROOT / "scripts" / "lib" / "cio_poller_reply.py").read_text()
    tree = ast.parse(src)
    # Identifiers the CODE references, not prose. The docstring names the very
    # functions this must not call, and a substring scan cannot tell the
    # difference between explaining a trap and falling into it.
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.update(node.name.split("."))
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
    for banned in ("_post_message", "_send", "_send_reply", "urllib", "requests",
                   "send_cio_message"):
        assert banned not in names, banned
    assert "telegram_transport" in names
    assert "send_message" in names


def test_rate_limit_and_dedupe_are_delegated_not_reimplemented():
    """wakes_limit is passed through; dedupe lives in the core keyed
    channel:message_id. Reimplementing either here would give two answers."""
    calls: list[dict] = []
    tx = FakeTransport()
    seen, cap = _captures()
    R.maybe_answer(MSG, text="what is WMT doing", chat_id=CHAT, token=GENERAL_TOKEN,
                   allowlist={CHAT}, env={"CIO_REPLY_ENABLED": "1"},
                   transport=tx, capture=cap, processor=_processor(calls))
    assert isinstance(calls[0]["wakes_limit"], int) and calls[0]["wakes_limit"] >= 1
    assert calls[0]["actor_id"] == "cio_poller_reply"
    assert calls[0]["dry_run"] is False


def test_transport_threads_reply_to_message_id():
    """The additive transport change: reply_to_message_id reaches the payload."""
    from scripts import telegram_transport as T

    payload = T._base_payload("1", "hi", thread_id=None, reply_markup=None,
                              parse_mode="Markdown", reply_to_message_id=777)
    assert payload["reply_to_message_id"] == 777
    payload2 = T._base_payload("1", "hi", thread_id=None, reply_markup=None,
                               parse_mode="Markdown")
    assert "reply_to_message_id" not in payload2


def test_poller_hook_is_guarded_and_after_the_checkpoint():
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text()
    assert "cio_poller_reply" in src
    hook = src.index("cio_poller_reply.maybe_answer")
    commit = src.rindex("_commit_if_legacy()", 0, hook)
    guard = src.rindex("if not handled:", 0, hook)
    assert commit < guard < hook, "hook must sit under `if not handled:` AFTER commit"


def test_authority_rails_declared():
    assert R.AUTHORITY == "READ_ONLY_ADVISORY"
    assert R.MBI == 0
