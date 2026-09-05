#!/usr/bin/env python3
"""Low-level Telegram transport.

This is the only module allowed to know the sendMessage / editMessageText Bot
API endpoints. Called by the audited alert outbox sender, not by application
producers.

T2 (2026-08-22): markdown parse failure must EDIT the original message, never
send a second copy. Idempotency key (surface, symbol, decision_id) converts a
retry into editMessageText.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import requests

TELEGRAM_SEND_MESSAGE_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_EDIT_MESSAGE_API = "https://api.telegram.org/bot{token}/editMessageText"
TELEGRAM_SEND_DOCUMENT_API = "https://api.telegram.org/bot{token}/sendDocument"
MAX_MSG_LEN = 4000


def smart_split(text: str, limit: int = MAX_MSG_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            for sep in (". ", "! ", "? "):
                pos = text.rfind(sep, 0, limit)
                if pos > limit // 2:
                    cut = pos + len(sep)
                    break
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def _safe_json(resp) -> dict:
    try:
        return resp.json()
    except Exception:
        return {}


def _message_id_from(body: dict | None) -> Any:
    if not isinstance(body, dict):
        return None
    result = body.get("result") if isinstance(body.get("result"), dict) else body
    mid = result.get("message_id") if isinstance(result, dict) else None
    return mid


def _http_post(url: str, payload: dict) -> Any:
    return requests.post(url, json=payload, timeout=10)


def _base_payload(
    chat_id: str,
    text: str,
    *,
    thread_id: str | None,
    reply_markup: dict | None,
    parse_mode: str | None,
    message_id: Any = None,
) -> dict:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if thread_id:
        payload["message_thread_id"] = thread_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if message_id is not None:
        payload["message_id"] = message_id
    return payload


def _interdicted() -> bool:
    """Is outbound Telegram delivery interdicted right now?

    C4, 2026-08-31. This check lived only in `send_message`, which then delegates
    to `deliver_text` -- and `deliver_text` is exported and callable directly. Any
    caller reaching it bypassed the interdict entirely, so a control named for
    stopping delivery did not cover every path that delivers.

    AGENTS.md §7, severity 2: the restriction existed, but not in the thing named
    for it. Someone hardening delivery by setting CIO_TELEGRAM_INTERDICT would
    have changed nothing for those callers, which is how a careful person makes a
    change that silently does not take.

    The check now sits at the LOWEST COMMON LAYER -- the function that actually
    performs the HTTP -- so no caller can reach a send that skips it.
    """
    import os
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("CIO_TELEGRAM_INTERDICT", "").lower()
        in ("1", "true", "yes", "on")
    )


def _interdicted_result() -> dict:
    return {
        "ok": False,
        "status_code": 0,
        "response": {"ok": False, "description": "INTERDICTED_TEST_OR_FLAG"},
        "interdicted": True,
    }



_log = logging.getLogger(__name__)


def escape_markdown(text: str) -> str:
    """THE shared Markdown V1 escaper. Use this; do not write another.

    D1, 2026-08-31. 126 producers send with parse_mode="Markdown". Exactly one
    escaper existed -- `_esc_md`, private, in telegram_proposal_alert_policy --
    reachable by 2 of them. The other 124 escaped nothing, so whether an
    identifier survived was decided by underscore parity: an even count parsed
    and Telegram ate the underscores (READ_ONLY_ADVISORY -> READONLYADVISORY), an
    odd count 400'd and the plaintext retry preserved them.

    Placed on the transport so every producer already importing it can reach it,
    rather than adding a 127th convention. Migrating the producers is a separate
    wave; this is the thing they migrate TO.
    """
    return (
        str(text)
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )


def deliver_text(
    *,
    token: str,
    chat_id: str,
    text: str,
    thread_id: str | None = None,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
    idempotency_key: str | None = None,
    post: Optional[Callable] = None,
) -> dict:
    """Send or edit one Telegram message.

    - Known idempotency key → editMessageText (never a second sendMessage).
    - First sendMessage with parse_mode. On parse/HTTP failure of that first
      attempt, if no message exists yet, send plaintext ONCE. If a message_id
      exists, edit it. Never sendMessage twice for the same key.
    """
    if _interdicted():
        return _interdicted_result()
    poster = post or _http_post
    edit_id = None
    if idempotency_key:
        try:
            from lib.telegram_send_idempotency import lookup
        except ImportError:
            try:
                from telegram_send_idempotency import lookup  # type: ignore
            except ImportError:
                lookup = None  # type: ignore
        if lookup:
            rec = lookup(idempotency_key, str(chat_id))
            if rec:
                edit_id = rec.get("message_id")

    def _remember(mid: Any) -> None:
        if not idempotency_key or mid in (None, "", 0):
            return
        try:
            from lib.telegram_send_idempotency import remember
        except ImportError:
            try:
                from telegram_send_idempotency import remember  # type: ignore
            except ImportError:
                return
        remember(idempotency_key, str(chat_id), mid)

    def _call(url: str, payload: dict) -> tuple[bool, int, dict]:
        resp = poster(url, payload)
        # Fake/test posters may return a dict.
        if isinstance(resp, dict):
            ok = bool(resp.get("ok"))
            code = int(resp.get("status_code") or (200 if ok else 400))
            body = resp.get("response") if isinstance(resp.get("response"), dict) else resp
            return ok, code, body or {}
        body = _safe_json(resp)
        ok = bool(getattr(resp, "ok", False))
        code = int(getattr(resp, "status_code", 0) or 0)
        return ok, code, body

    send_url = TELEGRAM_SEND_MESSAGE_API.format(token=token)
    edit_url = TELEGRAM_EDIT_MESSAGE_API.format(token=token)

    if edit_id is not None:
        payload = _base_payload(
            chat_id, text, thread_id=thread_id, reply_markup=reply_markup,
            parse_mode=parse_mode, message_id=edit_id,
        )
        ok, code, body = _call(edit_url, payload)
        if not ok and parse_mode:
            payload.pop("parse_mode", None)
            ok, code, body = _call(edit_url, payload)
        if ok:
            _remember(edit_id)
        return {
            "ok": ok,
            "status_code": code,
            "response": body,
            "edited": True,
            "message_id": edit_id if ok else _message_id_from(body),
        }

    payload = _base_payload(
        chat_id, text, thread_id=thread_id, reply_markup=reply_markup,
        parse_mode=parse_mode,
    )
    ok, code, body = _call(send_url, payload)
    if ok:
        mid = _message_id_from(body)
        _remember(mid)
        return {"ok": True, "status_code": code, "response": body, "edited": False, "message_id": mid}

    # First send never posted (typical: Markdown parse 400). One plaintext send —
    # that is the original message, not a duplicate.
    payload_plain = _base_payload(
        chat_id, text, thread_id=thread_id, reply_markup=reply_markup, parse_mode=None,
    )
    ok2, code2, body2 = _call(send_url, payload_plain)
    mid = _message_id_from(body2) if ok2 else None
    if ok2:
        _remember(mid)
    # D1, 2026-08-31: THE FALLBACK IS NO LONGER SILENT.
    #
    # `plain_fallback: True` was returned and never logged or persisted by any
    # caller. So the first send failing -- typically a Markdown parse 400 -- and
    # the request being silently changed was invisible: the operator saw
    # `READ_ONLY_ADVISORY` render as READONLYADVISORY on an even underscore count
    # and intact on an odd one, and nothing recorded which had happened.
    #
    # A retry that silently alters the request is a failure swallow (AGENTS.md
    # §9.1). It stays a retry -- dropping the message would be worse -- but it
    # now says so.
    _log.warning(
        "telegram parse_mode fallback: first send failed (code=%s), resent as "
        "plain text. Original parse_mode=%r. Identifiers with underscores may "
        "render differently between attempts. chat=%s ok=%s",
        code, parse_mode, chat_id, bool(ok2),
    )
    return {
        "ok": bool(ok2),
        "status_code": code2,
        "response": body2,
        "edited": False,
        "plain_fallback": True,
        "plain_fallback_reason": f"first_send_failed_code_{code}",
        "message_id": mid,
    }


def send_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    thread_id: str | None = None,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
    idempotency_key: str | None = None,
) -> dict:
    # C4: the interdict now lives in deliver_text, the lowest common layer, so it
    # cannot be bypassed by calling that directly. Kept here as an early return
    # only to avoid building a request that will be discarded.
    if _interdicted():
        return _interdicted_result()
    return deliver_text(
        token=token,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        idempotency_key=idempotency_key,
    )


def send_document(
    *,
    token: str,
    chat_id: str,
    file_path: str,
    caption: str | None = None,
    thread_id: str | None = None,
    reply_markup: dict | None = None,
) -> dict:
    """Send a document via Bot API. Only callable from approved delivery modules."""
    if _interdicted():
        return _interdicted_result()
    from pathlib import Path

    path = Path(file_path)
    if not path.is_file():
        return {
            "ok": False,
            "status_code": 0,
            "response": {"ok": False, "description": "file_missing"},
            "message_id": None,
        }
    url = TELEGRAM_SEND_DOCUMENT_API.format(token=token)
    data: dict[str, Any] = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    if thread_id:
        data["message_thread_id"] = thread_id
    if reply_markup:
        import json as _json

        data["reply_markup"] = _json.dumps(reply_markup)
    try:
        with path.open("rb") as fh:
            resp = requests.post(
                url,
                data=data,
                files={"document": (path.name, fh)},
                timeout=60,
            )
        body = _safe_json(resp)
        ok = bool(getattr(resp, "ok", False)) and bool(body.get("ok", getattr(resp, "ok", False)))
        # Prefer API ok flag when present.
        if isinstance(body, dict) and "ok" in body:
            ok = bool(body.get("ok"))
        return {
            "ok": ok,
            "status_code": int(getattr(resp, "status_code", 0) or 0),
            "response": body,
            "message_id": _message_id_from(body) if ok else None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": 0,
            "response": {"ok": False, "description": f"{type(e).__name__}:{e}"},
            "message_id": None,
        }
