"""Durable, read-only CIO workflow lineage.

The lineage stream is an audit projection of existing Hermes/CIO identifiers.  It
never creates investment decisions and is safe to call repeatedly: the semantic
key is persisted and duplicate nodes/edges are ignored.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "cio" / "cio_workflow_lineage.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOWorkflowLineage@v1"
ENVELOPE_SCHEMA = "CIOWorkflowEnvelope@v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()[:20]


def workflow_id(*, plan_id: str = "", research_id: str = "", decision_id: str = "", generation_id: str = "") -> str:
    """Return a stable workflow identity from the strongest available IDs."""
    parts = [str(x).strip() for x in (plan_id, research_id, decision_id, generation_id) if str(x).strip()]
    return "wf_" + _digest(parts) if parts else "wf_" + _digest("unresolved")


class LineageStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH

    def _existing_keys(self) -> set[str]:
        keys: set[str] = set()
        try:
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                        if row.get("semantic_key"):
                            keys.add(str(row["semantic_key"]))
                    except (ValueError, TypeError):
                        continue
        except FileNotFoundError:
            pass
        return keys

    def append(self, record: dict[str, Any]) -> bool:
        row = {"schema": SCHEMA, "recorded_at": _now(), "authority": AUTHORITY, **record}
        row.setdefault("semantic_key", _digest({k: row.get(k) for k in ("record_type", "workflow_id", "node_id", "from", "to", "relationship")}))
        keys = self._existing_keys()
        if row["semantic_key"] in keys:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # O_APPEND keeps concurrent workers from overwriting records.  A process
        # level duplicate check is intentionally best-effort; readers still
        # dedupe by semantic_key.
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True

    def node(self, *, workflow: str, node_type: str, node_id: str, status: str = "AVAILABLE", summary: str = "", source_ref: str | None = None, entity_refs: Iterable[str] = (), evidence_class: str = "OPERATOR_REQUESTED_LIVE", source_sha: str | None = None, as_of: str | None = None, data_quality: str = "AVAILABLE") -> bool:
        if not node_id:
            return False
        return self.append({
            "record_type": "node", "workflow_id": workflow, "node_type": node_type,
            "node_id": str(node_id), "status": status, "summary": summary[:500],
            "source_ref": source_ref, "entity_refs": list(entity_refs),
            "evidence_class": evidence_class, "source_sha": source_sha,
            "as_of": as_of or _now(), "data_quality": data_quality,
        })

    def edge(self, *, workflow: str, from_id: str, to_id: str, relationship: str, evidence: str | None = None, status: str = "RESOLVED") -> bool:
        if not from_id or not to_id:
            return False
        return self.append({"record_type": "edge", "workflow_id": workflow, "from": str(from_id), "to": str(to_id), "relationship": relationship, "evidence": evidence, "status": status})

    def envelope(self, envelope: Mapping[str, Any]) -> bool:
        """Persist one canonical workflow envelope as an idempotent node.

        The envelope is an audit projection only.  IDs are copied from producers;
        this helper never invents external identity or financial values.
        """
        workflow = str(envelope.get("workflow_id") or "").strip()
        if not workflow:
            return False
        required = {
            "workflow_id": workflow,
            "event_id": envelope.get("event_id"),
            "canonical_entity_id": envelope.get("canonical_entity_id"),
            "security_id": envelope.get("security_id"),
            "symbol": envelope.get("symbol"),
            "research_job_ids": list(envelope.get("research_job_ids") or []),
            "specialist_artifact_ids": list(envelope.get("specialist_artifact_ids") or []),
            "notification_ids": list(envelope.get("notification_ids") or []),
            "checkpoint_ids": list(envelope.get("checkpoint_ids") or []),
            "outcome_ids": list(envelope.get("outcome_ids") or []),
            "evidence_class": envelope.get("evidence_class") or "OPERATOR_REQUESTED_LIVE",
            "authority_classification": envelope.get("authority_classification") or AUTHORITY,
            "source_sha": envelope.get("source_sha"),
            "data_quality": envelope.get("data_quality") or "AVAILABLE",
            "record_type": "envelope",
            "schema": ENVELOPE_SCHEMA,
        }
        return self.append(required)

    def records_for_workflow(self, workflow: str) -> list[dict[str, Any]]:
        """Reload a bounded workflow projection from disk (never process memory)."""
        rows: list[dict[str, Any]] = []
        try:
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if row.get("workflow_id") == workflow:
                        rows.append(row)
        except FileNotFoundError:
            return []
        return rows

    def checkpoint(self, *, workflow: str, checkpoint_id: str, plan_id: str = "", research_id: str = "", decision_id: str = "", generation_id: str = "", entity_id: str = "", security_id: str = "", subject: str = "", due_at: str | None = None, observation_class: str = "", evidence_class: str = "OPERATOR_REQUESTED_LIVE") -> str:
        cid = checkpoint_id or "cp_" + _digest([workflow, plan_id, research_id, decision_id])
        self.append({
            "record_type": "checkpoint",
            "schema": "OutcomeCheckpoint@v1",
            "workflow_id": workflow,
            "node_id": cid,
            "checkpoint_id": cid,
            "entity_id": entity_id or None,
            "security_id": security_id or None,
            "subject": subject or None,
            "plan_id": plan_id or None,
            "research_id": research_id or None,
            "decision_id": decision_id or None,
            "generation_id": generation_id or None,
            "created_at": _now(),
            "due_at": due_at,
            "observation_class": observation_class or "THESIS_OUTCOME",
            "evidence_class": evidence_class,
            "authority": AUTHORITY,
            "data_quality": "AVAILABLE",
        })
        for src, rel in ((plan_id, "CHECKPOINTED_BY"), (research_id, "CHECKPOINTED_BY"), (decision_id, "CHECKPOINTED_BY")):
            if src:
                self.edge(workflow=workflow, from_id=src, to_id=cid, relationship=rel, evidence="canonical_id")
        return cid


def record_hermes_request(request: dict[str, Any], *, path: Path | str | None = None) -> str:
    plan_id = str(request.get("plan_id") or "")
    rid = str(request.get("research_id") or "")
    wf = workflow_id(plan_id=plan_id, research_id=rid)
    store = LineageStore(path)
    symbol = str(request.get("symbol") or "")
    store.node(workflow=wf, node_type="RESEARCH", node_id=rid, status="QUEUED", summary=str(request.get("reason") or "Hermes research queued"), source_ref="hermes_research_requests", entity_refs=[symbol] if symbol else (), evidence_class="OPERATOR_REQUESTED_LIVE")
    if plan_id:
        store.node(workflow=wf, node_type="CIO_PRODUCT", node_id=plan_id, status="AVAILABLE", summary="CIO plan requesting research", source_ref="cio_plans", entity_refs=[symbol] if symbol else ())
        store.edge(workflow=wf, from_id=plan_id, to_id=rid, relationship="TRIGGERED", evidence="plan_id")
    store.envelope({
        "workflow_id": wf, "event_id": request.get("event_id"),
        "canonical_entity_id": request.get("entity_id") or request.get("issuer_guid"),
        "security_id": request.get("security_id"), "symbol": symbol,
        "research_job_ids": [rid] if rid else [], "evidence_class": "OPERATOR_REQUESTED_LIVE",
    })
    return wf


def record_hermes_completion(request: dict[str, Any], result: dict[str, Any], *, path: Path | str | None = None) -> dict[str, str]:
    plan_id = str(request.get("plan_id") or result.get("plan_id") or "")
    rid = str(result.get("research_id") or request.get("research_id") or "")
    result_id = str(result.get("result_id") or "")
    wf = workflow_id(plan_id=plan_id, research_id=rid)
    store = LineageStore(path)
    symbol = str(request.get("symbol") or result.get("symbol") or "")
    store.node(workflow=wf, node_type="RESEARCH", node_id=rid, status="COMPLETED", summary=str(result.get("summary") or "Hermes research completed"), source_ref="hermes_research_results", entity_refs=[symbol] if symbol else (), evidence_class="OPERATOR_REQUESTED_LIVE")
    if result_id:
        store.node(workflow=wf, node_type="SPECIALIST_ARTIFACT", node_id=result_id, status="AVAILABLE", summary="Hermes result artifact", source_ref="hermes_research_results", entity_refs=[symbol] if symbol else ())
        store.edge(workflow=wf, from_id=rid, to_id=result_id, relationship="PRODUCED", evidence="research_id")
    generation_id = str(result.get("generation_id") or request.get("generation_id") or "")
    notification_id = str(result.get("notification_id") or request.get("notification_id") or "")
    specialist_id = str(result.get("specialist_dispatch_id") or request.get("specialist_dispatch_id") or "")
    for node_type, node_id, summary in (
        ("SPECIALIST_DISPATCH", specialist_id, "Specialist dispatch"),
        ("CIO_GENERATION", generation_id, "CIO synthesis generation"),
        ("NOTIFICATION", notification_id, "Notification or suppression"),
    ):
        if node_id:
            store.node(workflow=wf, node_type=node_type, node_id=node_id, summary=summary, source_ref="canonical_cio_lineage", entity_refs=[symbol] if symbol else ())
    if specialist_id and result_id:
        store.edge(workflow=wf, from_id=specialist_id, to_id=result_id, relationship="DISPATCHED_TO", evidence="specialist_dispatch_id")
    if result_id and generation_id:
        store.edge(workflow=wf, from_id=result_id, to_id=generation_id, relationship="SYNTHESIZED_INTO", evidence="result_id")
    if generation_id and notification_id:
        store.edge(workflow=wf, from_id=generation_id, to_id=notification_id, relationship="NOTIFIED_AS", evidence="generation_id")
    cp = "cp_" + _digest([wf, rid, result_id, plan_id])
    store.checkpoint(workflow=wf, checkpoint_id=cp, plan_id=plan_id, research_id=rid, decision_id=str(result.get("decision_id") or ""), generation_id=generation_id, entity_id=str(request.get("entity_id") or request.get("issuer_guid") or ""), security_id=str(request.get("security_id") or ""), subject=symbol, due_at=result.get("due_at"), observation_class=str(result.get("observation_class") or "THESIS_OUTCOME"))
    store.envelope({
        "workflow_id": wf, "event_id": request.get("event_id"),
        "canonical_entity_id": request.get("entity_id") or request.get("issuer_guid"),
        "security_id": request.get("security_id"), "symbol": symbol,
        "research_job_ids": [rid] if rid else [],
        "specialist_dispatch_id": specialist_id,
        "specialist_artifact_ids": [result_id] if result_id else [],
        "cio_synthesis_id": generation_id, "generation_id": generation_id,
        "notification_ids": [notification_id] if notification_id else [],
        "checkpoint_ids": [cp], "evidence_class": "OPERATOR_REQUESTED_LIVE",
    })
    return {"workflow_id": wf, "checkpoint_id": cp, "research_id": rid, "result_id": result_id}
