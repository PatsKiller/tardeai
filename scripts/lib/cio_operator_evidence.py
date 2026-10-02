"""Operator-facing CIO evidence composition.

This module only reads existing canonical stores.  It deliberately preserves
the difference between a producer event, a consumption receipt, and a UI
projection; an absent receipt is UNKNOWN, never REJECTED or USED.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOOperatorEvidence@v1"
RESEARCH_SCHEMA = "CIOResearchProvenance@v1"


def _root() -> Path:
    return Path(os.getenv("TRADEAI_CIO_DIR") or Path(__file__).resolve().parents[2] / "data" / "cio")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_matches_decision(row: dict[str, Any], decision_id: str) -> bool:
    """Match an exact decision id without using a symbol or neighboring row."""
    did = str(decision_id or "").strip()
    if not did:
        return True
    values: list[str] = []
    for key in (
        "decision_id", "judgment_decision_id", "cio_case_id", "workflow_id",
        "decision_ids", "decision_refs", "decisions", "consumed_by_decision_ids",
    ):
        value = row.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item not in (None, ""))
    contributions = row.get("contributions")
    if isinstance(contributions, list):
        for contribution in contributions:
            if isinstance(contribution, dict) and _row_matches_decision(contribution, did):
                return True
    return did in values


def _parse_rows(lines: Iterable[str], *, predicate: Any = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and (predicate is None or predicate(row)):
            out.append(row)
    return out


# Composition reads only a bounded window from the end of each store.  Every
# consumer below keeps the most recent rows (100-250); fully parsing the
# 60-120 MB stores on each request cost ~23 s and ~1.6 GB RSS per call.
_COMPOSITION_TAIL_BYTES = int(os.getenv("CIO_EVIDENCE_TAIL_BYTES") or 1024 * 1024)


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()  # discard the partial first line
        return handle.read().decode("utf-8", errors="replace").splitlines()


def _rows(path: Path, *, decision_id: str | None = None) -> list[dict[str, Any]]:
    """Rows for one exact decision (whole store), or the store's recent window.

    Exact lookups stream the whole file but only parse lines that contain the
    decision id, so older rows for the same decision are never dropped and a
    miss does not parse 100+ MB of JSON.
    """
    if not path.is_file():
        return []
    did = str(decision_id or "").strip()
    if did:
        predicate = lambda row: _row_matches_decision(row, did)  # noqa: E731
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return _parse_rows((line for line in handle if did in line), predicate=predicate)
    return _parse_rows(_tail_lines(path, _COMPOSITION_TAIL_BYTES))


def _rows_containing(path: Path, needles: set[str]) -> list[dict[str, Any]]:
    """Whole-store rows whose raw line contains any needle (exact ids)."""
    if not needles or not path.is_file():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return _parse_rows(line for line in handle if any(n in line for n in needles))


def _stamp(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in ("source_as_of", "as_of", "updated_ts", "updated_at", "recorded_at", "created_ts", "created_at", "at", "ts"):
        value = row.get(key)
        if value not in (None, "", []):
            return str(value)
    return None


def _parse_ts(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _latest_stamp(rows: Iterable[dict[str, Any]], *, not_after: datetime | None = None) -> str | None:
    """Latest parseable row clock.  Mixed formats compare as instants, not
    strings, and clocks in the future (beyond a 5-minute skew) are ignored."""
    ceiling = (not_after or datetime.now(timezone.utc)) + timedelta(minutes=5)
    best: tuple[datetime, str] | None = None
    for row in rows:
        raw = _stamp(row)
        parsed = _parse_ts(raw) if raw else None
        if parsed is None or parsed > ceiling:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, str(raw))
    return best[1] if best else None


def _source_version(path: Path) -> str | None:
    """Cheap store version (size + mtime).  Hashing every store per request
    re-read ~600 MB; a content hash is not needed to tell versions apart."""
    if not path.is_file():
        return None
    st = path.stat()
    return f"bytes={st.st_size};mtime_ns={st.st_mtime_ns}"


def _source_meta(path: Path, rows: list[dict[str, Any]], *, exact: bool = False) -> dict[str, Any]:
    return {
        "source_ref": str(path),
        "source_sha": None,
        "source_version": _source_version(path),
        "source_as_of": _latest_stamp(rows),
        "row_count": len(rows),
        "row_scope": "EXACT_DECISION_SCAN" if exact else "RECENT_WINDOW",
        "evidence_class": "DURABLE_RUNTIME_ARTIFACT" if path.is_file() else "UNAVAILABLE",
    }


def _freshness(source_as_of: str | None) -> str:
    """Name freshness only when a source clock actually exists."""
    return "OBSERVED" if source_as_of else "UNKNOWN"


def _age_seconds(source_as_of: str | None, composition_as_of: str) -> int | None:
    if not source_as_of:
        return None
    try:
        source = datetime.fromisoformat(str(source_as_of).replace("Z", "+00:00"))
        composed = datetime.fromisoformat(str(composition_as_of).replace("Z", "+00:00"))
        if source.tzinfo is None:
            source = source.replace(tzinfo=timezone.utc)
        if composed.tzinfo is None:
            composed = composed.replace(tzinfo=timezone.utc)
        return max(0, int((composed - source).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def _row_refs(row: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item not in (None, ""))
    return sorted({value for value in values if value.strip()})


def _evidence_ids(row: dict[str, Any]) -> list[str]:
    return _row_refs(
        row,
        "outcome_ids", "supporting_outcome_ids", "source_outcome_ids",
        "evidence_refs", "evidence_ids", "outcome_id", "outcome_ref",
    )


def _explicit_used(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("state") or row.get("event") or "").upper()
    if status in {"USED", "USED_IN_JUDGMENT", "ADVISORY_USED", "CONSUMED"}:
        return True
    for key in ("used_in_judgment", "used_in_decision", "advisory_use", "consumed_by", "consumption_receipt_id"):
        value = row.get(key)
        if value is True or (isinstance(value, (list, dict)) and bool(value)):
            return True
        if isinstance(value, str) and value.strip() and value.strip().upper() not in {"UNKNOWN", "FALSE", "NONE"}:
            return True
    return False


def _explicit_rejected(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("state") or row.get("event") or "").upper()
    reason = (
        row.get("rejection_reason")
        or row.get("reason_rejected")
        or row.get("rejected_reason")
        or row.get("rejected_because")
        or row.get("rejection_reasons")
    )
    # A generic request/producer ``reason`` is not a rejection receipt.  A
    # research artifact is rejected only when the canonical row carries an
    # explicit rejection field or a rejection state with a reason.
    return bool(reason) and (status in {"REJECTED", "DISMISSED", "NOT_USED", "RESEARCH_REJECTED"} or any(
        row.get(key) not in (None, "", [])
        for key in ("rejection_reason", "reason_rejected", "rejected_reason", "rejected_because", "rejection_reasons")
    ))


def _artifact_status(row: dict[str, Any], *, result: bool, source_name: str) -> str:
    if _explicit_used(row):
        return "USED_IN_JUDGMENT"
    if _explicit_rejected(row):
        return "REJECTED"
    retrieved = bool(
        row.get("retrieved_at")
        or row.get("retrieved_ts")
        or row.get("retrieved") is True
        or result
        or source_name in {"web_evidence_provenance.jsonl", "security_research_spine.jsonl"}
    )
    return "RETRIEVED" if retrieved else "UNKNOWN"


def _research_rows(path: Path, rows: Iterable[dict[str, Any]] | None = None) -> Iterable[dict[str, Any]]:
    """Yield artifact-shaped rows from existing research products.

    SecurityResearchSpine is a canonical projection whose contributions carry
    artifact ids; the spine envelope itself is not a new artifact and must not
    produce a synthetic ``UNKNOWN`` record.
    """
    for row in rows if rows is not None else _rows(path):
        if path.name == "security_research_spine.jsonl":
            contributions = row.get("contributions")
            if isinstance(contributions, list) and contributions:
                for contribution in contributions:
                    if not isinstance(contribution, dict):
                        continue
                    if not (contribution.get("artifact_id") or contribution.get("research_id") or contribution.get("refs")):
                        continue
                    yield {**row, **contribution, "symbol": contribution.get("symbol") or row.get("symbol")}
                continue
            if not (row.get("artifact_id") or row.get("research_id") or row.get("result_id")):
                continue
        yield row


def _research_artifact(row: dict[str, Any], *, source_name: str) -> dict[str, Any] | None:
    artifact_id = row.get("result_id") or row.get("research_id") or row.get("artifact_id") or row.get("id")
    if not artifact_id:
        return None
    status = _artifact_status(
        row,
        result=source_name == "hermes_research_results.jsonl",
        source_name=source_name,
    )
    entities = row.get("symbols") or row.get("affected_entities")
    if isinstance(entities, str):
        entities = [entities]
    if not isinstance(entities, list):
        entities = [row.get("symbol")] if row.get("symbol") else []
    decision_ids = (
        row.get("decision_ids")
        or row.get("decision_refs")
        or row.get("decisions")
        or row.get("consumed_by_decision_ids")
        or []
    )
    if isinstance(decision_ids, str):
        decision_ids = [decision_ids]
    direct_decision_id = row.get("decision_id") or row.get("cio_case_id") or row.get("judgment_decision_id")
    if direct_decision_id and direct_decision_id not in decision_ids:
        decision_ids = [*decision_ids, direct_decision_id]
    thesis_refs = row.get("thesis_refs") or row.get("thesis_ids") or row.get("refs") or []
    if isinstance(thesis_refs, str):
        thesis_refs = [thesis_refs]
    decision_ids = sorted({str(value) for value in decision_ids if value not in (None, "")})
    affected_entities = sorted({str(value) for value in entities if value not in (None, "")})
    return {
        "artifact_id": str(artifact_id),
        "research_id": row.get("research_id") or (str(artifact_id) if source_name == "hermes_research_results.jsonl" else None),
        "status": status,
        "source_type": row.get("source_type") or row.get("research_type") or row.get("provider") or source_name.removesuffix(".jsonl"),
        "source": row.get("source") or row.get("publisher") or source_name,
        "publisher": row.get("publisher") or row.get("source"),
        "source_url": row.get("url") or row.get("source_url"),
        "source_ref": row.get("source_ref") or row.get("source_store") or source_name,
        "publication_date": row.get("publication_date") or row.get("published_at"),
        "retrieved_at": row.get("retrieved_at") or row.get("retrieved_ts") or _stamp(row),
        "source_as_of": row.get("source_as_of") or row.get("as_of") or _stamp(row),
        "affected_entities": affected_entities,
        "subject_guid": row.get("subject_guid") or row.get("issuer_guid"),
        "research_run_id": row.get("research_run_id") or row.get("run_id") or row.get("research_run"),
        "agent_model": row.get("agent_model") or row.get("model") or row.get("model_used") or row.get("provider"),
        "relevance": row.get("relevance"),
        "support_or_challenge": row.get("support_or_challenge") or row.get("stance"),
        "reason_used_or_rejected": row.get("use_reason") or row.get("reason_used") or row.get("rejection_reason") or row.get("reason_rejected") or row.get("rejected_reason"),
        "decision_id": direct_decision_id,
        "decision_ids": decision_ids,
        "trace_id": row.get("trace_id") or row.get("trace"),
        "lineage_id": row.get("lineage_id"),
        "thesis_refs": thesis_refs,
        # Identifiers only: relationships remain resolved from existing stores.
        "related_decisions": decision_ids,
        "related_securities": affected_entities,
        "evidence_class": row.get("evidence_class") or "RESEARCH_ARTIFACT",
    }


def _merge_research_artifact(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    rank = {"UNKNOWN": 0, "RETRIEVED": 1, "REJECTED": 2, "USED_IN_JUDGMENT": 3}
    if not existing:
        return dict(candidate)
    merged = dict(existing)
    if rank.get(str(candidate.get("status")), 0) > rank.get(str(existing.get("status")), 0):
        merged["status"] = candidate["status"]
    for key, value in candidate.items():
        if value in (None, "", []):
            continue
        if key in {"affected_entities", "decision_ids", "thesis_refs", "related_decisions", "related_securities"}:
            prior = existing.get(key) if isinstance(existing.get(key), list) else []
            incoming = value if isinstance(value, list) else [value]
            merged[key] = sorted({str(item) for item in [*prior, *incoming] if item not in (None, "")})
        elif merged.get(key) in (None, ""):
            merged[key] = value
    if not merged.get("decision_id") and merged.get("decision_ids"):
        merged["decision_id"] = merged["decision_ids"][0]
    return merged


def _research_provenance(root: Path, *, decision_id: str | None = None) -> dict[str, Any]:
    paths = [
        root / "hermes_research_results.jsonl",
        root / "web_evidence_provenance.jsonl",
        root / "security_research_spine.jsonl",
    ]
    by_artifact: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for path in paths:
        # Exact decision lookups read only rows that reference the decision;
        # the global view reads each store's recent window.
        rows = _rows(path, decision_id=decision_id)
        sources.append({"source": path.name, **_source_meta(path, rows, exact=bool(decision_id))})
        if decision_id:
            # A shared artifact keeps every decision that referenced it: pull
            # all rows of the artifacts this decision touched (second pass,
            # still prefiltered by artifact id).
            ids = {a["artifact_id"] for r in _research_rows(path, rows)
                   if (a := _research_artifact(r, source_name=path.name))}
            rows = _rows_containing(path, ids)
        for row in list(_research_rows(path, rows))[-250:]:
            artifact = _research_artifact(row, source_name=path.name)
            if not artifact:
                continue
            artifact_id = artifact["artifact_id"]
            by_artifact[artifact_id] = _merge_research_artifact(by_artifact.get(artifact_id, {}), artifact)
    artifacts = list(by_artifact.values())
    did = str(decision_id or "").strip()
    if did:
        # Never hand a decision the global artifact list: keep only artifacts
        # that carry this exact decision id.
        artifacts = [
            a for a in artifacts
            if a.get("decision_id") == did or did in (a.get("decision_ids") or [])
        ]
    artifacts.sort(key=lambda item: (str(item.get("retrieved_at") or ""), item["artifact_id"]), reverse=True)
    return {
        "schema": RESEARCH_SCHEMA,
        "decision_id": did or None,
        "sources": sources,
        "artifacts": artifacts,
        "retrieved": [a for a in artifacts if a["status"] == "RETRIEVED"],
        "used_in_judgment": [a for a in artifacts if a["status"] == "USED_IN_JUDGMENT"],
        "rejected": [a for a in artifacts if a["status"] == "REJECTED"],
        "unknown": [a for a in artifacts if a["status"] == "UNKNOWN"],
        "counts": {
            "retrieved": sum(a["status"] == "RETRIEVED" for a in artifacts),
            "used_in_judgment": sum(a["status"] == "USED_IN_JUDGMENT" for a in artifacts),
            "rejected": sum(a["status"] == "REJECTED" for a in artifacts),
            "unknown": sum(a["status"] == "UNKNOWN" for a in artifacts),
        },
        "source_as_of": max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None),
    }


def build_research_provenance(
    root: Path | None = None,
    *,
    decision_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Build the additive research projection, optionally for one exact decision.

    Filtering is by decision id only.  A shared symbol is not a join key because
    historical decisions for that symbol must remain independently resolvable.
    """
    block = _research_provenance(root or _root(), decision_id=decision_id)
    did = str(decision_id or "").strip()
    if did:
        artifacts = [
            artifact for artifact in block["artifacts"]
            if artifact.get("decision_id") == did or did in (artifact.get("decision_ids") or [])
        ]
        block = {
            **block,
            "artifacts": artifacts,
            "retrieved": [a for a in artifacts if a["status"] == "RETRIEVED"],
            "used_in_judgment": [a for a in artifacts if a["status"] == "USED_IN_JUDGMENT"],
            "rejected": [a for a in artifacts if a["status"] == "REJECTED"],
            "unknown": [a for a in artifacts if a["status"] == "UNKNOWN"],
            "counts": {
                "retrieved": sum(a["status"] == "RETRIEVED" for a in artifacts),
                "used_in_judgment": sum(a["status"] == "USED_IN_JUDGMENT" for a in artifacts),
                "rejected": sum(a["status"] == "REJECTED" for a in artifacts),
                "unknown": sum(a["status"] == "UNKNOWN" for a in artifacts),
            },
            "decision_id": did,
        }
    block["authority"] = AUTHORITY
    block["financial_action"] = False
    block["mutation"] = False
    block["composition_as_of"] = now or _now()
    block["freshness"] = _freshness(block.get("source_as_of"))
    block["producer"] = "scripts.lib.cio_operator_evidence"
    return block


