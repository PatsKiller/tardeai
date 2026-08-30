"""DeliveryReceipt@v1 — the record that a routing decision was made.

Wave 3C. `NotificationPolicy@v1` decides; this records the decision and the
channel it *would* have used. It sends nothing: `would_send` is a constant
False, there is no adapter call, and a test asserts this PR adds no HTTP or
Telegram send site anywhere.

A receipt for a message that was never sent sounds odd until you need it: it is
what makes "the system stayed quiet" auditable rather than merely believed. The
`dedupe_key` is what stops the same subject generating a receipt every pass.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DELIVERY_RECEIPT_SCHEMA = "DeliveryReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

STORE_REL = "data/cio/cio_delivery_receipts.jsonl"

TELEGRAM, DIGEST, CC, NONE = "telegram", "digest", "cc", "none"
WOULD_CHANNELS = (TELEGRAM, DIGEST, CC, NONE)

# NotificationPolicy decision -> the channel it would have used.
# SUPPRESSED maps to `none`, not to a channel that merely stayed silent: a
# suppressed decision has no destination at all.
_CHANNEL_FOR = {
    "IMMEDIATE": TELEGRAM,
    "DIGEST": DIGEST,
    "COMMAND_CENTER_ONLY": CC,
    "SUPPRESSED": NONE,
}


def dedupe_key(notification_id: Any, decision: Any, day: str) -> str:
    raw = f"{notification_id}|{decision}|{day}"
    return "dk_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def build(decision_row: dict[str, Any], *,
          now: Optional[datetime] = None) -> dict[str, Any]:
    """Build a receipt from a NotificationPolicy@v1 decision row."""
    ts = (now or datetime.now(timezone.utc)).isoformat()
    decision = str(decision_row.get("decision") or "")
    if decision not in _CHANNEL_FOR:
        raise ValueError(f"unknown notification decision: {decision!r}")
    nid = decision_row.get("notification_id")
    return {
        "schema": DELIVERY_RECEIPT_SCHEMA,
        "notification_id": nid,
        # Carry the originating workflow through delivery/audit projections;
        # this is linkage only and does not grant delivery authority.
        "workflow_id": decision_row.get("workflow_id"),
        "generation_id": decision_row.get("generation_id") or decision_row.get("material_generation_id"),
        "plan_id": decision_row.get("plan_id"),
        "decision": decision,
        "would_channel": _CHANNEL_FOR[decision],
        "would_send": False,          # constant by design, never computed
        "dedupe_key": dedupe_key(nid, decision, ts[:10]),
        "reason": decision_row.get("reason"),
        "created_at": ts,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def validate(row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if row.get("schema") != DELIVERY_RECEIPT_SCHEMA:
        problems.append("wrong_schema")
    if not row.get("notification_id"):
        problems.append("missing_notification_id")
    if row.get("would_channel") not in WOULD_CHANNELS:
        problems.append("bad_would_channel")
    if row.get("would_send") is not False:
        problems.append("would_send_must_be_false")
    if not row.get("dedupe_key"):
        problems.append("missing_dedupe_key")
    return problems


def store_path(root: Path | str) -> Path:
    return Path(root) / STORE_REL


def existing_dedupe_keys(root: Path | str) -> set[str]:
    p = store_path(root)
    if not p.is_file():
        return set()
    keys = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("dedupe_key"):
            keys.add(row["dedupe_key"])
    return keys


def persist(root: Path | str, row: dict[str, Any], *,
            seen: Optional[set[str]] = None) -> dict[str, Any]:
    """Append a receipt unless its dedupe_key is already present."""
    problems = validate(row)
    if problems:
        return {"wrote": False, "problems": problems}
    keys = seen if seen is not None else existing_dedupe_keys(root)
    if row["dedupe_key"] in keys:
        return {"wrote": False, "duplicate": True,
                "dedupe_key": row["dedupe_key"]}
    p = store_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    keys.add(row["dedupe_key"])
    return {"wrote": True, "duplicate": False, "path": str(p),
            "dedupe_key": row["dedupe_key"]}
