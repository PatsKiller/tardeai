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
    "EXPIRED",
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
    if prev and all(prev.get(k) == gap.get(k) for k in
                    ("status", "question", "answer_status", "answer_ids", "resolved_by_artifact_guids")):
        return {"wrote": False, "reason": "NO_NEW_INFO", "gap": prev}
    kept = [r for r in rows if r.get("gap_id") != gid]
    kept.append(gap)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in kept), encoding="utf-8")
    tmp.replace(path)
    _register_on_spine(gap)
    return {"wrote": True, "gap": gap}


def _register_on_spine(gap: dict[str, Any]) -> str | None:
    """Make this gap_id joinable to the goal and the question it belongs to.

    `gap_id` does not change: it is registered as-is under source_table
    `research_gaps`. The gap already carries the resolved `security_guid`, so
    no lookup and no mint happens here.

    Fail-safe: the JSONL row is already on disk when this runs. An unlinked gap
    is degraded; a gap lost to a database that was briefly unreachable is not
    recoverable, and that trade is the contract (rule 5).
    """
    sguid = gap.get("security_guid")
    if not sguid:
        return None
    try:
        from scripts.lib.cio_identity_spine import register_on_spine

        return register_on_spine(
            "research_gaps", gap.get("gap_id"), str(sguid),
            semantic_subject=gap.get("symbol"),
        )
    except Exception:  # noqa: BLE001 -- never break the gap write
        return None


def reconcile_research_completion(root: Path | str, request: dict, result: dict, *, critique: dict | None = None) -> dict:
    """Close only explicitly originating gaps with matching, fresh cited answers."""
    from scripts.lib.research_quality import evidence_eligibility
    metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    origins = request.get("gap_ids") or metadata.get("gap_ids") or [request.get("gap_id") or metadata.get("gap_id")]
    if isinstance(origins, str):
        origins = [origins]
    origins = {str(g) for g in origins if g}
    if not origins:
        return {"status": "NO_ORIGIN_GAP", "updated": 0}
    path = Path(root) / PATH
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    changed = []
    missing = set(origins)
    for gap in rows:
        gid = str(gap.get("gap_id") or "")
        if gid not in origins:
            continue
        missing.discard(gid)
        if gap.get("status") in {"RESOLVED_LLM", "RESOLVED_FREE", "NO_LONGER_RELEVANT", "EXPIRED"}:
            continue
        rid = str(result.get("result_id") or "")
        if rid and rid in (gap.get("answer_ids") or []):
            continue
        validation = evidence_eligibility({**request, "symbol": gap.get("symbol"),
                                           "subject_guid": gap.get("security_guid")}, result, critique)
        answers = result.get("answers") or []
        if not isinstance(answers, list):
            answers = []
        matches = [a for a in answers if isinstance(a, dict) and
                   (str(a.get("gap_id") or a.get("question_id") or "") == gid or
                    str(a.get("question") or "").strip() == str(gap.get("question") or "").strip()) and a.get("answer")]
        # Explicit result/request joins alone establish lineage, not answer completeness.
        state, reason = "UNRESOLVED", "no_matching_answer"
        if not validation["eligible"]:
            reason = ";".join(validation["reasons"])
        elif matches:
            state = "ANSWERED" if str((critique or {}).get("verdict") or "").upper() == "VALID" else "PARTIALLY_ANSWERED"
            reason = "matched_origin_question_with_cited_research"
        updated = {**gap, "answer_status": state,
                   "answer_ids": list(gap.get("answer_ids") or []) + ([rid] if rid else []),
                   "lifecycle_events": list(gap.get("lifecycle_events") or []) + [{
                       "at": _now(), "state": state, "reason": reason, "result_id": rid,
                       "research_id": result.get("research_id") or request.get("research_id"),
                       "evidence_refs": validation["evidence_refs"]}]}
        if state == "ANSWERED":
            updated.update(status="RESOLVED_LLM", resolved_at=_now(), resolved_by_artifact_guids=[rid])
        elif gap.get("expires_at"):
            try:
                expiry = datetime.fromisoformat(str(gap["expires_at"]).replace("Z", "+00:00"))
                if expiry.tzinfo and expiry <= datetime.now(timezone.utc):
                    updated.update(status="EXPIRED", answer_status="EXPIRED")
            except ValueError:
                pass
        outcome = upsert_gap(root, updated)
        if outcome["wrote"]:
            changed.append({"gap_id": gid, "answer_status": updated["answer_status"], "result_id": rid})
    return {"status": "RECONCILED", "updated": len(changed), "changes": changed, "missing_origin_ids": sorted(missing)}