def _cognition(root: Path, *, decision_id: str | None = None) -> dict[str, Any]:
    paths = {
        "memory_retrieval": root / "aif_memory_retrievals.jsonl",
        "memory_context": root / "memory_contexts.jsonl",
        "research_lineage": root / "intelligence_lineages.jsonl",
        "operator_feedback": root / "operator_ticker_feedback.jsonl",
    }
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for kind, path in paths.items():
        rows = _rows(path, decision_id=decision_id)
        sources.append({"source": path.name, **_source_meta(path, rows, exact=bool(decision_id))})
        for row in rows[-100:]:
            retrieved = kind in {"memory_retrieval", "memory_context", "research_lineage"} and bool(
                row.get("retrieval_receipt_id") or row.get("memory_ids") or row.get("has_context") or row.get("result_id")
            )
            used = _explicit_used(row)
            changed = bool(
                row.get("changed_question") is True
                or row.get("changed_view") is True
                or row.get("question_changed") is True
                or row.get("view_changed") is True
                or row.get("influence_receipt_id")
            )
            contradictory = bool(
                row.get("contradictory") is True
                or row.get("counter") is True
                or row.get("contradiction_receipt_id")
            )
            items.append({
                "kind": kind,
                "id": row.get("context_id") or row.get("retrieval_receipt_id") or row.get("memory_id") or row.get("feedback_id"),
                "decision_id": row.get("decision_id") or row.get("judgment_decision_id"),
                "availability": "AVAILABLE",
                "state": "USED" if used else ("RETRIEVED" if retrieved else "AVAILABLE"),
                "retrieved": retrieved,
                "used": used,
                "changed_question_or_view": changed,
                "contradictory": contradictory,
                "symbol": row.get("symbol") or ((row.get("symbols") or [None])[0] if isinstance(row.get("symbols"), list) else None),
                "summary": row.get("summary") or row.get("query") or row.get("decision") or row.get("event"),
                "source_ref": str(path),
                "source_as_of": _stamp(row),
                "evidence_class": row.get("evidence_class") or "INSTITUTIONAL_COGNITION",
                "influence": "PROVEN" if used else "NOT_PROVEN",
            })
    source_as_of = max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None)
    return {
        "office_truth_boundary": ["price", "holdings", "cash", "orders", "broker_state", "risk_limits"],
        "items": items,
        "sources": sources,
        "source_as_of": source_as_of,
        "freshness": _freshness(source_as_of),
        "memory_behavior_influence": 0,
        "authority": "NON_AUTHORITATIVE_CONTEXT",
    }


