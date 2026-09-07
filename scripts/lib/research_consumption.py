"""Research → persistent-agent consumption contract (Lane C).

Emits AgentConsumptionReceipt@v2 with source_kind='research_object'.
Proves isolated effect: relevant research can change question/priority/view;
irrelevant research does not. Does not claim organic maturity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from scripts.lib.campaign_interfaces_c import (
    INTERFACE_VERSION,
    mint_consumption_receipt_id,
)
from scripts.lib.research_dossier import DossierRecord, build_dossier
from scripts.lib.research_object import ResearchObject

SCHEMA = "AgentConsumptionReceipt@v2"
CONSUME_SCHEMA = "ResearchConsumptionContract@v1"
Clock = Callable[[], datetime]

EFFECT_KINDS = frozenset({
    "none", "changed_question", "changed_priority", "changed_view", "changed_commitment",
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentViewState:
    """Minimal agent view surface for isolated proofs (not Lane A wake tables)."""

    agent_id: str
    subject_guid: str
    next_research_question: str = ""
    notify_priority: str = "NORMAL"
    view_summary: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConsumptionReceipt:
    receipt_id: str
    agent_id: str
    agent_version: str
    source_kind: str
    source_id: str
    purpose: str
    effect_kind: str
    effect_ref: Optional[str]
    subject_guid: str
    wake_id: Optional[str]
    thread_id: Optional[str]
    policy_decision: str
    retrieved_at: str
    acknowledged_at: Optional[str]
    derived_artifact_ids: list[str]
    influence_declaration: str
    influence_source_ids: list[str]
    evidence_used: list[dict[str, Any]]
    selection_reasons: list[str]
    schema_version: str = SCHEMA
    interface_version: str = INTERFACE_VERSION
    source_sha: str = "fixture"
    produced_at: str = ""
    correlation_id: str = ""
    idempotency_key: str = ""
    parent_id: Optional[str] = None
    parent_kind: Optional[str] = "research_object"
    retention_class: str = "evidence_2y"
    lifecycle_state: str = "ACKNOWLEDGED"
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MissingConsumptionReceipt(RuntimeError):
    pass


class ReferentialIntegrityError(RuntimeError):
    pass


def select_evidence(
    dossier: DossierRecord,
    *,
    purpose: str,
    max_items: int = 5,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pick evidence from dossier for agent consumption; record why."""
    selected: list[dict[str, Any]] = []
    reasons: list[str] = []
    # Prefer primary evidence by authoritative rank.
    for row in dossier.primary_evidence:
        if len(selected) >= max_items:
            break
        selected.append(row)
        reasons.append(
            f"primary_subject rank={row.get('authoritative_source_rank')} "
            f"purpose={purpose} research_id={row.get('research_id')}"
        )
    # Mentioned evidence fills remaining slots without conflating into primary.
    for row in dossier.mentioned_evidence:
        if len(selected) >= max_items:
            break
        if row.get("research_id") in {s.get("research_id") for s in selected}:
            continue
        selected.append(row)
        reasons.append(
            f"mentioned_security symbol={row.get('mentioned_symbol')} "
            f"research_id={row.get('research_id')}"
        )
    return selected, reasons


