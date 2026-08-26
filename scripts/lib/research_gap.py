"""ResearchGap@v1 — missing information, not LLM age."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchGap@v1"
PATH = "data/cio/research_gaps.jsonl"
STATUSES = (
    "OPEN",
    "FREE_FIRST_PENDING",
    "RESOLVED_FREE",
    "LLM_ELIGIBLE_NOT_AUTHORIZED",
    "RESOLVED_LLM",
    "NO_LONGER_RELEVANT",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def gap_id(*, security_guid: str | None, reason: str, question: str) -> str:
    payload = f"tradeai:gap:{security_guid or ''}|{reason}|{question}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def build_gap(
    *,
    security_guid: str | None,
    symbol: str,
    reason: str,
    question: str,
    materiality: str = "low",
    required_evidence_type: str = "unknown",
    portfolio_relevance: bool = False,
    thesis_relevance: bool = False,
    status: str = "OPEN",
) -> dict[str, Any]:
    st = status if status in STATUSES else "OPEN"
    return {
        "schema": SCHEMA,
        "gap_id": gap_id(security_guid=security_guid, reason=reason, question=question),
        "security_guid": security_guid,
        "symbol": symbol,
        "created_at": _now(),
        "reason": reason,
        "materiality": materiality,
        "question": question,
        "required_evidence_type": required_evidence_type,
        "portfolio_relevance": portfolio_relevance,
        "thesis_relevance": thesis_relevance,
        "status": st,
        "resolved_by_artifact_guids": [],
        "resolved_at": None,
        "authority": AUTHORITY,
        "financial_action": False,
        "note": "Gap is missing information, not LLM age",
    }


def should_create_gap(*, hermes_resolved: bool, material_stale: bool, contradiction_open: bool, need_data: bool) -> bool:
    if hermes_resolved and not contradiction_open and not need_data and not material_stale:
        return False
    return bool(material_stale or contradiction_open or need_data)


def upsert_gap(root: Path | str, gap: dict[str, Any]) -> dict[str, Any]:
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
    gid = gap.get("gap_id")
    prev = next((r for r in rows if r.get("gap_id") == gid), None)
    if prev and prev.get("status") == gap.get("status") and prev.get("question") == gap.get("question"):
        return {"wrote": False, "reason": "NO_NEW_INFO", "gap": prev}
    kept = [r for r in rows if r.get("gap_id") != gid]
    kept.append(gap)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in kept), encoding="utf-8")
    tmp.replace(path)
    return {"wrote": True, "gap": gap}
