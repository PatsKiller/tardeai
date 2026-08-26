"""TickerResearchState@v1 — current curated view; points at artifacts, does not duplicate prose."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "TickerResearchState@v1"
PATH = "data/cio/ticker_research_state.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_path(root: Path | str) -> Path:
    return Path(root) / PATH


def build_state(
    *,
    symbol: str,
    ticker_guid: str | None,
    security_guid: str | None,
    artifact_guids: list[str],
    support_guids: list[str],
    counter_guids: list[str],
    open_gaps: list[str],
    watermark: str,
    decision: str,
    freshness: str,
    next_review: str,
    catalyst_guids: list[str] | None = None,
    issuer_guid: str | None = None,
    listing_guid: str | None = None,
    curation_id: str | None = None,
    curation_version: int | None = None,
    status: str | None = None,
    last_free_refresh: str | None = None,
    thesis_action: str = "NO_THESIS_ACTION",
) -> dict[str, Any]:
    st = status or ("CURRENT" if freshness == "CURRENT" else freshness)
    return {
        "schema": SCHEMA,
        "symbol": symbol,
        "ticker_guid": ticker_guid,
        "security_guid": security_guid,
        "issuer_guid": issuer_guid,
        "listing_guid": listing_guid,
        "ticker_aliases": [symbol],
        "current_curation_id": curation_id,
        "current_curation_version": curation_version,
        "artifact_guids": artifact_guids,
        "support_evidence": support_guids,
        "counter_evidence": counter_guids,
        "open_gaps": open_gaps,
        "catalyst_event_guids": catalyst_guids or [],
        "evidence_watermark": watermark,
        "decision": decision,
        "freshness": freshness,
        "status": st,
        "last_material_change": None if decision == "NO_NEW_INFO" else _now(),
        "last_free_refresh": last_free_refresh or _now(),
        "last_model_assisted_curation": None,
        "thesis_action": thesis_action,
        "next_review_reason": next_review,
        "updated_at": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def upsert_state(root: Path | str, state: dict[str, Any]) -> dict[str, Any]:
    path = state_path(root)
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
    guid = state.get("ticker_guid") or state.get("symbol")
    kept = [r for r in rows if (r.get("ticker_guid") or r.get("symbol")) != guid]
    # Replay: identical watermark → do not bump version
    prev = next((r for r in rows if (r.get("ticker_guid") or r.get("symbol")) == guid), None)
    if prev and prev.get("evidence_watermark") == state.get("evidence_watermark"):
        return {"wrote": False, "reason": "NO_NEW_INFO", "state": prev}
    kept.append(state)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in kept), encoding="utf-8")
    tmp.replace(path)
    return {"wrote": True, "state": state}
