"""Durable, read-only CIO workflow lineage.

The lineage stream is an audit projection of existing Hermes/CIO identifiers.
It never creates investment decisions. Duplicate nodes/edges/envelopes are
ignored via semantic_key. Canonical checkpoints are OutcomeCheckpoint@v1.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.lib.canonical_store_registry import production_state_root
from scripts.lib.cio_institutional_learning import CHECKPOINT_PATH, HORIZONS, persist_checkpoint, _jsonl as _checkpoint_jsonl
from scripts.lib.cio_workflow_envelope import (
    AUTHORITY,
    MBI,
    SCHEMA as ENVELOPE_SCHEMA,
    STAGE_COMPLETED,
    STAGE_NOT_YET_CREATED,
    cio_stage_for_skip,
    coerce_notification_classification,
    coerce_skip_reason,
    freeze_governance,
    hermes_completion_fields,
    hermes_request_fields,
    identity_from_payload,
    is_complete_to_checkpoint,
    merge_envelope,
    notification_is_ambiguous,
    notification_stage_for,
    semantic_payload,
)
from scripts.lib.r17_checkpoint_binding import enrich_checkpoint

SCHEMA = "CIOWorkflowLineage@v1"
ENVELOPE_RECORD = "envelope"
CHECKPOINT_SCHEMA = "OutcomeCheckpoint@v1"
REQUIRED_CHECKPOINT_FIELDS = (
    "schema",
    "checkpoint_id",
    "workflow_id",
    "subject_id",
    "entity_type",
    "subject_guid",
    "decision_id",
    "decision_generation",
    "created_at",
    "due_at",
    "status",
    "observational_only",
    "authority",
    "runtime_source_sha",
    "semantic_key",
    "horizon",
    "lineage_id",
    "context_receipt",
    "original_decision_state",
    "memory_behavior_influence",
    "trading",
)
LINEAGE_RELATIVE = Path("data") / "cio" / "cio_workflow_lineage.jsonl"


def default_lineage_path() -> Path:
    """Lineage JSONL under production_state_root (persistent overlay when deployed)."""
    return production_state_root() / LINEAGE_RELATIVE


def __getattr__(name: str) -> Any:
    if name == "DEFAULT_PATH":
        return default_lineage_path()
    if name == "ROOT":
        return production_state_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()[:20]


def _lineage_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    return default_lineage_path()


def _infer_root(path: Path) -> Path:
    p = Path(path)
    if p.parent.name == "cio" and p.parent.parent.name == "data":
        return p.parent.parent.parent
    return p.parent


def _optional_str(value: Any) -> str:
    return str(value).strip() if value is not None and str(value).strip() else ""


def workflow_id(
    *,
    plan_id: str = "",
    research_id: str = "",
    decision_id: str = "",
    generation_id: str = "",
) -> str:
    """Return a stable workflow identity from the strongest available IDs."""
    parts = [
        str(x).strip()
        for x in (plan_id, research_id, decision_id, generation_id)
        if str(x).strip()
    ]
    return "wf_" + _digest(parts) if parts else "wf_" + _digest("unresolved")


def iter_lineage_records(path: Path | str | None = None) -> list[dict[str, Any]]:
    target = _lineage_path(path)
    rows: list[dict[str, Any]] = []
    try:
        with target.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        return []
    return rows


class LineageStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = _lineage_path(path)

    def _existing_keys(self) -> set[str]:
        keys: set[str] = set()
        for row in iter_lineage_records(self.path):
            if row.get("semantic_key"):
                keys.add(str(row["semantic_key"]))
        return keys

    def _rows(self) -> list[dict[str, Any]]:
        return iter_lineage_records(self.path)

    def append(self, record: dict[str, Any]) -> bool:
        row = {
            "schema": SCHEMA,
            "recorded_at": _now(),
            "memory_behavior_influence": MBI,
            **record,
        }
        row["authority"] = AUTHORITY
        row.setdefault(
            "semantic_key",
            _digest(
                {
                    k: row.get(k)
                    for k in ("record_type", "workflow_id", "node_id", "from", "to", "relationship")
                }
            ),
        )
        if row["semantic_key"] in self._existing_keys():
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True

    def node(
        self,
        *,
        workflow: str,
        node_type: str,
        node_id: str,
        status: str = "AVAILABLE",
        summary: str = "",
        source_ref: str | None = None,
        entity_refs: Iterable[str] = (),
        evidence_class: str = "OPERATOR_REQUESTED_LIVE",
        source_sha: str | None = None,
        as_of: str | None = None,
        data_quality: str = "AVAILABLE",
    ) -> bool:
        if not node_id:
            return False
        return self.append(
            {
                "record_type": "node",
                "workflow_id": workflow,
                "node_type": node_type,
                "node_id": str(node_id),
                "status": status,
                "summary": summary[:500],
                "source_ref": source_ref,
                "entity_refs": list(entity_refs),
                "evidence_class": evidence_class,
                "source_sha": source_sha,
                "as_of": as_of or _now(),
                "data_quality": data_quality,
            }
        )

    def edge(
        self,
        *,
        workflow: str,
        from_id: str,
        to_id: str,
        relationship: str,
        evidence: str | None = None,
        status: str = "RESOLVED",
    ) -> bool:
        if not from_id or not to_id:
            return False
        return self.append(
            {
                "record_type": "edge",
                "workflow_id": workflow,
                "from": str(from_id),
                "to": str(to_id),
                "relationship": relationship,
                "evidence": evidence,
                "status": status,
            }
        )

    def checkpoint(
        self,
        *,
        workflow: str,
        checkpoint_id: str,
        plan_id: str = "",
        research_id: str = "",
        decision_id: str = "",
        subject: str = "",
        due_at: str | None = None,
        evidence_class: str = "OPERATOR_REQUESTED_LIVE",
    ) -> str:
        """Graph NODE pointing at checkpoint_id. Does not mint cp_* when an id is provided."""
        cid = str(checkpoint_id or "")
        if not cid:
            return ""
        self.node(
            workflow=workflow,
            node_type="CHECKPOINT",
            node_id=cid,
            summary=f"Checkpoint for {subject or plan_id or research_id}",
            source_ref="outcome_checkpoints",
            evidence_class=evidence_class,
        )
        for src, rel in (
            (plan_id, "CHECKPOINTED_BY"),
            (research_id, "CHECKPOINTED_BY"),
            (decision_id, "CHECKPOINTED_BY"),
        ):
            if src:
                self.edge(
                    workflow=workflow,
                    from_id=src,
                    to_id=cid,
                    relationship=rel,
                    evidence="canonical_id",
                )
        return cid

    def latest_envelope(self, workflow: str) -> dict[str, Any] | None:
        found = None
        for row in self._rows():
            if row.get("record_type") == ENVELOPE_RECORD and str(row.get("workflow_id")) == str(workflow):
                found = row
        return found

    def upsert_envelope(
        self,
        workflow: str,
        updates: dict[str, Any] | None = None,
        *,
        unset: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        existing = self.latest_envelope(workflow)
        created = (existing or {}).get("created_at") or now
        merged = merge_envelope(
            existing,
            {"workflow_id": workflow, **(updates or {})},
            updated_at=now,
            created_at=created,
            unset=unset,
        )
        freeze_governance(merged)
        key = "env_" + _digest(semantic_payload(merged))
        merged["semantic_key"] = key
        merged["record_type"] = ENVELOPE_RECORD
        if existing and existing.get("semantic_key") == key:
            return merge_envelope(existing, None)
        self.append(
            {
                **merged,
                "record_type": ENVELOPE_RECORD,
                "schema": ENVELOPE_SCHEMA,
                "semantic_key": key,
            }
        )
        return merged


def load_envelope(workflow_id: str, path: Path | str | None = None) -> dict[str, Any] | None:
    env = LineageStore(path).latest_envelope(workflow_id)
    if env is None:
        return None
    return merge_envelope(env, None)


def upsert_envelope(
    workflow_id: str,
    updates: dict[str, Any] | None = None,
    *,
    path: Path | str | None = None,
    unset: Iterable[str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    payload = {**(updates or {}), **fields}
    return LineageStore(path).upsert_envelope(workflow_id, payload, unset=unset)


def record_cio_generation(
    workflow_id: str,
    generation_id: str | None = None,
    skip_reason: str | None = None,
    *,
    path: Path | str | None = None,
    source_sha: str | None = None,
    identity: Any = None,
) -> dict[str, Any]:
    """Persist a real CIO generation id, or a typed skip. Never mint a fake id.

    `identity` is an optional payload describing what the run is *about*, used to
    stamp a canonical `event_id`. Without it a CIO envelope carries no entity at
    all -- which is why every production envelope read `entity_type: UNRESOLVED`
    and why the CIO arc had nothing to join to the research arc on.
    """
    store = LineageStore(path)
    gid = _optional_str(generation_id)
    reason = coerce_skip_reason(skip_reason)
    updates: dict[str, Any] = {}
    if source_sha:
        updates["source_sha"] = source_sha
    if identity:
        try:
            from scripts.lib.cio_canonical_identity import identity_fields
            updates.update(identity_fields(identity, event_kind="CIO_RUN"))
        except Exception:
            pass  # lineage is an audit projection; identity is best-effort
    if reason:
        updates["cio_skip_reason"] = reason
        updates["stage_status"] = {"cio": cio_stage_for_skip(reason)}
        return store.upsert_envelope(workflow_id, updates, unset=("cio_generation_id",))
    if gid:
        store.node(
            workflow=workflow_id,
            node_type="CIO_GENERATION",
            node_id=gid,
            status="AVAILABLE",
            summary="CIO generation",
            source_ref="cio_generation",
            source_sha=source_sha,
        )
        env = store.latest_envelope(workflow_id) or {}
        artifact = env.get("specialist_artifact_id") or env.get("research_artifact_id") or env.get("research_request_id")
        if artifact:
            store.edge(
                workflow=workflow_id,
                from_id=str(artifact),
                to_id=gid,
                relationship="TRIGGERED",
                evidence="cio_generation",
            )
        updates["cio_generation_id"] = gid
        updates["stage_status"] = {"cio": STAGE_COMPLETED}
        return store.upsert_envelope(workflow_id, updates, unset=("cio_skip_reason",))
    updates["stage_status"] = {"cio": STAGE_NOT_YET_CREATED}
    return store.upsert_envelope(workflow_id, updates)


def record_specialist_dispatch(
    workflow_id: str,
    dispatch_id: str | None,
    *,
    agent_id: str | None = None,
    artifact_id: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Persist the specialist hand-off in the same workflow envelope.

    Dispatch is an explicit stage: callers must provide the producer's ID; this
    helper never fabricates an agent or artifact identity.
    """
    store = LineageStore(path)
    did = _optional_str(dispatch_id)
    aid = _optional_str(artifact_id)
    if did:
        store.node(workflow=workflow_id, node_type="SPECIALIST_DISPATCH", node_id=did,
                   summary=f"Specialist dispatch {agent_id or ''}".strip(),
                   source_ref="specialist_dispatch", entity_refs=())
    if did and aid:
        store.edge(workflow=workflow_id, from_id=did, to_id=aid,
                   relationship="DISPATCHED_TO", evidence="specialist_dispatch_id")
    updates: dict[str, Any] = {"stage_status": {"specialist": STAGE_COMPLETED if aid else STAGE_NOT_YET_CREATED}}
    if did:
        updates["specialist_dispatch_id"] = did
    if aid:
        updates["specialist_artifact_id"] = aid
    return store.upsert_envelope(workflow_id, updates)


