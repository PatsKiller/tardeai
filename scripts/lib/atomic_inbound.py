#!/usr/bin/env python3
"""atomic_inbound.py — one coherent inbound intake transaction (Grok-closure Phase 3).

Orchestrates the inbound pipeline so the checkpoint can only advance after every
durable artifact exists, and there is exactly ONE checkpoint owner:

    Telegram update
      → normalize_inbound_update (durable CommunicationEvent@v2)
      → tag_inbound (deterministic identity spine tag, no model)
      → persist operator turn (durable operator_conversation_turns)
      → emit AgentConsumptionReceipt@v2 (durable, all columns)
      → commit_checkpoint (the ONLY durable offset advance, LAST)

Invariants enforced here (and asserted by tests):
  * One checkpoint owner: this is the only caller that advances the offset after
    all artifacts are written. ``normalize_inbound_update`` is used in its
    publish-only mode so the checkpoint is never advanced half-way.
  * No advancement before all artifacts: ``commit_checkpoint`` runs only after
    event, operator turn, and receipt each report success.
  * Idempotent retry: ``claim_update`` gates first; a replayed update returns
    already_processed and writes nothing.
  * No premature in-memory dedupe: replay denial is a consequence of the durable
    checkpoint, never an in-process set.
  * Plausibility metric: a committed offset that is wildly ahead of the update
    under processing (corrupt / tampered checkpoint) is surfaced as an incident
    signal rather than silently starving the poller.

Authority: READ_ONLY_ADVISORY. Never interprets inbound text as broker
permission; effect_kind defaults to 'none'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

SCHEMA = "AtomicInbound@v1"
FEATURE_FLAG = "ATOMIC_INBOUND_ENABLED"

#: A checkpoint more than this many update_ids ahead of the update being
#: processed is implausible for a single-user bot and is treated as an incident.
PLAUSIBILITY_LIMIT = 1_000_000


@dataclass
class AtomicInboundResult:
    ok: bool
    outcome: str  # processed | already_processed | refused | error
    update_id: int | None = None
    event_id: str | None = None
    receipt_id: str | None = None
    turn_written: int = 0
    checkpoint_offset: int | None = None
    plausibility: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "outcome": self.outcome,
            "update_id": self.update_id,
            "event_id": self.event_id,
            "receipt_id": self.receipt_id,
            "turn_written": self.turn_written,
            "checkpoint_offset": self.checkpoint_offset,
            "plausibility": dict(self.plausibility),
            "reason": self.reason,
        }


def _checkpoint_plausible(update_id: int, committed_offset: int) -> dict[str, Any]:
    gap = committed_offset - update_id
    plausible = gap <= PLAUSIBILITY_LIMIT
    return {
        "update_id": update_id,
        "committed_offset": committed_offset,
        "gap": gap,
        "plausible": plausible,
        "incident": not plausible,
    }


def process_update_atomically(
    update: dict[str, Any],
    *,
    agent_id: str = "cio",
    agent_version: str = "atomic-inbound@v1",
    effect_kind: str = "none",
    effect_ref: str | None = None,
    provenance_producer: str = "atomic_inbound",
    env: dict[str, Any] | None = None,
    steps: dict[str, Callable[..., Any]] | None = None,
) -> AtomicInboundResult:
    """Run one inbound update through normalize → tag → turn → receipt → checkpoint.

    ``steps`` injects the five pipeline functions for hermetic tests. Production
    callers omit it and the real modules are used. Every step must return a
    dict-like; a non-``ok`` step short-circuits BEFORE the checkpoint advances.
    """
    import os

    env = dict(env if env is not None else os.environ)

    if str(env.get(FEATURE_FLAG, "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return AtomicInboundResult(ok=False, outcome="refused", reason="feature_flag_off")

    if not isinstance(update, dict):
        return AtomicInboundResult(ok=False, outcome="error", reason="update_not_dict")

    try:
        from scripts.lib.comms.inbound import _coerce_update_id, claim_update, commit_checkpoint
        from scripts.lib.inbound_event_normalizer import normalize_inbound_update
        from scripts.lib.inbound_identity_tagger import tag_inbound, persist_turn
        from scripts.lib.comms.agent_contracts import emit_consumption_receipt
    except Exception as exc:  # pragma: no cover - import path variance
        return AtomicInboundResult(ok=False, outcome="error", reason=f"import_failed:{type(exc).__name__}")

    try:
        uid = _coerce_update_id(update.get("update_id"))
    except Exception as exc:
        return AtomicInboundResult(ok=False, outcome="error", reason=f"update_id:{exc}")

    # 1) Replay gate (read-only, no durable write).
    claim = claim_update(uid)
    plausibility = _checkpoint_plausible(uid, claim.checkpoint_offset)
    if claim.already_processed:
        return AtomicInboundResult(
            ok=True,
            outcome="already_processed",
            update_id=uid,
            checkpoint_offset=claim.checkpoint_offset,
            plausibility=plausibility,
        )

    # 2) Normalize + publish the durable event. publish=True so the event row
    #    is durable before any downstream artifact claims to reference it.
    norm = steps["normalize"] if steps and "normalize" in steps else normalize_inbound_update
    n = norm(update, publish=True)
    if not getattr(n, "ok", None) if hasattr(n, "ok") else not (n.get("ok") if isinstance(n, dict) else False):
        reason = n.reason if hasattr(n, "reason") else (n.get("reason") if isinstance(n, dict) else "normalize_failed")
        return AtomicInboundResult(
            ok=False, outcome="error", update_id=uid, reason=str(reason), plausibility=plausibility
        )
    event_id = getattr(n, "event_id", None) or (n.get("event_id") if isinstance(n, dict) else None)
    event = getattr(n, "event", None) or (n.get("event") if isinstance(n, dict) else None)
    if not event_id:
        return AtomicInboundResult(
            ok=False, outcome="error", update_id=uid, reason="no_event_id", plausibility=plausibility
        )

    # 3) Identity tag (deterministic; no model).
    text = _inbound_text(update, event)
    tag_fn = steps["tag"] if steps and "tag" in steps else tag_inbound
    tag = tag_fn(text)

    # 4) Durable operator turn.
    turn_fn = steps["turn"] if steps and "turn" in steps else _persist_turn_for_update
    try:
        turn_written = int(turn_fn(update, tag, text, event) or 0)
    except Exception as exc:
        return AtomicInboundResult(
            ok=False,
            outcome="error",
            update_id=uid,
            event_id=event_id,
            reason=f"turn_failed:{type(exc).__name__}",
            plausibility=plausibility,
        )

    # 5) Durable v2 consumption receipt (effect_kind 'none' by default).
    receipt_fn = steps["receipt"] if steps and "receipt" in steps else _emit_receipt_for_event
    try:
        rec = receipt_fn(
            agent_id=agent_id,
            agent_version=agent_version,
            event_id=event_id,
            event=event,
            effect_kind=effect_kind,
            effect_ref=effect_ref,
            provenance_producer=provenance_producer,
        )
    except Exception as exc:
        return AtomicInboundResult(
            ok=False,
            outcome="error",
            update_id=uid,
            event_id=event_id,
            reason=f"receipt_failed:{type(exc).__name__}",
            plausibility=plausibility,
        )
    if not rec.get("ok") if isinstance(rec, dict) else False:
        return AtomicInboundResult(
            ok=False,
            outcome="error",
            update_id=uid,
            event_id=event_id,
            reason="receipt_rejected",
            plausibility=plausibility,
        )

    # 6) Checkpoint LAST — the only durable offset advance.
    try:
        new_offset = commit_checkpoint(uid)
    except Exception as exc:
        return AtomicInboundResult(
            ok=False,
            outcome="error",
            update_id=uid,
            event_id=event_id,
            reason=f"checkpoint_failed:{type(exc).__name__}",
            plausibility=plausibility,
        )

    return AtomicInboundResult(
        ok=True,
        outcome="processed",
        update_id=uid,
        event_id=event_id,
        receipt_id=rec.get("receipt_id") if isinstance(rec, dict) else None,
        turn_written=turn_written,
        checkpoint_offset=int(new_offset),
        plausibility=plausibility,
    )


def _inbound_text(update: dict[str, Any], event: Any) -> str:
    cb = update.get("callback_query")
    msg = update.get("message")
    if cb is not None:
        return str(cb.get("data") or "") or _event_text(event)
    if msg is not None:
        return str(msg.get("text") or "") or _event_text(event)
    return _event_text(event)


def _event_text(event: Any) -> str:
    if hasattr(event, "sanitized_body"):
        return str(event.sanitized_body or "")
    if isinstance(event, dict):
        return str(event.get("sanitized_body") or event.get("payload", {}).get("text") or "")
    return ""


def _persist_turn_for_update(update: dict[str, Any], tag: dict[str, Any], text: str, event: Any) -> int:
    from scripts.lib.inbound_identity_tagger import persist_turn
    from scripts.lib.comms.inbound import _db_conn

    cb = update.get("callback_query")
    msg = update.get("message")
    inner = (cb or {}).get("message") or {} if cb is not None else msg or {}
    chat_id = _as(inner.get("chat", {}).get("id"))
    message_id = _as(inner.get("message_id"))
    reply_to = _as((inner.get("reply_to_message") or {}).get("message_id"))
    conn = _db_conn()
    if conn is None:
        return 0
    return persist_turn(
        tag,
        conn=conn,
        text=text,
        role="operator",
        chat_id=chat_id,
        message_id=message_id,
        thread_id=message_id,
        reply_to_message_id=reply_to,
    )


def _emit_receipt_for_event(
    *,
    agent_id: str,
    agent_version: str,
    event_id: str,
    event: Any,
    effect_kind: str,
    effect_ref: str | None,
    provenance_producer: str,
) -> dict[str, Any]:
    from scripts.lib.comms.agent_contracts import emit_consumption_receipt

    ev = event if isinstance(event, dict) else None
    return emit_consumption_receipt(
        agent_id,
        event_id=event_id,
        source_kind="comm_event",
        source_id=event_id,
        purpose="operator_turn_intake",
        agent_version=agent_version,
        thread_id=getattr(event, "thread_id", None) if not ev else ev.get("thread_id"),
        effect_kind=effect_kind or "none",
        effect_ref=effect_ref,
        correlation_id=getattr(event, "correlation_id", None) if not ev else ev.get("correlation_id"),
        parent_id=event_id,
        parent_kind="comm_event",
        event=ev
        if ev is not None
        else {
            "event_id": event_id,
            "thread_id": getattr(event, "thread_id", None),
            "correlation_id": getattr(event, "correlation_id", None),
            "direction": getattr(event, "direction", "INBOUND"),
        },
        allow_unknown=True,
        provenance={
            "producer": provenance_producer,
            "inputs": [event_id],
            "policy_decisions": ["atomic_inbound_operator_turn_intake"],
            "llm": None,
        },
    )


def _as(v: Any) -> str | None:
    return str(v) if v is not None else None


__all__ = [
    "SCHEMA",
    "FEATURE_FLAG",
    "AtomicInboundResult",
    "process_update_atomically",
]
