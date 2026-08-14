#!/usr/bin/env python3
"""Low-level Telegram transport.

This is the only module allowed to know the sendMessage Bot API endpoint. It is
called by the audited alert outbox sender, not by application producers.
"""
from __future__ import annotations

import requests

TELEGRAM_SEND_MESSAGE_API = "https://api.telegram.org/bot{token}/sendMessage"
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


def send_message(*, token: str, chat_id: str, text: str, thread_id: str | None = None) -> dict:
    # Phase 1 network interdiction: never hit Telegram API under pytest / CI flags
    import os
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CIO_TELEGRAM_INTERDICT", "").lower() in (
        "1", "true", "yes", "on",
    ):
        return {
            "ok": False,
            "status_code": 0,
            "response": {"ok": False, "description": "INTERDICTED_TEST_OR_FLAG"},
            "interdicted": True,
        }
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if thread_id:
        payload["message_thread_id"] = thread_id
    resp = requests.post(TELEGRAM_SEND_MESSAGE_API.format(token=token), json=payload, timeout=10)
    if resp.ok:
        return {"ok": True, "status_code": resp.status_code, "response": _safe_json(resp)}
    fallback = {"chat_id": chat_id, "text": text}
    if thread_id:
        fallback["message_thread_id"] = thread_id
    resp2 = requests.post(TELEGRAM_SEND_MESSAGE_API.format(token=token), json=fallback, timeout=10)
    return {"ok": bool(resp2.ok), "status_code": resp2.status_code, "response": _safe_json(resp2)}


def _safe_json(resp) -> dict:
    try:
        return resp.json()
    except Exception:
        return {}
