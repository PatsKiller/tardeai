"""CIO WhatsApp egress — single governed Cloud API sender (P4).

READ_ONLY_ADVISORY. Meta WhatsApp Business Cloud API only.
No broker. Tokens from env only.

Env:
  WHATSAPP_TOKEN / WHATSAPP_ACCESS_TOKEN
  WHATSAPP_PHONE_NUMBER_ID
  CIO_WHATSAPP_CONVERSE=0|1  (must be on to send; also checked by ingress)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

# WhatsApp Cloud API text body limit
WA_MAX_MSG_LEN = 4000
GRAPH_VERSION = os.environ.get("WHATSAPP_GRAPH_VERSION", "v19.0").strip() or "v19.0"


def _env(k: str, default: str = "") -> str:
    return os.environ.get(k, default).strip()


def wa_token() -> str:
    return _env("WHATSAPP_TOKEN") or _env("WHATSAPP_ACCESS_TOKEN") or _env("META_WA_TOKEN")


def wa_phone_number_id() -> str:
    return _env("WHATSAPP_PHONE_NUMBER_ID") or _env("META_WA_PHONE_NUMBER_ID")


def egress_enabled() -> bool:
    """Hard fail-closed: flag must be on AND credentials present."""
    raw = _env("CIO_WHATSAPP_CONVERSE", "0")
    if raw.lower() in ("0", "false", "off", "no", ""):
        return False
    return bool(wa_token() and wa_phone_number_id())


def smart_split(text: str, limit: int = WA_MAX_MSG_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            for sep in (". ", "! ", "? ", " "):
                pos = text.rfind(sep, 0, limit)
                if pos > limit // 2:
                    cut = pos + len(sep)
                    break
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def send_whatsapp_text(
    to_wa_id: str,
    text: str,
    *,
    reply_to: Optional[str] = None,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    dry_run: bool = False,
    http_post: Any = None,
) -> dict[str, Any]:
    """Send one or more text messages via Cloud API. Sole WA egress path.

    to_wa_id: digits only preferred (e.g. 15551234567), whatsapp: prefix stripped.
    """
    tok = token or wa_token()
    pnid = phone_number_id or wa_phone_number_id()
    to = str(to_wa_id or "").replace("whatsapp:", "").replace("+", "").strip()
    if not to or not text:
        return {"ok": False, "error": "empty_to_or_text"}

    if dry_run:
        chunks = smart_split(text, WA_MAX_MSG_LEN)
        return {
            "ok": True,
            "dry_run": True,
            "chunks": len(chunks),
            "message_id": f"wamid.dry_{to}_{len(text)}",
        }

    # Live path: flag + credentials required (fail-closed)
    flag = _env("CIO_WHATSAPP_CONVERSE", "0").lower()
    if flag not in ("1", "true", "on", "yes"):
        return {"ok": False, "error": "CIO_WHATSAPP_CONVERSE_off"}
    if not tok or not pnid:
        return {"ok": False, "error": "wa_credentials_missing"}

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{pnid}/messages"
    chunks = smart_split(text, WA_MAX_MSG_LEN)
    last_mid: Optional[str] = None
    last_raw: dict[str, Any] = {}

    def _default_post(u: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            u, data=data, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    return {"ok": True, "status": resp.status, "body": json.loads(body)}
                except json.JSONDecodeError:
                    return {"ok": True, "status": resp.status, "body": {"raw": body}}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            try:
                parsed = json.loads(err_body) if err_body else {}
            except json.JSONDecodeError:
                parsed = {"raw": err_body}
            return {"ok": False, "status": e.code, "body": parsed, "error": f"HTTP{e.code}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

    post = http_post or _default_post
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }

    for i, chunk in enumerate(chunks):
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": chunk},
        }
        # context for first chunk only when replying in-thread
        if reply_to and i == 0:
            payload["context"] = {"message_id": str(reply_to)}
        last_raw = post(url, payload, headers)
        if not last_raw.get("ok"):
            return {
                "ok": False,
                "error": last_raw.get("error") or "send_failed",
                "raw": last_raw,
                "message_id": last_mid,
            }
        body = last_raw.get("body") or {}
        msgs = body.get("messages") or []
        if msgs and isinstance(msgs[0], dict):
            last_mid = msgs[0].get("id") or last_mid

    return {"ok": True, "message_id": last_mid, "chunks": len(chunks), "raw": last_raw}