def record_notification(
    workflow_id: str,
    notification_id: str | None = None,
    classification: str | None = None,
    suppression_reason: str | None = None,
    *,
    path: Path | str | None = None,
) -> dict[str, Any]:
    store = LineageStore(path)
    klass = coerce_notification_classification(classification)
    nid = _optional_str(notification_id)
    stage = notification_stage_for(klass)
    updates: dict[str, Any] = {
        "notification_classification": klass,
        "suppression_reason": _optional_str(suppression_reason) or None,
        "stage_status": {"notification": stage},
    }
    if nid:
        updates["notification_id"] = nid
        store.node(
            workflow=workflow_id,
            node_type="NOTIFICATION",
            node_id=nid,
            status=klass or stage,
            summary=str(klass or stage),
            source_ref="cio_notification_audit",
        )
        env = store.latest_envelope(workflow_id) or {}
        src = env.get("cio_generation_id") or env.get("specialist_artifact_id") or env.get("research_request_id")
        if src:
            store.edge(
                workflow=workflow_id,
                from_id=str(src),
                to_id=nid,
                relationship="NOTIFIED",
                evidence="notification_id",
            )
    return store.upsert_envelope(workflow_id, updates)


def finalize_notification_required(
    workflow_id: str,
    *,
    path: Path | str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Mark notification NOT_REQUIRED so the workflow does not end ambiguous."""
    return record_notification(
        workflow_id,
        notification_id=None,
        classification="NOT_REQUIRED",
        suppression_reason=reason or "NOT_REQUIRED",
        path=path,
    )


def persist_canonical_checkpoint(
    root: Path | str,
    workflow_id: str,
    decision: dict[str, Any],
    source_sha: str,
    *,
    path: Path | str | None = None,
    horizon: str | None = None,
) -> dict[str, Any]:
    """Write OutcomeCheckpoint@v1 and point the envelope/graph at the same id.

    Returns the existing checkpoint_id on semantic duplicate. Never mints a
    competing cp_* identity when an OutcomeCheckpoint id exists.
    """
    root_p = Path(root)
    store = LineageStore(path)
    d = dict(decision or {})
    if not _optional_str(d.get("decision_id")):
        d["decision_id"] = str(workflow_id)
    d.setdefault("observational_only", True)
    hz = _optional_str(horizon or d.get("horizon")) or "event-relative"
    if hz not in HORIZONS:
        hz = "event-relative"

    existing_rows = _checkpoint_jsonl(root_p / CHECKPOINT_PATH)
    by_semantic = {str(r.get("semantic_key")): r for r in existing_rows if r.get("semantic_key")}
    existing_ids = [str(r.get("checkpoint_id")) for r in existing_rows if r.get("checkpoint_id")]
    ck = enrich_checkpoint(d, hz, source_sha=str(source_sha), existing_ids=existing_ids)
    env = store.latest_envelope(workflow_id) or {}
    ntf_id = d.get("notification_id") if d.get("notification_id") is not None else env.get("notification_id")
    ident = identity_from_payload(d)
    ck["workflow_id"] = str(workflow_id)
    ck["notification_id"] = ntf_id
    ck["schema"] = CHECKPOINT_SCHEMA
    ck["observational_only"] = True
    ck["trading"] = False
    ck["authority"] = AUTHORITY
    ck["memory_behavior_influence"] = MBI
    ck["duplicate"] = False
    if not d.get("subject_guid") and not d.get("security_guid"):
        ck["subject_guid"] = None
    ck.setdefault("entity_type", ident.get("entity_type"))
    ck.setdefault("subject_id", ident.get("subject_id"))

    def _attach(cid: str, wrote: bool, duplicate: bool, stored: dict[str, Any]) -> dict[str, Any]:
        envelope = store.upsert_envelope(
            workflow_id,
            {
                "checkpoint_id": cid,
                "stage_status": {"checkpoint": STAGE_COMPLETED},
                "subject_id": ident.get("subject_id"),
                "entity_type": ident.get("entity_type"),
                "subject_guid": ident.get("subject_guid"),
                "source_sha": source_sha,
            },
        )
        return {
            "wrote": wrote,
            "duplicate": duplicate,
            "checkpoint": stored,
            "checkpoint_id": cid,
            "envelope": envelope,
            "authority": AUTHORITY,
        }

    prior = by_semantic.get(str(ck.get("semantic_key")))
    if prior:
        cid = str(prior.get("checkpoint_id") or ck.get("checkpoint_id") or "")
        return _attach(cid, False, True, prior)

    result = persist_checkpoint(root_p, ck)
    stored = result.get("checkpoint") or ck
    cid = str(stored.get("checkpoint_id") or ck.get("checkpoint_id") or "")
    if result.get("duplicate"):
        return _attach(cid, False, True, stored)
    store.checkpoint(
        workflow=str(workflow_id),
        checkpoint_id=cid,
        plan_id=_optional_str(d.get("plan_id")),
        research_id=_optional_str(d.get("research_id") or env.get("research_request_id")),
        decision_id=_optional_str(d.get("decision_id")),
        subject=_optional_str(d.get("symbol") or ident.get("subject_id")),
    )
    if ntf_id:
        store.edge(
            workflow=str(workflow_id),
            from_id=str(ntf_id),
            to_id=cid,
            relationship="CHECKPOINTED_BY",
            evidence="notification_id",
        )
    return _attach(cid, True, False, stored)


def record_hermes_request(request: dict[str, Any], *, path: Path | str | None = None) -> str:
    plan_id = str(request.get("plan_id") or "")
    rid = str(request.get("research_id") or "")
    wf = workflow_id(plan_id=plan_id, research_id=rid)
    store = LineageStore(path)
    symbol = str(request.get("symbol") or "")
    ident = identity_from_payload(request)
    store.node(
        workflow=wf,
        node_type="RESEARCH",
        node_id=rid,
        status="QUEUED",
        summary=str(request.get("reason") or "Hermes research queued"),
        source_ref="hermes_research_requests",
        entity_refs=[symbol] if symbol else (),
        evidence_class="OPERATOR_REQUESTED_LIVE",
        source_sha=request.get("source_sha"),
    )
    entity_id = ident.get("subject_guid") or ident.get("subject_id")
    if entity_id:
        store.node(
            workflow=wf,
            node_type="ENTITY",
            node_id=str(entity_id),
            status="AVAILABLE",
            summary=str(ident.get("entity_type") or "UNRESOLVED"),
            source_ref="cio_workflow_envelope",
            entity_refs=[symbol] if symbol else (),
            source_sha=request.get("source_sha"),
        )
        store.node(
            workflow=wf,
            node_type="WORKFLOW",
            node_id=wf,
            status="AVAILABLE",
            summary="CIO workflow",
            source_ref="cio_workflow_lineage",
            entity_refs=[symbol] if symbol else (),
            source_sha=request.get("source_sha"),
        )
        store.edge(workflow=wf, from_id=str(entity_id), to_id=wf, relationship="SUBJECT_OF", evidence="subject_id")
        if rid:
            store.edge(workflow=wf, from_id=wf, to_id=rid, relationship="TRIGGERED", evidence="workflow_id")
    if plan_id:
        store.node(
            workflow=wf,
            node_type="CIO_PRODUCT",
            node_id=plan_id,
            status="AVAILABLE",
            summary="CIO plan requesting research",
            source_ref="cio_plans",
            entity_refs=[symbol] if symbol else (),
        )
        store.edge(workflow=wf, from_id=plan_id, to_id=rid, relationship="TRIGGERED", evidence="plan_id")
    store.upsert_envelope(wf, hermes_request_fields(request))
    return wf


def record_hermes_completion(
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    path: Path | str | None = None,
    root: Path | str | None = None,
    source_sha: str | None = None,
) -> dict[str, str]:
    plan_id = str(request.get("plan_id") or result.get("plan_id") or "")
    rid = str(result.get("research_id") or request.get("research_id") or "")
    result_id = str(result.get("result_id") or "")
    wf = workflow_id(plan_id=plan_id, research_id=rid)
    store = LineageStore(path)
    symbol = str(request.get("symbol") or result.get("symbol") or "")
    store.node(
        workflow=wf,
        node_type="RESEARCH",
        node_id=rid,
        status="COMPLETED",
        summary=str(result.get("summary") or "Hermes research completed"),
        source_ref="hermes_research_results",
        entity_refs=[symbol] if symbol else (),
        evidence_class="OPERATOR_REQUESTED_LIVE",
    )
    if result_id:
        store.node(
            workflow=wf,
            node_type="SPECIALIST_ARTIFACT",
            node_id=result_id,
            status="AVAILABLE",
            summary="Hermes result artifact",
            source_ref="hermes_research_results",
            entity_refs=[symbol] if symbol else (),
        )
        store.edge(workflow=wf, from_id=rid, to_id=result_id, relationship="PRODUCED", evidence="research_id")
    store.upsert_envelope(wf, hermes_completion_fields(request, result))
    sha = str(source_sha or result.get("source_sha") or request.get("source_sha") or "")
    ck_root = Path(root) if root is not None else _infer_root(store.path)
    decision = {
        "decision_id": str(request.get("decision_id") or plan_id or rid or wf),
        "symbol": symbol,
        "recommendation": request.get("recommendation") or result.get("recommendation") or "OBSERVE",
        "producer_id": "hermes_research",
        "material_generation": result_id or rid,
        "plan_id": plan_id,
        "research_id": rid,
        "subject_guid": request.get("subject_guid") or result.get("subject_guid"),
        "entity_type": request.get("entity_type") or result.get("entity_type"),
        "subject_id": request.get("subject_id") or result.get("subject_id"),
        "observational_only": True,
    }
    persisted = persist_canonical_checkpoint(
        ck_root,
        wf,
        decision,
        sha or "lineage",
        path=store.path,
    )
    cid = str(persisted.get("checkpoint_id") or "")
    return {
        "workflow_id": wf,
        "checkpoint_id": cid,
        "research_id": rid,
        "result_id": result_id,
    }


def complete_to_checkpoint(workflow_id: str, path: Path | str | None = None) -> bool:
    env = load_envelope(workflow_id, path)
    return is_complete_to_checkpoint(env)