def _learning_row(row: dict[str, Any], *, origin: str) -> dict[str, Any]:
    evidence_ids = _evidence_ids(row)
    raw_status = str(row.get("promotion_stage") or row.get("status") or "UNKNOWN").upper()
    return {
        **row,
        "evidence_ids": evidence_ids,
        "evidence_state": "PROVEN" if evidence_ids else "INSUFFICIENT_EVIDENCE",
        "origin": origin,
        "outcome_ids": _row_refs(row, "outcome_ids", "supporting_outcome_ids", "outcome_id"),
        "status": raw_status,
    }


def _learning(root: Path, *, decision_id: str | None = None) -> dict[str, Any]:
    paths = {
        "outcomes": root / "advisory_outcomes_v1.jsonl",
        "checkpoints": root / "outcome_checkpoints.jsonl",
        "lessons": root / "lesson_candidates.jsonl",
        "experiments": root / "shadow_experiments.jsonl",
        "hypotheses": root / "hypotheses.jsonl",
        "hypothesis_candidates": root / "hypothesis_candidates.jsonl",
        "operator_learning": root / "cio_operator_learning.jsonl",
        "instrument_records": root / "cio_instrument_records.jsonl",
    }
    rows_by_kind = {kind: _rows(path, decision_id=decision_id) for kind, path in paths.items()}
    sources = [{"source": path.name, **_source_meta(path, rows_by_kind[kind], exact=bool(decision_id))} for kind, path in paths.items()]
    outcomes = rows_by_kind["outcomes"]
    settled_statuses = {"OUTCOME_EVALUATED", "SETTLED", "SETTLED_OUTCOME", "CONFIRMED", "REFUTED", "EXPIRED"}
    settled = [r for r in outcomes if str(r.get("status") or r.get("outcome") or "").upper() in settled_statuses]
    pending = [r for r in outcomes if r not in settled]
    settled_ids = sorted({str(r.get("outcome_id") or r.get("id")) for r in settled if r.get("outcome_id") or r.get("id")})
    successful_statuses = {"SUCCESS", "POSITIVE", "CONFIRMED", "WIN", "SUPPORTED"}
    successful_count = sum(1 for row in settled if str(row.get("result") or row.get("outcome") or row.get("status") or "").upper() in successful_statuses)
    sample_size = len(settled_ids) if paths["outcomes"].is_file() else None
    success_rate = (successful_count / sample_size) if sample_size else None

    lessons_raw = rows_by_kind["lessons"] + [r for r in rows_by_kind["operator_learning"] if r.get("lesson_id") or r.get("statement")]
    lessons = [_learning_row(row, origin=("RESEARCH_DERIVED" if str(row.get("lesson_provenance") or row.get("origin") or "").upper() == "RESEARCH_DERIVED" else "OUTCOME_DERIVED" if _evidence_ids(row) else "UNKNOWN")) for row in lessons_raw[-100:]]
    hypotheses_raw = rows_by_kind["hypotheses"] + rows_by_kind["hypothesis_candidates"]
    hypotheses = [_learning_row(row, origin=str(row.get("origin") or "UNKNOWN").upper()) for row in hypotheses_raw[-100:]]
    experiments = rows_by_kind["experiments"][-100:]

    beliefs: list[dict[str, Any]] = []
    for record in rows_by_kind["instrument_records"]:
        for belief in record.get("beliefs") or []:
            if not isinstance(belief, dict):
                continue
            outcome_ids = _row_refs(belief, "outcome_ids", "outcome_id")
            beliefs.append({
                **belief,
                "belief_id": belief.get("belief_id") or belief.get("belief_key"),
                "outcome_ids": outcome_ids,
                "sample_size": belief.get("sample_size") if belief.get("sample_size") is not None else len(outcome_ids),
                "evidence_state": "PROVEN" if outcome_ids else "INSUFFICIENT_EVIDENCE",
                "state": str(belief.get("status") or belief.get("state") or "UNKNOWN").upper(),
            })
    beliefs.extend({
        "belief_id": row.get("belief_id"),
        "outcome_ids": row["outcome_ids"],
        "sample_size": row.get("sample_size"),
        "success_rate": row.get("success_rate"),
        "state": row.get("status") or "UNKNOWN",
        "evidence_state": row["evidence_state"],
    } for row in lessons if row.get("belief_id") and row.get("belief_id") not in {b.get("belief_id") for b in beliefs})

    review_ready = [row for row in [*lessons, *hypotheses] if row.get("status") == "REVIEW_READY" and row.get("evidence_ids")]
    maturity_state = "REVIEW_READY" if review_ready else "INSUFFICIENT_EVIDENCE" if not sample_size or sample_size < 5 else "OBSERVATION_ONLY"
    source_as_of = max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None)
    return {
        "settled_outcomes": [{"outcome_id": r.get("outcome_id") or r.get("id"), "decision_id": r.get("decision_id"), "status": r.get("status") or r.get("outcome"), "source_as_of": _stamp(r)} for r in settled[-100:]],
        "pending_outcomes": [{"outcome_id": r.get("outcome_id") or r.get("id"), "decision_id": r.get("decision_id"), "status": r.get("status") or r.get("outcome"), "source_as_of": _stamp(r)} for r in pending[-100:]],
        "beliefs": beliefs[-100:],
        "lessons": lessons,
        "research_derived_lessons": [row for row in lessons if row.get("origin") == "RESEARCH_DERIVED"],
        "outcome_derived_lessons": [row for row in lessons if row.get("origin") == "OUTCOME_DERIVED"],
        "hypotheses": hypotheses,
        "experiments": experiments,
        "checkpoint_count": len(rows_by_kind["checkpoints"]),
        "sample_size": sample_size,
        "successful_count": successful_count if paths["outcomes"].is_file() else None,
        "success_rate": success_rate,
        "horizon": next((r.get("horizon") for r in [*beliefs, *lessons] if r.get("horizon")), None),
        "calibration": next((r.get("calibration") for r in [*beliefs, *lessons] if r.get("calibration") is not None), None),
        "maturity_state": maturity_state,
        "review_ready": review_ready,
        "sources": sources,
        "source_as_of": source_as_of,
        "freshness": _freshness(source_as_of),
        "memory_behavior_influence": 0,
        "self_promotion": False,
    }


