"""Pure incident identity for SIEM projections; never changes alert lifecycle.

Repeated 2026-10-06 stop and ATM observations differed only in changing prose or
their embedded log timestamp. Keep those observations together when the saved
evidence identifies the same condition, without merging accounts or orders.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

_DB_LOG_PREFIX = re.compile(
    r"\ADB_CONNECTION: (?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3,6}) (?P<message>.+)\Z",
    re.DOTALL,
)


def _identifier(value: Any) -> str | None:
    # A container or bool is not an identity, even if its string form is stable.
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _payload(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, Mapping) else {}


def incident_key(row: Mapping[str, Any]) -> str:
    """Return an opaque, source-scoped key from an existing alert event row.

    Complete stop identities outrank condition_key so adding this key to a new
    observation does not split it from otherwise identical historical events.
    Other sources can supply their existing condition_key. Unknown identities
    retain their full text; no generic number, price, or date removal is safe.
    A row lacking text and both durable identifiers is refused, not conflated
    with other empty records.
    """
    source = _identifier(row.get("source_script")) or ""
    alert_type = _identifier(row.get("alert_type")) or ""
    payload = _payload(row.get("parsed_payload"))
    parts: list[Any] = [source, alert_type]

    stop_fields = tuple(_identifier(payload.get(field)) for field in ("account", "order_id", "symbol", "condition"))
    if source == "stop_health" and all(value is not None for value in stop_fields):
        parts.extend(["stop", *stop_fields])
    elif condition_key := _identifier(payload.get("condition_key")):
        parts.extend(["condition", condition_key])
    elif isinstance(text := row.get("raw_text"), str) and text.strip():
        # Only this observed log prefix has evidence that the timestamp is not
        # part of the failure identity. Every byte of its message stays intact.
        match = _DB_LOG_PREFIX.fullmatch(text) if source.endswith(".log") else None
        if match:
            try:
                datetime.strptime(match["timestamp"], "%Y-%m-%d %H:%M:%S,%f")
            except ValueError:
                match = None
        parts.extend(["db_log", match["message"]] if match else ["text", text])
    elif uid := _identifier(row.get("alert_uid")):
        parts.extend(["uid", uid])
    elif row_id := _identifier(row.get("id")):
        parts.extend(["id", row_id])
    else:
        raise ValueError("SIEM incident requires text, alert_uid, or id when condition identity is unavailable")

    encoded = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return "siem:v1:" + hashlib.sha256(encoded).hexdigest()
