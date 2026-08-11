"""CIO WhatsApp ingress — Meta Cloud API webhook → shared converse core (P4).

Transport only. Maps inbound WA messages to the same OPERATOR_MESSAGE path
as Telegram. READ_ONLY_ADVISORY.

Env:
  CIO_WHATSAPP_CONVERSE=0|1          default 0
  WHATSAPP_WA_IDS / WHATSAPP_ALLOWLIST  comma allowlist (digits)
  WHATSAPP_TOKEN / WHATSAPP_ACCESS_TOKEN
  WHATSAPP_PHONE_NUMBER_ID
  WHATSAPP_VERIFY_TOKEN              webhook challenge
  WHATSAPP_APP_SECRET                X-Hub-Signature-256 (required if set)
  CIO_WHATSAPP_WAKES_PER_HOUR        default 20
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_whatsapp_egress import send_whatsapp_text, wa_token, wa_phone_number_id

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEDUP = PROJECT_ROOT / "data" / "cio" / "cio_whatsapp_msg_dedup.jsonl"
DEFAULT_MSG_MAP = PROJECT_ROOT / "data" / "cio" / "cio_whatsapp_plan_messages.jsonl"
DEFAULT_RATE = PROJECT_ROOT / "data" / "cio" / "cio_whatsapp_rate.jsonl"


def _env(k: str, default: str = "") -> str:
    return os.environ.get(k, default).strip()


def converse_enabled() -> bool:
    raw = _env("CIO_WHATSAPP_CONVERSE", "0")
    return raw.lower() in ("1", "true", "on", "yes")


def allowlist_wa_ids() -> set[str]:
    raw = (
        _env("WHATSAPP_WA_IDS")
        or _env("WHATSAPP_ALLOWLIST")
        or _env("WHATSAPP_TO")
        or _env("CIO_WHATSAPP_ALLOWLIST")
    )
    out: set[str] = set()
    for part in raw.split(","):
        p = part.strip().replace("whatsapp:", "").replace("+", "")
        if p:
            out.add(p)
    return out


def verify_token() -> str:
    return _env("WHATSAPP_VERIFY_TOKEN") or _env("META_WA_VERIFY_TOKEN")


def app_secret() -> str:
    return _env("WHATSAPP_APP_SECRET") or _env("META_APP_SECRET")


def wakes_per_hour() -> int:
    try:
        return max(1, int(_env("CIO_WHATSAPP_WAKES_PER_HOUR", "20")))
    except ValueError:
        return 20


def verify_webhook_challenge(
    mode: str,
    token: str,
    challenge: str,
) -> Optional[str]:
    """Meta GET hub.mode / hub.verify_token / hub.challenge."""
    if mode != "subscribe":
        return None
    expected = verify_token()
    if not expected or token != expected:
        return None
    return challenge


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Validate X-Hub-Signature-256 when app secret configured.

    If WHATSAPP_APP_SECRET is empty, returns False (fail-closed for POST)
    unless WHATSAPP_SKIP_SIGNATURE=1 (dev only).
    """
    if _env("WHATSAPP_SKIP_SIGNATURE", "0").lower() in ("1", "true", "yes"):
        return True
    secret = app_secret()
    if not secret:
        # fail-closed: require secret in production
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.split("=", 1)[1].strip()
    dig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(dig, expected)


def extract_inbound_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Meta webhook payload to normalized inbound rows."""
    rows: list[dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts = {c.get("wa_id"): c for c in (value.get("contacts") or []) if c.get("wa_id")}
            for msg in value.get("messages") or []:
                mid = msg.get("id")
                frm = str(msg.get("from") or "")
                mtype = msg.get("type") or ""
                text = ""
                if mtype == "text":
                    text = (msg.get("text") or {}).get("body") or ""
                elif mtype == "button":
                    text = (msg.get("button") or {}).get("text") or ""
                elif mtype == "interactive":
                    inter = msg.get("interactive") or {}
                    if inter.get("type") == "button_reply":
                        text = (inter.get("button_reply") or {}).get("title") or ""
                    elif inter.get("type") == "list_reply":
                        text = (inter.get("list_reply") or {}).get("title") or ""
                ctx = msg.get("context") or {}
                reply_to = ctx.get("id")
                contact = contacts.get(frm) or {}
                profile = contact.get("profile") or {}
                rows.append({
                    "message_id": mid,
                    "wa_id": frm.replace("+", ""),
                    "text": (text or "").strip(),
                    "type": mtype,
                    "reply_to_message_id": reply_to,
                    "reply_to_text": None,  # Cloud API rarely echoes parent body
                    "username": profile.get("name") or "",
                    "timestamp": msg.get("timestamp"),
                    "phone_number_id": (value.get("metadata") or {}).get("phone_number_id"),
                })
    return rows


def process_whatsapp_inbound(
    inbound: dict[str, Any],
    *,
    dry_run: bool = False,
    dedup_path: Path = DEFAULT_DEDUP,
    msg_map_path: Path = DEFAULT_MSG_MAP,
    rate_path: Path = DEFAULT_RATE,
    send_fn: Any = None,
) -> dict[str, Any]:
    """Process one normalized inbound WA message via shared converse core."""
    from scripts.lib.cio_converse_core import process_operator_message

    wa_id = str(inbound.get("wa_id") or "").replace("+", "")
    text = (inbound.get("text") or "").strip()
    mid = inbound.get("message_id")

    flag_on = converse_enabled()

    def _send(cid: str, body: str, reply_to: Optional[str] = None) -> dict[str, Any]:
        # Flag 0 = no egress (commands included)
        if not flag_on:
            return {"ok": False, "error": "CIO_WHATSAPP_CONVERSE_off"}
        if send_fn is not None:
            return send_fn(cid, body, reply_to=reply_to)
        return send_whatsapp_text(cid, body, reply_to=reply_to, dry_run=False)

    return process_operator_message(
        channel="whatsapp",
        chat_id=wa_id,
        message_id=mid or "",
        text=text,
        reply_to_message_id=inbound.get("reply_to_message_id"),
        reply_to_text=inbound.get("reply_to_text"),
        user_id=wa_id,
        username=inbound.get("username") or "",
        allowlist=allowlist_wa_ids(),
        # When flag off: still accept allowlist checks; free-text blocked as disabled;
        # slash/commands may run handlers but _send refuses egress.
        converse_on=flag_on,
        dedup_path=dedup_path,
        msg_map_path=msg_map_path,
        rate_path=rate_path,
        dry_run=dry_run,
        send_fn=None if dry_run else _send,
        wakes_limit=wakes_per_hour(),
        actor_id="cio_whatsapp",
    )


def process_webhook_payload(
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Process full Meta webhook JSON."""
    out: dict[str, Any] = {
        "processed": 0,
        "results": [],
        "errors": [],
        "enabled": converse_enabled(),
        "allowlist_n": len(allowlist_wa_ids()),
        "token_set": bool(wa_token()),
        "phone_number_id_set": bool(wa_phone_number_id()),
        "authority": "READ_ONLY_ADVISORY",
    }
    try:
        messages = extract_inbound_messages(payload)
    except Exception as exc:
        out["errors"].append(f"extract:{type(exc).__name__}:{exc}")
        return out
    for inbound in messages:
        try:
            res = process_whatsapp_inbound(inbound, dry_run=dry_run, **kwargs)
            out["results"].append(res)
            out["processed"] += 1
        except Exception as exc:
            out["errors"].append(
                f"msg:{inbound.get('message_id')}:{type(exc).__name__}:{exc}"
            )
    return out