def _capability_coverage(root: Path, *, composition_as_of: str | None = None) -> dict[str, Any]:
    """Classify capabilities from observed producer/consumer artifacts.

    A missing React field is never evidence of DARK.  DARK means a declared
    producer exists but no runtime producer rows are observable; PARTIAL means
    only one side of the producer/consumer edge is observable; LIVE requires an
    explicit consumer reference as well as producer rows.
    """
    specs = [
        ("InstrumentRecord", "scripts.lib.cio_instrument_record", "cio_instrument_records.jsonl", ("cio_wake_jobs.jsonl", "intelligence_lineages.jsonl")),
        ("identity resolution", "scripts.lib.cio_identity", "security_research_spine.jsonl", ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl")),
        ("office truth", "scripts.lib.cio_current_truth", "cio_events.jsonl", ("cio_workflow_lineage.jsonl",)),
        ("persistent cognition", "scripts.lib.agent_durable_memory", "memory_contexts.jsonl", ("intelligence_lineages.jsonl", "context_use_receipts.jsonl")),
        ("memory retrieval", "scripts.lib.agent_durable_memory", "aif_memory_retrievals.jsonl", ("context_use_receipts.jsonl",)),
        ("Hermes research", "scripts.lib.cio_hermes_research", "hermes_research_requests.jsonl", ("hermes_research_projection.json", "intelligence_lineages.jsonl")),
        ("external research", "scripts.lib.cio_hermes_research", "security_research_spine.jsonl", ("intelligence_lineages.jsonl",)),
        ("specialist artifacts", "scripts.lib.cio_specialist_artifact", "cio_specialist_artifacts.jsonl", ("cio_workflow_lineage.jsonl",)),
        ("specialist disagreement", "scripts.lib.cio_specialist_artifact", "cio_workflow_lineage.jsonl", ("intelligence_lineages.jsonl",)),
        ("CIO synthesis", "scripts.lib.cio_committee", "cio_workflow_lineage.jsonl", ("cio_plans.jsonl", "cio_production_cases.jsonl")),
        ("judgment", "scripts.lib.cio_run", "cio_workflow_lineage.jsonl", ("cio_action_ledger.jsonl",)),
        ("commitment", "scripts.lib.cio_action_ledger", "cio_action_ledger.jsonl", ("operator_notification_outbox.jsonl",)),
        ("notification policy", "scripts.lib.cio_notification_signal", "cio_notification_audit.jsonl", ("operator_notification_outbox.jsonl",)),
        ("delivery/outbox", "scripts.lib.cio_delivery_mode", "operator_notification_outbox.jsonl", ("cio_telegram_receipts.jsonl",)),
        ("operator feedback", "scripts.lib.cio_feedback_learning_v1", "operator_ticker_feedback.jsonl", ("cio_workflow_lineage.jsonl",)),
        ("outcome checkpoint", "scripts.lib.r17_checkpoint_binding", "outcome_checkpoints.jsonl", ("advisory_outcomes_v1.jsonl",)),
        ("outcome settlement", "scripts.lib.cio_outcome_store", "advisory_outcomes_v1.jsonl", ("lesson_candidates.jsonl",)),
        ("belief writer", "scripts.lib.cio_belief_writer", "cio_instrument_records.jsonl", ("memory_contexts.jsonl",)),
        ("lesson", "scripts.lib.memory_consolidator", "lesson_candidates.jsonl", ("cio_operator_learning.jsonl",)),
        ("hypothesis", "scripts.lib.cio_institutional_learning", "hypothesis_candidates.jsonl", ("shadow_experiments.jsonl",)),
        ("graph propagation", "scripts.lib.ticker_knowledge_graph", "ticker_research_graph.jsonl", ("intelligence_lineages.jsonl",)),
        ("canon retrieval", "scripts.lib.cio_canon", "canon_retrievals.jsonl", ("cio_workflow_lineage.jsonl",)),
        ("historical analogue retrieval", "scripts.lib.cio_analogue_retrieval", "historical_analogues.jsonl", ("cio_workflow_lineage.jsonl",)),
    ]
    composed = composition_as_of or _now()
    rows: list[dict[str, Any]] = []
    repo_root = Path(__file__).resolve().parents[2]
    for capability, producer, producer_name, consumer_names in specs:
        producer_path = root / producer_name
        producer_rows = _rows(producer_path)
        consumer_rows_by_path = {name: _rows(root / name) for name in consumer_names}
        consumer_rows = [row for values in consumer_rows_by_path.values() for row in values]
        # A consumer row counts as direct only when it carries an explicit
        # producer/source/artifact reference.  Store existence alone is not a
        # proof that this capability was consumed.
        producer_tokens = {producer_name, producer_name.removesuffix(".jsonl"), capability.lower()}
        direct_consumers = [
            row for row in consumer_rows
            if any(token in " ".join(_row_refs(row, "source_ref", "source_refs", "producer", "producer_id", "input_ref", "input_refs", "artifact_id", "capability")).lower() for token in producer_tokens)
        ]
        module_path = repo_root / (producer.replace(".", "/") + ".py")
        producer_declared = producer_path.is_file() or module_path.is_file()
        if producer_rows and direct_consumers:
            state = "LIVE"
            reason = "timestamped producer rows and an explicit consumer reference were observed"
        elif producer_rows or consumer_rows:
            state = "PARTIAL"
            reason = "runtime evidence exists on only one side, or the consumer lacks an explicit edge reference"
        elif producer_declared and consumer_names:
            state = "DARK"
            reason = "declared producer exists but no runtime producer or consumer evidence was observed"
        elif producer_declared:
            state = "UNWIRED"
            reason = "declared producer has no declared consumer contract"
        else:
            state = "UNKNOWN"
            reason = "producer contract and runtime artifact could not be verified"
        ceiling = _parse_ts(composed)
        last_producer = _latest_stamp(producer_rows, not_after=ceiling)
        last_consumer = _latest_stamp(direct_consumers, not_after=ceiling)
        rows.append({
            "capability": capability,
            "contract": producer,
            "producer": producer,
            "consumer": ", ".join(consumer_names) if consumer_names else None,
            "last_producer_event": last_producer,
            "last_consumer_event": last_consumer,
            "last_produced_at": last_producer,
            "last_consumed_at": last_consumer,
            "durable_artifact": str(producer_path),
            "artifact_age": _age_seconds(last_producer, composed),
            "current_status": state,
            "state": state,
            "reason": reason,
            "source_sha": None,
            "source_version": _source_version(producer_path),
            "evidence_class": "RUNTIME_ARTIFACT_CENSUS",
        })
    counts = {state: sum(row["state"] == state for row in rows) for state in ("LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN")}
    source_as_of = max((r["last_produced_at"] for r in rows if r["last_produced_at"]), default=None)
    return {"rows": rows, "counts": counts, "source_as_of": source_as_of, "freshness": _freshness(source_as_of)}


def build_operator_evidence(
    *, now: str | None = None, decision_id: str | None = None,
    include_coverage: bool = True,
) -> dict[str, Any]:
    root = _root()
    composed = now or _now()
    research = _research_provenance(root, decision_id=decision_id)
    cognition = _cognition(root, decision_id=decision_id)
    learning = _learning(root, decision_id=decision_id)
    coverage = _capability_coverage(root, composition_as_of=composed) if include_coverage else {
        "rows": [],
        "counts": {state: 0 for state in ("LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN")},
        "source_as_of": None,
        "freshness": "UNKNOWN",
        "reason": "omitted from exact decision lookup; unrelated capability stores are not scanned",
    }
    blocks = {"research": research, "institutional_cognition": cognition, "learning": learning, "capability_coverage": coverage}
    for block in blocks.values():
        block["composition_as_of"] = composed
        block["producer"] = "scripts.lib.cio_operator_evidence"
        block["freshness"] = block.get("freshness") or _freshness(block.get("source_as_of"))
        block["authority"] = AUTHORITY
    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "mutation": False,
        "memory_behavior_influence": 0,
        "source_as_of": min((b["source_as_of"] for b in blocks.values() if b.get("source_as_of")), default=None),
        "composition_as_of": composed,
        "blocks": blocks,
    }
