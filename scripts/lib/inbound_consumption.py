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


# ── Poller-facing entry (canonical hook for run_telegram_callback_poller.py) ──

APPROVED_POLLER_PATH = "scripts/run_telegram_callback_poller.py"
FEED_SYMBOLS = (
    "feed_telegram_update",
    "scripts.lib.inbound_consumption.feed_telegram_update",
    "from scripts.lib.inbound_consumption import feed_telegram_update",
    "from inbound_consumption import feed_telegram_update",
)


def feed_telegram_update(
    update: dict[str, Any],
    *,
    agent_id: str = DEFAULT_AGENT,
    agent_version: str = "lane-i@v1",
    purpose: str = DEFAULT_PURPOSE,
    effect_kind: str = "none",
    effect_ref: str | None = None,
    require_correlation: bool = False,
    commitment_id: str | None = None,
    provenance_producer: str = "runtime_poller",
) -> ConsumeResult:
    """Runtime entry for the approved Telegram callback poller.

    Never contacts Telegram itself. Never interprets inbound text as broker
    permission. Default ``effect_kind='none'`` (not behavioral consumption).
    Checkpoint/offset persistence is owned by ``normalize_inbound_update`` via
    the Wave C inbound checkpoint (advanced only after successful publish).
    """
    # Hard refusal of financial/broker action flags if a caller tries to smuggle them.
    if effect_kind in BEHAVIORAL_EFFECT_KINDS and effect_ref and str(effect_ref).startswith(
        ("order:", "broker:", "trade:")
    ):
        return ConsumeResult(
            ok=False,
            reason="refused:financial_or_broker_effect_forbidden",
            effect_kind="none",
        )
    return process_inbound_update(
        update,
        agent_id=agent_id,
        agent_version=agent_version,
        purpose=purpose,
        effect_kind=effect_kind or "none",
        effect_ref=effect_ref,
        publish=True,
        require_correlation=require_correlation,
        commitment_id=commitment_id,
        provenance_producer=provenance_producer,
    )


def _iter_py_files(root: Any) -> list[Any]:
    from pathlib import Path

    root_p = Path(root)
    out: list[Any] = []
    for p in root_p.rglob("*.py"):
        parts = set(p.parts)
        if "tests" in parts or ".venv" in parts or "__pycache__" in parts:
            continue
        out.append(p)
    return out


def find_normalize_runtime_callers(repo_root: Any | None = None) -> list[str]:
    """Non-test production files that reference ``normalize_inbound_update``."""
    from pathlib import Path

    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    needle = "normalize_inbound_update"
    hits: list[str] = []
    for p in _iter_py_files(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle not in text:
            continue
        # Defining site alone is not a caller.
        rel = str(p.relative_to(root)).replace("\\", "/")
        if rel.endswith("scripts/lib/inbound_event_normalizer.py"):
            # Count only if something other than the def line references it — skip def module.
            continue
        hits.append(rel)
    return sorted(set(hits))


def poller_wires_feed(repo_root: Any | None = None) -> bool:
    """True when the approved poller references ``feed_telegram_update``."""
    from pathlib import Path

    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    poller = root / APPROVED_POLLER_PATH
    if not poller.is_file():
        return False
    try:
        text = poller.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(sym in text for sym in FEED_SYMBOLS)


class InboundReachabilityError(RuntimeError):
    """normalize_inbound_update has no non-test runtime caller, or poller unwired."""


def assert_inbound_runtime_reachability(repo_root: Any | None = None) -> dict[str, Any]:
    """Fail closed when the Lane I normalizer is dark at runtime.

    Checks:
      1. At least one non-test module calls ``normalize_inbound_update``.
      2. ``scripts/run_telegram_callback_poller.py`` feeds ``feed_telegram_update``
         (requires SFR-I-RUNTIME-001 until applied).
    """
    callers = find_normalize_runtime_callers(repo_root)
    wired = poller_wires_feed(repo_root)
    report = {
        "ok": bool(callers) and wired,
        "normalize_runtime_callers": callers,
        "poller_path": APPROVED_POLLER_PATH,
        "poller_wires_feed_telegram_update": wired,
        "sfr_required_if_unwired": "SFR-I-RUNTIME-001",
    }
    if not callers:
        raise InboundReachabilityError(
            "normalize_inbound_update has no non-test runtime caller; "
            f"report={report}"
        )
    if not wired:
        raise InboundReachabilityError(
            f"{APPROVED_POLLER_PATH} does not call feed_telegram_update; "
            "apply SFR-I-RUNTIME-001. "
            f"report={report}"
        )
    return report
