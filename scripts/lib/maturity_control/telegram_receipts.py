"""Telegram delivery proof for Command Center. Never returns tokens or chat IDs.

Unifies ALL real send/receipt paths used by CIO + generic Trade AI bots:
  - dedicated CIO Alex receipts (cio_telegram_receipts.jsonl)
  - CIO delivery / audit / runtime receipts
  - operator notification outbox DELIVERY_CONFIRMED events
  - generic ops SYSTEM sends (system_telegram_sends.jsonl)

PREPARE_ONLY means the dedicated CIO live path is not authorized — it does
NOT mean "nothing was ever sent". Generic-bot deliveries are surfaced when
present. This module never invents receipts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_delivery_mode import classify_delivery_mode
from scripts.lib.maturity_control.redaction import redact
from scripts.lib.maturity_control.store import resolve_root

# (relative path, default bot_channel label when row does not declare one)
RECEIPT_SOURCES: tuple[tuple[str, str], ...] = (
    ("data/cio/cio_telegram_receipts.jsonl", "dedicated_cio"),
    ("data/cio/cio_telegram_delivery.jsonl", "dedicated_cio"),
    ("data/cio/cio_notification_audit.jsonl", "dedicated_cio"),
    ("data/runtime/cio_telegram_receipts.jsonl", "dedicated_cio"),
    ("data/cio/operator_notification_outbox.jsonl", "dedicated_cio"),
    ("data/cio/cio_notification_outbox.jsonl", "dedicated_cio"),
    ("data/cio/system_telegram_sends.jsonl", "generic_ops"),
)

_OUTBOX_DELIVERY_EVENTS = frozenset({
    "DELIVERY_CONFIRMED",
    "DELIVERY_ATTEMPTED",
    "DELIVERY_FAILED",
    "DELIVERY_CLAIMED",
})


def _bot_channel_from_row(obj: dict[str, Any], default: str) -> str:
    if obj.get("general_channel") is True or obj.get("cio_lineage") is False:
        return "generic_ops"
    ch = str(obj.get("channel") or obj.get("delivery_method") or "").lower()
    family = str(obj.get("family") or "").upper()
    if family == "TRADE_AI_SYSTEM" or "generic" in ch or ch in {"telegram", "telegram_ops"}:
        if family == "TRADE_AI_SYSTEM":
            return "generic_ops"
    if "cio" in ch or ch in {"telegram_cio", "dedicated_cio"}:
        return "dedicated_cio"
    if default:
        return default
    return "unknown"


def _normalize_receipt(obj: dict[str, Any], *, source: str, default_bot: str) -> dict[str, Any] | None:
    """Map heterogeneous send/receipt rows into a redaction-safe receipt view."""
    event_type = str(obj.get("event_type") or "")
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

    # Outbox event stream — only delivery-related events count as receipts.
    if event_type:
        if event_type not in _OUTBOX_DELIVERY_EVENTS and event_type != "NOTIFICATION_ENQUEUED":
            return None
        # Enqueue is preparation, not delivery — keep only when useful as attempt
        # context under PREPARE_ONLY; still not a delivery success.
        mid = (
            payload.get("external_message_id")
            or payload.get("message_id")
            or obj.get("telegram_message_id")
            or obj.get("message_id")
        )
        ok: bool | None
        if event_type == "DELIVERY_CONFIRMED":
            ok = True
        elif event_type in {"DELIVERY_FAILED"}:
            ok = False
        elif event_type == "NOTIFICATION_ENQUEUED":
            ok = None  # prepared / queued, not delivered
        else:
            ok = None
        bot = _bot_channel_from_row({**obj, **payload}, default_bot)
        # Shadow confirms with empty message_id are not live delivery proof
        if event_type == "DELIVERY_CONFIRMED" and not mid:
            bot = bot  # still record attempt; ok stays True but mid empty
        return {
            "at": obj.get("occurred_at") or obj.get("at") or payload.get("created_at"),
            "ok": ok,
            "message_id": mid or None,
            "dedupe_key": payload.get("dedupe_key") or payload.get("notification_id") or obj.get("stream_id"),
            "notification_class": payload.get("message_class") or obj.get("notification_class"),
            "decision_lineage_id": obj.get("decision_lineage_id") or payload.get("decision_lineage_id"),
            "error_class": payload.get("error") or obj.get("error_class"),
            "bot_channel": bot,
            "event_type": event_type,
            "source_file": source,
            "subject": payload.get("subject"),
            "kind": "outbox_" + event_type.lower(),
        }

    mid = obj.get("telegram_message_id") or obj.get("message_id")
    if isinstance(obj.get("message_ids"), list) and obj["message_ids"]:
        mid = mid or obj["message_ids"][0]
    # Keep send/delivery rows and audit rows that look like telegram attempts
    if not mid and obj.get("kind") not in {"send", "delivery", "telegram", "daily_heartbeat", "canary", "alert"}:
        if obj.get("ok") is None and not obj.get("delivered"):
            blob = json.dumps(obj).lower()
            if "telegram" not in blob and "message_id" not in obj and "delivered" not in obj:
                return None

    ok = obj.get("ok") if "ok" in obj else obj.get("success")
    if ok is None and "delivered" in obj:
        ok = bool(obj.get("delivered"))
    # Alex CIO receipts record message_ids without an explicit ok flag
    if ok is None and mid is not None:
        ok = True
    bot = _bot_channel_from_row(obj, default_bot)
    return {
        "at": obj.get("at") or obj.get("created_at") or obj.get("ts") or obj.get("delivered_at"),
        "ok": ok,
        "message_id": mid,
        "dedupe_key": obj.get("dedupe_key") or obj.get("notification_id") or obj.get("identity"),
        "notification_class": obj.get("notification_class"),
        "decision_lineage_id": obj.get("decision_lineage_id") or obj.get("decision_id"),
        "error_class": obj.get("error_class") or obj.get("error"),
        "bot_channel": bot,
        "event_type": obj.get("kind") or obj.get("family"),
        "source_file": source,
        "subject": obj.get("subject"),
        "kind": obj.get("kind"),
    }


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def collect_telegram_receipts(*, root: Path | str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    mode = classify_delivery_mode(env)
    delivery_mode = mode.get("CIO_DELIVERY_MODE")
    receipts: list[dict[str, Any]] = []
    sources_seen: list[str] = []

    for rel, default_bot in RECEIPT_SOURCES:
        p = base / rel
        rows = _iter_jsonl(p)
        if not rows:
            continue
        sources_seen.append(rel)
        for obj in rows:
            norm = _normalize_receipt(obj, source=rel, default_bot=default_bot)
            if norm is None:
                continue
            receipts.append(norm)

    # Stable chronological order (unknown timestamps last)
    def _sort_key(r: dict[str, Any]) -> str:
        return str(r.get("at") or "")

    receipts.sort(key=_sort_key)

    last_ok = next((r for r in reversed(receipts) if r.get("ok") is True), None)
    last_fail = next((r for r in reversed(receipts) if r.get("ok") is False), None)
    last_attempt = receipts[-1] if receipts else None
    delivered_bots = sorted({
        str(r.get("bot_channel"))
        for r in receipts
        if r.get("ok") is True and r.get("bot_channel")
    })
    generic_delivered = any(
        r.get("ok") is True and r.get("bot_channel") == "generic_ops" for r in receipts
    )
    cio_delivered = any(
        r.get("ok") is True and r.get("bot_channel") == "dedicated_cio" for r in receipts
    )

    mode_note = (
        "PREPARE_ONLY means the dedicated CIO live path is not authorized in this "
        "process. It does not mean nothing was ever sent — check generic_ops and "
        "outbox receipts below."
        if delivery_mode == "PREPARE_ONLY"
        else (
            "INTERDICTED is a kill-switch for the CIO path; SYSTEM/generic ops may "
            "still have historical receipts."
            if delivery_mode == "INTERDICTED"
            else "CIO_ONLY_LIVE allows dedicated CIO bot delivery when credentials are ready."
        )
    )

    return redact({
        "authority": "READ_ONLY_ADVISORY",
        "delivery_mode": delivery_mode,
        "delivery_mode_note": mode_note,
        "prepare_only_does_not_mean_never_sent": delivery_mode == "PREPARE_ONLY",
        "credentials_ready": bool(mode.get("dedicated_cio_token_set") and mode.get("dedicated_chat_allowlist_set")),
        "live_authorized": bool(mode.get("live_authorized")),
        "interdicted": bool(mode.get("interdict")),
        "proactive_delivery_ready": bool(mode.get("proactive_delivery_ready")),
        "general_token_present": bool(mode.get("general_token_present")),
        "bots_that_delivered": delivered_bots,
        "last_delivery_bot": (last_ok or {}).get("bot_channel") if last_ok else None,
        "generic_ops_delivered": generic_delivered,
        "dedicated_cio_delivered": cio_delivered,
        "last_delivery_attempt": last_attempt,
        "last_success": last_ok,
        "last_failure": last_fail,
        "receipt_count": len(receipts),
        "receipts": receipts[-50:],
        "sources_read": sources_seen,
        # Explicitly omitted: bot token, chat ID
        "secrets_omitted": ["TELEGRAM_CIO_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CIO_CHAT_IDS"],
    })
