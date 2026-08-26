"""Persistent Telegram send idempotency — T2.

Key = (surface, symbol, decision_id). A retry EDITS the original message_id
instead of sendMessage again.

JSON map at data/runtime/telegram_send_idempotency.json. Best-effort; never
raises into the send path. TTL 24h.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

TTL_SEC = 24 * 3600
_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "runtime" / "telegram_send_idempotency.json"


def _path(p: Path | None) -> Path:
    return p or _DEFAULT


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def lookup(key: str, chat_id: str, *, path: Path | None = None) -> Optional[dict[str, Any]]:
    if not key or not chat_id:
        return None
    store = _load(_path(path))
    rec = store.get(f"{key}|{chat_id}")
    if not isinstance(rec, dict):
        return None
    ts = float(rec.get("ts") or 0)
    if ts and (time.time() - ts) > TTL_SEC:
        return None
    if rec.get("message_id") in (None, "", 0):
        return None
    return rec


def remember(
    key: str,
    chat_id: str,
    message_id: Any,
    *,
    path: Path | None = None,
) -> None:
    if not key or not chat_id or message_id in (None, "", 0):
        return
    dest = _path(path)
    store = _load(dest)
    now = time.time()
    # prune
    drop = [k for k, v in store.items() if not isinstance(v, dict) or (now - float(v.get("ts") or 0)) > TTL_SEC]
    for k in drop:
        store.pop(k, None)
    store[f"{key}|{chat_id}"] = {"message_id": message_id, "ts": now, "chat_id": str(chat_id)}
    try:
        _save(dest, store)
    except OSError:
        pass
