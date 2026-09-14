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
import re as _re_html
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


#: Telegram counts message length in UTF-16 code units; an emoji is two.
TELEGRAM_TEXT_LIMIT = 4096


def utf16_len(text: str) -> int:
    return len((text or "").encode("utf-16-le")) // 2


def split_for_telegram(text: str, limit: int = MAX_MSG_LEN) -> list[str]:
    """`smart_split`, then re-split any part Telegram would count as over 4,096 UTF-16 units."""
    parts: list[str] = []
    for part in smart_split(text or "", limit):
        if utf16_len(part) <= TELEGRAM_TEXT_LIMIT or limit <= 500:
            parts.append(part)
        else:
            parts.extend(split_for_telegram(part, max(500, limit - 400)))
    return parts


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
    reply_to_message_id: Any = None,
    link_preview_options: dict | None = None,
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
    if reply_to_message_id is not None:
        # An answer that does not hang under its question is a different message
        # in the same room. It also costs the inbound side its reply context: a
        # later "ok" replying to THIS answer resolves its subject by pointing at
        # the parent, and the parent has to be reachable for that to work.
        payload["reply_to_message_id"] = int(reply_to_message_id)
    if link_preview_options:
        # Bot API: a chart image URL shown large above the text, or previews switched off.
        payload["link_preview_options"] = link_preview_options
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


_log = logging.getLogger(__name__)


def _interdicted_result() -> dict:
    # Observability: silent return made interdict unprovable in prod logs.
    # Log once per call at WARNING so soak/self-repair can see the gate fire.
    _log.warning(
        "telegram_interdicted",
        extra={"event": "telegram_interdicted", "description": "INTERDICTED_TEST_OR_FLAG"},
    )
    return {
        "ok": False,
        "status_code": 0,
        "response": {"ok": False, "description": "INTERDICTED_TEST_OR_FLAG"},
        "interdicted": True,
    }


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


def unescape_markdown(text: str) -> str:
    """Inverse of ``escape_markdown``, for the plaintext fallback.

    Only the four sequences the escaper produces, so a literal backslash the
    author actually wrote survives untouched.
    """
    return (
        str(text)
        .replace("\\_", "_")
        .replace("\\*", "*")
        .replace("\\[", "[")
        .replace("\\`", "`")
    )


_HTML_TAG = _re_html.compile(r"</?(?:b|i|u|s|code|pre|a)\b[^>]*>")
_MD_EMPHASIS = _re_html.compile(r"(?:\*\w|_\w|`)")


def parse_mode_for(text: str, default: str | None = "Markdown") -> str | None:
    """Pick the markup language the body is actually written in.

    Producers disagree about this channel's markup and the transport assumed
    one answer. 8 of 678 messages in the 7 days to 2026-09-10 shipped
    ``⚠️ <b>Health Agent: DEGRADED — 68/100</b>`` with the tags visible, because
    HTML was sent under ``parse_mode="Markdown"``.

    Measured on the same window, no message mixes the two (0 of 678), so
    choosing by content is unambiguous on real traffic. A body that somehow
    contains both keeps the default and the existing plaintext fallback catches
    it — this widens nothing.
    """
    if not text:
        return default
    if _HTML_TAG.search(text) and not _MD_EMPHASIS.search(text):
        return "HTML"
    return default


def html_to_plain(text: str) -> str:
    """Readable plain text from Telegram HTML, for the one plain retry after an HTML send is refused.

    Resending the HTML body without parse_mode would put the tags in front of the operator, which is the
    Markdown-backslash failure again in another language. Links keep their address.
    """
    import html as _html  # noqa: PLC0415

    t = _re_html.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', lambda m: f"{m.group(2)} ({_html.unescape(m.group(1))})",
                     text or "", flags=_re_html.S)
    t = _re_html.sub(r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|tg-spoiler|span|blockquote)(?:\s[^>]*)?>", "", t)
    return _html.unescape(t)


def _comms_editor():
    try:
        from lib import comms_editor as ce  # noqa: PLC0415
    except ImportError:
        try:
            from scripts.lib import comms_editor as ce  # type: ignore  # noqa: PLC0415
        except ImportError:
            return None
    return ce


