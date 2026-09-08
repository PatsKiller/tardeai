"""Lane I — inbound event → agent consumption receipt.

Closes the structurally dark edge:

  normalized inbound CommunicationEvent
    → agent consumption (AgentConsumptionReceipt@v2)
    → honest effect_kind (including ``none``)
    → ``none`` never counts as behavioral consumption

Default: no financial or broker action. Reading an operator turn is not acting
on it. Fail-closed when identity or receipt persistence is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.lib.comms.agent_contracts import (
    AgentConsumptionReceipt,
    AgentContractError,
    emit_consumption_receipt,
)
from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.inbound_event_normalizer import normalize_inbound_update

SCHEMA = "InboundConsumption@v1"
DEFAULT_PURPOSE = "operator_turn_intake"
DEFAULT_AGENT = "cio"
BEHAVIORAL_EFFECT_KINDS = frozenset(
    {"changed_question", "changed_priority", "changed_view", "changed_commitment"}
)


@dataclass
class ConsumeResult:
    ok: bool
    reason: str
    event_id: str | None = None
    receipt_id: str | None = None
    effect_kind: str = "none"
    effect_ref: str | None = None
    counts_as_behavioral_consumption: bool = False
    normalize: dict[str, Any] = field(default_factory=dict)
    receipt: dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "event_id": self.event_id,
            "receipt_id": self.receipt_id,
            "effect_kind": self.effect_kind,
            "effect_ref": self.effect_ref,
            "counts_as_behavioral_consumption": self.counts_as_behavioral_consumption,
            "normalize": dict(self.normalize),
            "receipt": dict(self.receipt),
            "schema": self.schema,
        }


def counts_as_behavioral_consumption(effect_kind: str, effect_ref: str | None) -> bool:
    """``effect_kind='none'`` is legal and honest — never behavioral maturity."""
    ek = (effect_kind or "none").strip() or "none"
    if ek == "none":
        return False
    if ek not in BEHAVIORAL_EFFECT_KINDS:
        return False
    return bool(effect_ref and str(effect_ref).strip())


def consume_inbound_event(
    event: CommunicationEvent | dict[str, Any],
    *,
    agent_id: str = DEFAULT_AGENT,
    agent_version: str = "lane-i@v1",
    purpose: str = DEFAULT_PURPOSE,
    effect_kind: str = "none",
    effect_ref: str | None = None,
    allow_unknown_agent: bool = False,
    provenance_producer: str = "test",
) -> ConsumeResult:
    """Emit AgentConsumptionReceipt@v2 linked to the exact inbound event_id."""
    if isinstance(event, CommunicationEvent):
        event_id = event.event_id
        thread_id = event.thread_id
        correlation_id = event.correlation_id
        subject_key = event.subject_key
        event_dict = {
            "event_id": event_id,
            "thread_id": thread_id,
            "correlation_id": correlation_id,
            "subject_key": subject_key,
            "knowledge_eligibility": event.knowledge_eligibility,
            "knowledge_status": event.knowledge_status,
            "direction": event.direction,
        }
    elif isinstance(event, dict):
        event_id = str(event.get("event_id") or "").strip() or None
        thread_id = event.get("thread_id")
        correlation_id = event.get("correlation_id")
        event_dict = dict(event)
    else:
        return ConsumeResult(ok=False, reason="malformed:event_type")

    if not event_id:
        return ConsumeResult(ok=False, reason="identity_unavailable:event_id")

    ek = (effect_kind or "none").strip() or "none"
    # Default path: inbound operator turns are not institutional facts and must
    # not claim a behavioral effect without an explicit effect_ref.
    if ek != "none" and not (effect_ref and str(effect_ref).strip()):
        return ConsumeResult(
            ok=False,
            reason="effect_ref_required_for_non_none",
            event_id=event_id,
            effect_kind=ek,
        )

    try:
        receipt = emit_consumption_receipt(
            agent_id,
            event_id=event_id,
            source_kind="comm_event",
            source_id=event_id,
            purpose=purpose,
            agent_version=agent_version,
            thread_id=str(thread_id) if thread_id else None,
            effect_kind=ek,
            effect_ref=effect_ref,
            correlation_id=str(correlation_id) if correlation_id else None,
            parent_id=event_id,
            parent_kind="comm_event",
            event=event_dict,
            allow_unknown=allow_unknown_agent,
            provenance={
                "producer": provenance_producer,
                "inputs": [event_id],
                "policy_decisions": ["inbound_operator_turn_intake"],
                "llm": None,
            },
        )
    except AgentContractError as exc:
        return ConsumeResult(
            ok=False,
            reason=f"receipt_rejected:{exc}",
            event_id=event_id,
            effect_kind=ek,
        )
    except Exception as exc:  # noqa: BLE001
        return ConsumeResult(
            ok=False,
            reason=f"persistence_failure:{type(exc).__name__}",
            event_id=event_id,
            effect_kind=ek,
        )

    row = receipt.to_dict() if isinstance(receipt, AgentConsumptionReceipt) else dict(receipt)
    behavioral = counts_as_behavioral_consumption(ek, effect_ref)
    return ConsumeResult(
        ok=True,
        reason="consumed",
        event_id=event_id,
        receipt_id=row.get("receipt_id"),
        effect_kind=ek,
        effect_ref=effect_ref,
        counts_as_behavioral_consumption=behavioral,
        receipt=row,
    )


def process_inbound_update(
    update: dict[str, Any],
    *,
    agent_id: str = DEFAULT_AGENT,
    agent_version: str = "lane-i@v1",
    purpose: str = DEFAULT_PURPOSE,
    effect_kind: str = "none",
    effect_ref: str | None = None,
    publish: bool = True,
    require_correlation: bool = False,
    commitment_id: str | None = None,
    provenance_producer: str = "test",
) -> ConsumeResult:
    """End-to-end: normalize → publish → consume receipt.

    Default ``effect_kind='none'`` — honest no-behavior intake.
    """
    norm = normalize_inbound_update(
        update,
        publish=publish,
        commitment_id=commitment_id,
        require_correlation=require_correlation,
    )
    if not norm.ok:
        return ConsumeResult(
            ok=False,
            reason=norm.reason,
            event_id=norm.event_id,
            normalize=norm.to_dict(),
        )

    if norm.event is None or not norm.event_id:
        return ConsumeResult(
            ok=False,
            reason="identity_unavailable:normalized_event",
            normalize=norm.to_dict(),
        )

    consumed = consume_inbound_event(
        norm.event,
        agent_id=agent_id,
        agent_version=agent_version,
        purpose=purpose,
        effect_kind=effect_kind,
        effect_ref=effect_ref,
        provenance_producer=provenance_producer,
    )
    consumed.normalize = norm.to_dict()
    return consumed
