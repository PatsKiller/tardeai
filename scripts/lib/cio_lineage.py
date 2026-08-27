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
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "cio" / "cio_workflow_lineage.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOWorkflowLineage@v1"


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

    def checkpoint(self, *, workflow: str, checkpoint_id: str, plan_id: str = "", research_id: str = "", decision_id: str = "", subject: str = "", due_at: str | None = None, evidence_class: str = "OPERATOR_REQUESTED_LIVE") -> str:
        cid = checkpoint_id or "cp_" + _digest([workflow, plan_id, research_id, decision_id])
        self.node(workflow=workflow, node_type="CHECKPOINT", node_id=cid, summary=f"Checkpoint for {subject or plan_id or research_id}", source_ref="cio_workflow_lineage", evidence_class=evidence_class)
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
    cp = "cp_" + _digest([wf, rid, result_id, plan_id])
    store.checkpoint(workflow=wf, checkpoint_id=cp, plan_id=plan_id, research_id=rid, subject=symbol)
    return {"workflow_id": wf, "checkpoint_id": cp, "research_id": rid, "result_id": result_id}
