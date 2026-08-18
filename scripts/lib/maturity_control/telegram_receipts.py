"""Telegram delivery proof for Command Center. Never returns tokens or chat IDs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_delivery_mode import classify_delivery_mode
from scripts.lib.maturity_control.redaction import redact
from scripts.lib.maturity_control.store import resolve_root


def collect_telegram_receipts(*, root: Path | str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    mode = classify_delivery_mode(env)
    # Prefer dedicated CIO token presence flags already computed; never copy values.
    receipts: list[dict[str, Any]] = []
    for rel in (
        "data/cio/cio_telegram_delivery.jsonl",
        "data/cio/cio_notification_audit.jsonl",
        "data/runtime/cio_telegram_receipts.jsonl",
    ):
        p = base / rel
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            mid = obj.get("telegram_message_id") or obj.get("message_id")
            if not mid and obj.get("kind") not in {"send", "delivery", "telegram"}:
                # keep audit rows that look like send attempts
                if "telegram" not in json.dumps(obj).lower() and "message_id" not in obj:
                    continue
            receipts.append({
                "at": obj.get("at") or obj.get("created_at") or obj.get("ts"),
                "ok": obj.get("ok") if "ok" in obj else obj.get("success"),
                "message_id": mid,
                "dedupe_key": obj.get("dedupe_key") or obj.get("notification_id"),
                "notification_class": obj.get("notification_class"),
                "decision_lineage_id": obj.get("decision_lineage_id"),
                "error_class": obj.get("error_class") or obj.get("error"),
            })
    last_ok = next((r for r in reversed(receipts) if r.get("ok") is True), None)
    last_fail = next((r for r in reversed(receipts) if r.get("ok") is False), None)
    last_attempt = receipts[-1] if receipts else None
    return redact({
        "authority": "READ_ONLY_ADVISORY",
        "delivery_mode": mode.get("CIO_DELIVERY_MODE"),
        "credentials_ready": bool(mode.get("dedicated_cio_token_set") and mode.get("dedicated_chat_allowlist_set")),
        "live_authorized": bool(mode.get("live_authorized")),
        "interdicted": bool(mode.get("interdict")),
        "proactive_delivery_ready": bool(mode.get("proactive_delivery_ready")),
        "last_delivery_attempt": last_attempt,
        "last_success": last_ok,
        "last_failure": last_fail,
        "receipt_count": len(receipts),
        "receipts": receipts[-50:],
        # Explicitly omitted: bot token, chat ID
        "secrets_omitted": ["TELEGRAM_CIO_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CIO_CHAT_IDS"],
    })