def deliver_text(
    *,
    token: str,
    chat_id: str,
    text: str,
    thread_id: str | None = None,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
    idempotency_key: str | None = None,
    reply_to_message_id: Any = None,
    post: Optional[Callable] = None,
    link_preview_options: dict | None = None,
) -> dict:
    """Every operator message passes the Communications Editor, then the raw send.

    2026-09-14: the operator's Telegram exports showed the same morning brief 50
    times, raw Markdown asterisks, messages with no links, and decisions sent
    while marked invalid. ``COMMS_EDITOR_MODE`` decides what happens here:
    ``off`` sends unchanged; ``shadow`` sends unchanged and writes the editor's
    receipt; ``live`` sends the edited HTML, and holds duplicates and invalid
    products (reported as ``suppressed``, never as a failure). The editor can
    never block a send by raising: any editor error sends the original.
    """
    if _interdicted():
        return _interdicted_result()
    ce = _comms_editor()
    decision = None
    if ce is not None and ce.mode() != "off":
        try:
            decision = ce.edit(text, chat_id=chat_id, parse_mode=parse_mode, db_query=ce.default_db_query)
        except Exception as exc:  # noqa: BLE001
            _log.warning("comms editor failed, sending original: %s", exc)
            decision = None
    if decision is not None and decision.mode == "live":
        if not decision.send:
            ce.commit(decision, chat_id=chat_id)
            return {"ok": True, "status_code": 200, "response": {}, "edited": False, "message_id": None,
                    "suppressed": "duplicate" if decision.duplicate_of else decision.held_reason,
                    "comms_editor": decision.receipt()}
        result = _deliver_text_raw(
            token=token, chat_id=chat_id, text=decision.text, thread_id=thread_id, reply_markup=reply_markup,
            parse_mode="HTML", idempotency_key=idempotency_key, reply_to_message_id=reply_to_message_id, post=post,
            link_preview_options=link_preview_options,
        )
        if result.get("ok"):
            ce.commit(decision, chat_id=chat_id)
        result["comms_editor"] = decision.receipt()
        return result
    result = _deliver_text_raw(
        token=token, chat_id=chat_id, text=text, thread_id=thread_id, reply_markup=reply_markup,
        parse_mode=parse_mode, idempotency_key=idempotency_key, reply_to_message_id=reply_to_message_id, post=post,
            link_preview_options=link_preview_options,
    )
    if decision is not None:  # shadow: record what the editor would have done
        try:
            ce.commit(decision, chat_id=chat_id)
        except Exception:  # noqa: BLE001
            pass
    return result


def _deliver_text_raw(
    *,
    token: str,
    chat_id: str,
    text: str,
    thread_id: str | None = None,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
    idempotency_key: str | None = None,
    reply_to_message_id: Any = None,
    post: Optional[Callable] = None,
    link_preview_options: dict | None = None,
) -> dict:
    """Send or edit one Telegram message.

    - Known idempotency key → editMessageText (never a second sendMessage).
    - First sendMessage with parse_mode. On parse/HTTP failure of that first
      attempt, if no message exists yet, send plaintext ONCE. If a message_id
      exists, edit it. Never sendMessage twice for the same key.
    """
    if _interdicted():
        return _interdicted_result()
    # Resolve the markup language from the body before any attempt, so an HTML
    # producer is not sent under Markdown and rendered with its tags showing.
    parse_mode = parse_mode_for(text, parse_mode)
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
            parse_mode=parse_mode, message_id=edit_id, link_preview_options=link_preview_options,
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
        parse_mode=parse_mode, reply_to_message_id=reply_to_message_id,
        link_preview_options=link_preview_options,
    )
    ok, code, body = _call(send_url, payload)
    if ok:
        mid = _message_id_from(body)
        _remember(mid)
        return {"ok": True, "status_code": code, "response": body, "edited": False, "message_id": mid}

    # First send never posted (typical: Markdown parse 400). One plaintext send —
    # that is the original message, not a duplicate.
    #
    # Unescape first. Dropping parse_mode without undoing the escaping is what
    # put `siem\_p1 ×16 — 🚨 SIEM P1: cleanup\_stale\_proposals` in front of the
    # operator: the producer escaped correctly for Markdown, the parse failed,
    # and the plaintext retry rendered the escape characters as themselves.
    # 15 of 678 messages in the 7 days to 2026-09-10 carried visible
    # backslashes. Nothing was wrong with the escaper; the fallback simply
    # spoke a different language than the text it was resending.
    payload_plain = _base_payload(
        chat_id,
        unescape_markdown(text) if parse_mode == "Markdown" else html_to_plain(text) if parse_mode == "HTML" else text,
        thread_id=thread_id, reply_markup=reply_markup, parse_mode=None,
        reply_to_message_id=reply_to_message_id,
        link_preview_options=link_preview_options,
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
    reply_to_message_id: Any = None,
    link_preview_options: dict | None = None,
) -> dict:
    # C4: the interdict now lives in deliver_text, the lowest common layer, so it
    # cannot be bypassed by calling that directly. Kept here as an early return
    # only to avoid building a request that will be discarded.
    if _interdicted():
        return _interdicted_result()
    # 2026-09-14 13:47: the desk's 4,571-character AXTI answer went to sendMessage whole.
    # Telegram refused it (400, over 4,096), the plain-text retry was refused the same way,
    # and the poller logged "replied". A long body is sent as ordered parts instead. An
    # idempotent send edits one existing message, so it is never split.
    parts = split_for_telegram(text) if (text and not idempotency_key) else [text]
    if len(parts) > 1:
        results: list[dict] = []
        for i, part in enumerate(parts):
            res = deliver_text(
                token=token, chat_id=chat_id, text=part, thread_id=thread_id,
                reply_markup=reply_markup if i == len(parts) - 1 else None,
                parse_mode=parse_mode, idempotency_key=None,
                reply_to_message_id=reply_to_message_id if i == 0 else None,
                link_preview_options=link_preview_options if i == 0 else None,
            )
            results.append(res)
            if not res.get("ok"):
                break
        out = dict(results[-1])
        out.update({
            "ok": len(results) == len(parts) and all(r.get("ok") for r in results),
            "message_id": results[0].get("message_id"),
            "message_ids": [r.get("message_id") for r in results],
            "parts": len(parts),
            "parts_sent": sum(1 for r in results if r.get("ok")),
        })
        return out
    return deliver_text(
        token=token,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        idempotency_key=idempotency_key,
        reply_to_message_id=reply_to_message_id,
        link_preview_options=link_preview_options,
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
