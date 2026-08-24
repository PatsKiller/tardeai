"""Contradiction lineage. Never silently overwrite conflicting evidence."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "EvidenceContradiction@v1"
PATH = "data/cio/evidence_contradictions.jsonl"
STATUSES = ("OPEN", "RESOLVED_SUPPORT", "RESOLVED_COUNTER", "SUPERSEDED", "INSUFFICIENT_DATA")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def contradiction_id(*, security_guid: str | None, topic: str) -> str:
    payload = f"tradeai:contradiction:{security_guid or ''}|{topic}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def build_contradiction(
    *,
    security_guid: str | None,
    symbol: str,
    topic: str,
    support_guids: list[str],
    counter_guids: list[str],
    status: str = "OPEN",
) -> dict[str, Any]:
    st = status if status in STATUSES else "OPEN"
    return {
        "schema": SCHEMA,
        "contradiction_id": contradiction_id(security_guid=security_guid, topic=topic),
        "security_guid": security_guid,
        "symbol": symbol,
        "topic": topic,
        "support_artifact_guids": support_guids,
        "counter_artifact_guids": counter_guids,
        "status": st,
        "observed_at": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def upsert_contradiction(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    path = Path(root) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    cid = row.get("contradiction_id")
    prev = next((r for r in rows if r.get("contradiction_id") == cid), None)
    if prev and prev.get("status") == row.get("status") and prev.get("support_artifact_guids") == row.get("support_artifact_guids") and prev.get("counter_artifact_guids") == row.get("counter_artifact_guids"):
        return {"wrote": False, "reason": "NO_NEW_INFO", "row": prev}
    kept = [r for r in rows if r.get("contradiction_id") != cid]
    kept.append(row)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in kept), encoding="utf-8")
    tmp.replace(path)
    return {"wrote": True, "row": row}
