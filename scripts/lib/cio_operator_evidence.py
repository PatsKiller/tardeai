"""Operator-facing CIO evidence composition.

This module only reads existing canonical stores.  It deliberately preserves
the difference between a producer event, a consumption receipt, and a UI
projection; an absent receipt is UNKNOWN, never REJECTED or USED.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOOperatorEvidence@v1"


def _root() -> Path:
    return Path(os.getenv("TRADEAI_CIO_DIR") or Path(__file__).resolve().parents[2] / "data" / "cio")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _stamp(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in ("source_as_of", "as_of", "updated_ts", "updated_at", "recorded_at", "created_ts", "created_at", "at", "ts"):
        value = row.get(key)
        if value not in (None, "", []):
            return str(value)
    return None


def _latest_stamp(rows: Iterable[dict[str, Any]]) -> str | None:
    values = [v for row in rows if (v := _stamp(row))]
    return max(values) if values else None


def _source_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_meta(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_ref": str(path),
        "source_sha": _source_sha(path),
        "source_as_of": _latest_stamp(rows),
        "row_count": len(rows),
        "evidence_class": "DURABLE_RUNTIME_ARTIFACT" if path.is_file() else "UNAVAILABLE",
    }


def _explicit_used(row: dict[str, Any]) -> bool:
    for key in ("used_in_judgment", "used_in_decision", "advisory_use", "consumed_by", "consumption_receipt_id"):
        value = row.get(key)
        if value is True or (isinstance(value, (list, dict)) and bool(value)):
            return True
        if isinstance(value, str) and value.strip() and value.strip().upper() not in {"UNKNOWN", "FALSE", "NONE"}:
            return True
    return False


def _explicit_rejected(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("decision") or "").upper()
    reason = row.get("rejection_reason") or row.get("reason_rejected") or row.get("rejected_reason")
    return bool(reason) or status in {"REJECTED", "DISMISSED", "NOT_USED"}


def _artifact_status(row: dict[str, Any], *, result: bool) -> str:
    if _explicit_used(row):
        return "USED_IN_JUDGMENT"
    if _explicit_rejected(row):
        return "REJECTED"
    return "RETRIEVED" if result else "UNKNOWN"


def _research_provenance(root: Path) -> dict[str, Any]:
    paths = [
        root / "hermes_research_results.jsonl",
        root / "web_evidence_provenance.jsonl",
        root / "security_research_spine.jsonl",
    ]
    artifacts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for path in paths:
        rows = _rows(path)
        sources.append({"source": path.name, **_source_meta(path, rows)})
        for row in rows[-250:]:
            artifact_id = row.get("result_id") or row.get("research_id") or row.get("artifact_id") or row.get("id")
            # Spine rows are thesis records, not automatically research evidence.
            if not artifact_id and path.name != "security_research_spine.jsonl":
                continue
            status = _artifact_status(row, result=path.name == "hermes_research_results.jsonl")
            artifacts.append({
                "artifact_id": str(artifact_id or "UNKNOWN"),
                "status": status,
                "source_type": row.get("source_type") or row.get("provider") or path.stem,
                "source": row.get("source") or row.get("publisher") or path.name,
                "source_url": row.get("url") or row.get("source_url") or row.get("source_ref"),
                "publication_date": row.get("publication_date") or row.get("published_at"),
                "retrieved_at": _stamp(row),
                "source_as_of": _stamp(row),
                "affected_entities": row.get("symbols") or ([row.get("symbol")] if row.get("symbol") else []),
                "relevance": row.get("relevance"),
                "support_or_challenge": row.get("support_or_challenge") or row.get("stance"),
                "reason_used_or_rejected": row.get("use_reason") or row.get("rejection_reason") or row.get("reason"),
                "agent_model": row.get("model") or row.get("model_used") or row.get("provider"),
                "decision_id": row.get("decision_id") or row.get("cio_case_id"),
                "trace_id": row.get("trace_id") or row.get("run_id"),
                "evidence_class": row.get("evidence_class") or "RESEARCH_ARTIFACT",
            })
    return {
        "sources": sources,
        "artifacts": artifacts,
        "retrieved": [a for a in artifacts if a["status"] == "RETRIEVED"],
        "used_in_judgment": [a for a in artifacts if a["status"] == "USED_IN_JUDGMENT"],
        "rejected": [a for a in artifacts if a["status"] == "REJECTED"],
        "counts": {
            "retrieved": sum(a["status"] == "RETRIEVED" for a in artifacts),
            "used_in_judgment": sum(a["status"] == "USED_IN_JUDGMENT" for a in artifacts),
            "rejected": sum(a["status"] == "REJECTED" for a in artifacts),
            "unknown": sum(a["status"] == "UNKNOWN" for a in artifacts),
        },
        "source_as_of": max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None),
    }


def _cognition(root: Path) -> dict[str, Any]:
    paths = {
        "memory_retrieval": root / "aif_memory_retrievals.jsonl",
        "memory_context": root / "memory_contexts.jsonl",
        "research_lineage": root / "intelligence_lineages.jsonl",
        "operator_feedback": root / "operator_ticker_feedback.jsonl",
    }
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for kind, path in paths.items():
        rows = _rows(path)
        sources.append({"source": path.name, **_source_meta(path, rows)})
        for row in rows[-100:]:
            items.append({
                "kind": kind,
                "id": row.get("context_id") or row.get("retrieval_receipt_id") or row.get("memory_id") or row.get("feedback_id"),
                "state": "USED" if _explicit_used(row) else ("RETRIEVED" if row.get("has_context") or row.get("memory_ids") else "AVAILABLE"),
                "symbol": row.get("symbol") or ((row.get("symbols") or [None])[0] if isinstance(row.get("symbols"), list) else None),
                "summary": row.get("summary") or row.get("query") or row.get("decision") or row.get("event"),
                "contradictory": bool(row.get("contradictory") or row.get("counter")),
                "source_ref": str(path),
                "source_as_of": _stamp(row),
                "evidence_class": "INSTITUTIONAL_COGNITION",
                "influence": "PROVEN" if _explicit_used(row) else "NOT_PROVEN",
            })
    return {
        "office_truth_boundary": ["price", "holdings", "cash", "orders", "broker_state", "risk_limits"],
        "items": items,
        "sources": sources,
        "source_as_of": max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None),
        "memory_behavior_influence": 0,
        "authority": "NON_AUTHORITATIVE_CONTEXT",
    }


def _learning(root: Path) -> dict[str, Any]:
    paths = {
        "outcomes": root / "advisory_outcomes_v1.jsonl",
        "checkpoints": root / "outcome_checkpoints.jsonl",
        "lessons": root / "lesson_candidates.jsonl",
        "experiments": root / "shadow_experiments.jsonl",
        "hypotheses": root / "hypotheses.jsonl",
    }
    rows_by_kind = {kind: _rows(path) for kind, path in paths.items()}
    sources = [{"source": path.name, **_source_meta(path, rows_by_kind[kind])} for kind, path in paths.items()]
    outcomes = rows_by_kind["outcomes"]
    settled = [r for r in outcomes if str(r.get("status") or "").upper() in {"OUTCOME_EVALUATED", "SETTLED", "SETTLED_OUTCOME"}]
    pending = [r for r in outcomes if r not in settled]
    lessons = rows_by_kind["lessons"]
    return {
        "settled_outcomes": [{"outcome_id": r.get("outcome_id") or r.get("id"), "decision_id": r.get("decision_id"), "status": r.get("status"), "source_as_of": _stamp(r)} for r in settled[-100:]],
        "pending_outcomes": [{"outcome_id": r.get("outcome_id") or r.get("id"), "decision_id": r.get("decision_id"), "status": r.get("status"), "source_as_of": _stamp(r)} for r in pending[-100:]],
        "beliefs": [{"belief_id": r.get("belief_id"), "outcome_ids": r.get("outcome_ids") or [], "sample_size": r.get("sample_size"), "success_rate": r.get("success_rate"), "state": r.get("status") or "UNKNOWN"} for r in lessons[-100:] if r.get("belief_id") or r.get("outcome_ids")],
        "lessons": lessons[-100:],
        "hypotheses": rows_by_kind["hypotheses"][-100:],
        "experiments": rows_by_kind["experiments"][-100:],
        "checkpoint_count": len(rows_by_kind["checkpoints"]),
        "sample_size": len(set(str(r.get("outcome_id") or r.get("id")) for r in settled if r.get("outcome_id") or r.get("id"))),
        "review_ready": [r for r in lessons + rows_by_kind["hypotheses"] if str(r.get("promotion_stage") or r.get("status") or "").upper() == "REVIEW_READY"],
        "sources": sources,
        "source_as_of": max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None),
        "memory_behavior_influence": 0,
        "self_promotion": False,
    }


def _capability_coverage(root: Path) -> dict[str, Any]:
    """Classify capabilities from producer artifacts, not React field absence."""
    specs = [
        ("InstrumentRecord", "scripts.lib.cio_instrument_record", "data/cio/cio_instrument_records.jsonl", "persistent_wake", "PARTIAL"),
        ("persistent memory", "scripts.lib.agent_durable_memory", "data/cio/aif_memory_retrievals.jsonl", "cio/advisory/hermes", "PARTIAL"),
        ("specialist artifacts", "scripts.lib.cio_specialist_artifact", "data/cio/cio_specialist_artifacts.jsonl", "decision_lineage", "DARK"),
        ("CIO council synthesis", "scripts.lib.cio_committee", "data/cio/cio_workflow_lineage.jsonl", "cio_home", "PARTIAL"),
        ("judgment", "scripts.lib.cio_run", "data/cio/cio_workflow_lineage.jsonl", "cio_decisions", "PARTIAL"),
        ("commitment", "scripts.lib.cio_action_ledger", "data/cio/cio_action_ledger.jsonl", "operator_disposition", "PARTIAL"),
        ("outcome checkpoint", "scripts.lib.r17_checkpoint_binding", "data/cio/outcome_checkpoints.jsonl", "learning_cockpit", "PARTIAL"),
        ("outcome settlement", "scripts.lib.cio_outcome_store", "data/cio/advisory_outcomes_v1.jsonl", "learning_cockpit", "PARTIAL"),
        ("lesson", "scripts.lib.memory_consolidator", "data/cio/lesson_candidates.jsonl", "learning_cockpit", "PARTIAL"),
        ("belief writer", "scripts.lib.cio_belief_writer", "data/cio/cio_instrument_records.jsonl", "persistent_wake", "PARTIAL"),
        ("notification policy", "scripts.lib.cio_notification_signal", "data/cio/cio_notification_audit.jsonl", "notification_panel", "PARTIAL"),
        ("delivery receipt", "scripts.lib.cio_delivery_mode", "data/cio/cio_telegram_receipts.jsonl", "telegram_receipts", "PARTIAL"),
        ("Telegram lane", "scripts.lib.cio_alex_telegram", "data/cio/cio_telegram_receipts.jsonl", "telegram_receipts", "PARTIAL"),
        ("operator feedback", "scripts.lib.cio_feedback_learning_v1", "data/cio/operator_ticker_feedback.jsonl", "decisions/advisory", "PARTIAL"),
        ("external research", "scripts.lib.cio_hermes_research", "data/cio/hermes_research_results.jsonl", "research/lineage", "DARK"),
        ("graph propagation", "scripts.lib.ticker_knowledge_graph", "data/cio/ticker_research_graph.jsonl", "research", "PARTIAL"),
    ]
    rows: list[dict[str, Any]] = []
    for capability, producer, rel, consumer, dark_state in specs:
        path = root / Path(rel).relative_to("data/cio")
        records = _rows(path)
        module_path = Path(__file__).resolve().parents[2] / (producer.replace(".", "/") + ".py")
        if records:
            state = "LIVE" if consumer else "PARTIAL"
            reason = "durable producer and consumer evidence observed"
        elif path.is_file():
            state = "PARTIAL"
            reason = "canonical artifact exists but no readable runtime rows"
        elif module_path.is_file():
            state = dark_state if dark_state in {"DARK", "PARTIAL"} else "UNWIRED"
            reason = "producer exists; no durable runtime artifact observed"
        else:
            state = "UNKNOWN"
            reason = "producer and artifact could not be verified"
        rows.append({
            "capability": capability,
            "contract": producer,
            "producer": producer,
            "consumer": consumer,
            "last_producer_event": _latest_stamp(records),
            "last_consumer_event": None,
            "durable_artifact": str(path),
            "artifact_age": None,
            "current_status": state,
            "reason": reason,
            "source_sha": _source_sha(path),
            "evidence_class": "RUNTIME_ARTIFACT_CENSUS",
        })
    counts = {state: sum(row["current_status"] == state for row in rows) for state in ("LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN")}
    return {"rows": rows, "counts": counts, "source_as_of": max((r["last_producer_event"] for r in rows if r["last_producer_event"]), default=None)}


def build_operator_evidence(*, now: str | None = None) -> dict[str, Any]:
    root = _root()
    composed = now or _now()
    research = _research_provenance(root)
    cognition = _cognition(root)
    learning = _learning(root)
    coverage = _capability_coverage(root)
    blocks = {"research": research, "institutional_cognition": cognition, "learning": learning, "capability_coverage": coverage}
    for block in blocks.values():
        block["composition_as_of"] = composed
        block["producer"] = "scripts.lib.cio_operator_evidence"
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