def _apply_relevant_effect(
    view: AgentViewState,
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[AgentViewState, str, Optional[str]]:
    """Deterministic effect when evidence is relevant to the subject."""
    if not evidence:
        return view, "none", None
    titles = [str(e.get("title") or "") for e in evidence]
    bodies = []
    for e in evidence:
        # body may live on provenance inputs
        bodies.append(json.dumps(e.get("provenance") or {}, sort_keys=True))
    blob = " ".join(titles + bodies).upper()
    sym = view.subject_guid  # may be guid; also check titles for material tokens
    material = any(
        tok in blob
        for tok in ("EARNINGS", "GUIDANCE", "DOWNGRADE", "UPGRADE", "FDA", "MERGER", "INVESTIGATION")
    )
    if not material:
        return view, "none", None

    new_q = f"What changed after: {titles[0][:120]}"
    new_priority = "HIGH" if "DOWNGRADE" in blob or "INVESTIGATION" in blob else "ELEVATED"
    new_view = f"Updated from research: {titles[0][:160]}"
    updated = AgentViewState(
        agent_id=view.agent_id,
        subject_guid=view.subject_guid,
        next_research_question=new_q,
        notify_priority=new_priority,
        view_summary=new_view,
        version=view.version + 1,
    )
    # Prefer changed_question as the primary demonstrated effect (defect 1 closer).
    effect_kind = "changed_question"
    effect_ref = f"agent_view:{view.agent_id}:{view.subject_guid}:v{updated.version}:question"
    return updated, effect_kind, effect_ref


def consume_dossier(
    *,
    agent_id: str,
    agent_version: str,
    dossier: DossierRecord,
    view: AgentViewState,
    purpose: str = "wake_research",
    wake_id: Optional[str] = None,
    source_sha: str = "fixture",
    clock: Optional[Clock] = None,
    require_receipt: bool = True,
) -> tuple[AgentViewState, ConsumptionReceipt]:
    """Lane A-facing consumption API. Returns updated view + receipt."""
    clock = clock or _utc_now
    now = clock()
    if dossier.subject_guid != view.subject_guid:
        raise ReferentialIntegrityError("dossier.subject_guid != view.subject_guid")

    evidence, reasons = select_evidence(dossier, purpose=purpose)
    if not evidence and require_receipt is False:
        raise MissingConsumptionReceipt("no evidence and receipt required disabled")

    updated, effect_kind, effect_ref = _apply_relevant_effect(view, evidence)
    # Primary source_id = first research object id (referential).
    source_id = evidence[0]["research_id"] if evidence else dossier.dossier_id
    if evidence:
        for e in evidence:
            if not e.get("research_id"):
                raise ReferentialIntegrityError("evidence missing research_id")
            if e["research_id"] not in dossier.research_ids:
                raise ReferentialIntegrityError(
                    f"evidence research_id {e['research_id']} not in dossier"
                )

    receipt_id = mint_consumption_receipt_id(
        agent_id, "research_object", source_id, purpose
    )
    ts = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    receipt = ConsumptionReceipt(
        receipt_id=receipt_id,
        agent_id=agent_id,
        agent_version=agent_version,
        source_kind="research_object",
        source_id=source_id,
        purpose=purpose,
        effect_kind=effect_kind,
        effect_ref=effect_ref,
        subject_guid=view.subject_guid,
        wake_id=wake_id,
        thread_id=None,
        policy_decision="ALLOW" if evidence else "NO_EVIDENCE",
        retrieved_at=ts,
        acknowledged_at=ts,
        derived_artifact_ids=[dossier.dossier_id],
        influence_declaration=(
            "research_object_influenced_agent_view"
            if effect_kind != "none"
            else "research_object_retrieved_no_effect"
        ),
        influence_source_ids=[e["research_id"] for e in evidence],
        evidence_used=list(evidence),
        selection_reasons=list(reasons),
        source_sha=source_sha,
        produced_at=ts,
        correlation_id=receipt_id,
        idempotency_key=receipt_id,
        parent_id=source_id,
        provenance={
            "producer": "research_consumption",
            "inputs": [dossier.dossier_id],
            "policy_decisions": [purpose],
            "llm": None,
        },
    )
    if require_receipt and receipt is None:
        raise MissingConsumptionReceipt("receipt missing")
    return updated, receipt


def persist_receipt(receipt: ConsumptionReceipt, path: Path) -> None:
    """Disposable local receipt store for tests — never production tables."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list = []
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
    # Idempotent on receipt_id
    rows = [r for r in rows if r.get("receipt_id") != receipt.receipt_id]
    rows.append(receipt.to_dict())
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_receipts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
