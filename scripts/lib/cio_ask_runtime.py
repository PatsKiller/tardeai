"""Shared Ask research runtime, independent of UI/resolver/broker adapters.

Both the operator core and native lifecycle use these exact accounting, answer,
shared-memory and notification-intent functions. The native dependency set cannot
resolve positions or invoke the operator converse API. Ledger and memory writers
are unchanged; no additional authoritative store or send path exists.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from scripts.lib.cio_ask_contract import (
    AskAnswer,
    AskResearchContext,
    EntityRef,
    DEEP_RESEARCH_ENTRYPOINT,
    utc_now_iso,
    validate_answer,
)
from scripts.lib.cio_ask_memory import SpineAskMemory
from scripts.lib.cio_ask_store import AskEventStore, event_id_for

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config/cio_ask.json"


def _deps(deps):
    return deps  # Shared sink functions require explicit dependencies; reads never construct live ones.


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    try:
        return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "_error": "config unreadable — Ask the CIO fails closed"}


class CostGate:
    """Ask-level caps on top of the governed LLM caps. Fails closed. Quick answers use the desk loop's own caps."""

    def __init__(
        self, config: dict[str, Any], store: AskEventStore, global_check: Optional[Callable[[str, float], dict]] = None
    ):
        self.cfg = config.get("cost") or {}
        self.store = store
        self.global_check = global_check

    @property
    def approved(self) -> bool:
        return str((self.cfg.get("approval") or {}).get("status") or "").upper() == "APPROVED"

    def allow(self, projected_usd: float) -> dict[str, Any]:
        if not self.approved:
            return {
                "allow": False,
                "reason": "CAP_AWAITING_APPROVAL",
                "detail": "the Ask-the-CIO daily cap is PROPOSED; deep answers and re-answers stay inert",
            }
        per_q = float(self.cfg.get("per_question_cap_usd") or 0)
        if projected_usd > per_q:
            return {"allow": False, "reason": "PER_QUESTION_CAP", "detail": f"${projected_usd:.2f} > ${per_q:.2f}"}
        daily = float(self.cfg.get("daily_cap_usd") or 0)
        spent = self.store.cost_today()
        if spent + projected_usd > daily:
            return {"allow": False, "reason": "DAILY_CAP", "detail": f"${spent:.2f} spent of ${daily:.2f}"}
        check = self.global_check or _global_cap_check
        try:
            g = check(str(self.cfg.get("process_id") or "cio_ask_deep_research"), projected_usd) or {}
        except Exception as exc:  # noqa: BLE001 — never fail open
            return {"allow": False, "reason": "GLOBAL_CAP_UNAVAILABLE", "detail": type(exc).__name__}
        if not g.get("allow"):
            return {"allow": False, "reason": str(g.get("reason") or "GLOBAL_CAP"), "detail": g.get("scope")}
        return {"allow": True, "reason": g.get("reason") or "OK", "spent_today": spent, "native_admission": g}

    def record(self, *, thread_id: str, ask_id: str, usd: float, kind: str) -> None:
        self.store.append(
            "ask.cost",
            {"thread_id": thread_id, "ask_id": ask_id, "usd": round(float(usd), 6), "cost_kind": kind},
            event_id=event_id_for("ask.cost", ask_id, kind, utc_now_iso()),
        )


def _global_cap_check(process_id: str, projected_usd: float) -> dict:
    """Config admission only; measured process/global/provider reservation belongs to the native bridge."""
    from scripts.lib.cio_ask_provider_routes import native_route_admission

    return native_route_admission(process_id, projected_usd=projected_usd)


@dataclass
class AskDeps:
    store: AskEventStore
    memory: Any
    tracker: Any
    resolver: Callable[[str], list[EntityRef]]
    sizing: Any
    cost: CostGate
    config: dict[str, Any]
    deep_provider: Optional[Callable[[AskResearchContext], AskAnswer]] = None
    telegram_send: Optional[Callable[[str], dict]] = None
    run_async: bool = True
    delivery_read: Optional[Callable[[str], dict]] = None
    notification_enqueue: Optional[Callable[[str], dict]] = None


def _default_notification_enqueue(text: str) -> dict:
    """Queue a CIO-origin advisory message in the CIO notification outbox. Never a direct send: the CIO send
    entrypoints are a shrink-only allowlist (tests/test_cio_origin_gate_20260916.py), and delivery (live or shadow)
    stays governed by the outbox's delivery worker. Cross-channel follow-up does not need the outbound message id:
    the body carries the thread id, and a Telegram reply quotes it (``reply_to_text``)."""
    import hashlib  # noqa: PLC0415

    from scripts.lib.cio_notification_outbox import NotificationOutbox  # noqa: PLC0415

    body = str(text or "")[:3800]
    nid = "ntf_ask_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]
    note = {
        "notification_id": nid,
        "message_class": "advisory",
        "channel_targets": ["telegram"],
        "subject": "CIO · Ask the CIO",
        "body": body,
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "sender": "cio_ask",
        "trace_id": f"trace_{nid}",
        "dedupe_key": "cio_ask:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24],
        "idempotency_key": f"cio_ask:{nid}",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "parse_mode": None,
    }
    event = NotificationOutbox().enqueue(note, actor_id="cio_ask", actor_type="agent", authority="advisory")
    actual_ref = (event.get("payload") or {}).get("notification_id") or event.get("stream_id")
    return {"ok": bool(actual_ref), "queued": actual_ref, "message_id": None}


def _default_delivery_read(notification_id: str) -> dict:
    """Read the existing outbox projection; absence never creates a new outbox."""
    from scripts.lib.cio_notification_outbox import NotificationOutbox

    path = REPO_ROOT / "data" / "cio" / "operator_notification_outbox.jsonl"
    if not path.is_file() or path.stat().st_size == 0:
        return {"state": "queued", "ref": notification_id, "reason": "OUTBOX_READBACK_UNAVAILABLE"}
    try:
        row = NotificationOutbox(event_store_path=path).get_notification(notification_id) or {}
        status = row.get("current_status")
        if status == "DELIVERED" and row.get("external_message_id") is not None and row.get("transport_receipt_hash"):
            return {
                "state": "delivered",
                "ref": notification_id,
                "message_id": row["external_message_id"],
                "transport_receipt_hash": row["transport_receipt_hash"],
            }
        if status in {"DEAD_LETTERED", "EXPIRED", "CANCELLED"}:
            return {"state": "failed", "ref": notification_id, "reason": "OUTBOX_" + status}
        return {"state": "queued", "ref": notification_id, "reason": "OUTBOX_" + str(status or "READBACK_UNAVAILABLE")}
    except Exception as exc:
        return {"state": "queued", "ref": notification_id, "reason": "OUTBOX_READBACK:" + type(exc).__name__}


def _default_deep_provider() -> Optional[Callable[[AskResearchContext], AskAnswer]]:
    mod, _, fn = DEEP_RESEARCH_ENTRYPOINT.partition(":")
    try:
        return getattr(importlib.import_module(mod), fn)
    except Exception:  # noqa: BLE001 — Phase 9 not landed
        return None


def _remember(d: AskDeps, e: EntityRef, kind: str, summary: str, ref: str) -> dict | None:
    try:
        return d.memory.append(entity=e, kind=kind, summary=summary, ref=ref)
    except Exception as exc:  # noqa: BLE001 — preserve a retryable acknowledgement gap
        return {"ok": False, "error": type(exc).__name__}


def record_answer(ans: AskAnswer, *, turn: Optional[Any] = None, deps: Optional[AskDeps] = None) -> None:
    d = _deps(deps)
    if d is None:
        return
    problems = validate_answer(ans, allow_size_suggestion=False)
    payload = ans.to_dict(allow_size_suggestion=False)
    payload["validation"] = problems
    d.store.append(
        "ask.answer_version",
        {"thread_id": ans.thread_id, "ask_id": ans.ask_id, "version": ans.version, "answer": payload},
        event_id=event_id_for("ask.answer_version", ans.ask_id, ans.version),
    )
    q = turn.request.question if turn else ""
    kind_q = "ask.follow_up" if turn and turn.turn_kind == "follow_up" else "ask.asked"
    for e in ans.entities or (turn.entities if turn else []):
        if turn and ans.version == 1:
            _remember(d, e, kind_q, f"({ans.ask_id} via {turn.request.channel}) {q}", ans.ask_id)
            _remember(
                d, e, "ask.entity_resolved", f"{e.name} → {e.symbol or e.entity_guid} ({e.resolution})", ans.ask_id
            )
        if ans.status == "reanswer":
            _remember(
                d,
                e,
                "ask.reanswer_triggered",
                f"{(ans.trigger or {}).get('summary') or 'material change'}",
                ans.answer_id,
            )
        _remember(d, e, "ask.answer_version", f"v{ans.version} {ans.status}: {_plain(ans.summary, 600)}", ans.answer_id)
        for s in ans.sources[:6]:
            _remember(d, e, "ask.source", f"{s.title} ({s.kind}, as of {s.as_of})", ans.answer_id)


def _plain(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def link_channel(store: AskEventStore, *, thread_id: str, channel: str, chat_id: Any, message_id: Any) -> None:
    store.append(
        "ask.channel_link",
        {"thread_id": thread_id, "channel": channel, "chat_id": str(chat_id), "message_id": str(message_id)},
        event_id=event_id_for("ask.channel_link", channel, chat_id, message_id),
    )


def sync_answer_memory(ans: AskAnswer, *, deps: Optional[AskDeps] = None) -> dict:
    """Retry shared facts/summary writes without repeating research or changing its answer."""
    d = _deps(deps)
    if d is None:
        return {"state": "pending", "reason": "ASK_DISABLED"}
    receipts = []
    for entity in ans.entities:
        receipts.append(
            _remember(
                d,
                entity,
                "ask.answer_version",
                f"v{ans.version} {ans.status}: {_plain(ans.summary, 600)}",
                ans.answer_id,
            )
        )
    private_verified = []
    for index, entity in enumerate(ans.entities):
        if entity.kind != "private_entity" or not entity.entity_guid:
            continue
        stored = d.store.thread(ans.thread_id) or {}
        verified = any(
            a.get("answer_id") == ans.answer_id
            and any(e.get("entity_guid") == entity.entity_guid for e in a.get("entities", []))
            for turn in stored.get("turns", [])
            for a in turn.get("answers", [])
        )
        if verified:
            receipts[index] = {"ok": True, "sink": "cio_ask_events", "ref": ans.answer_id}
            private_verified.append(entity.entity_guid)
    summaries_ok = bool(receipts) and all(
        isinstance(x, dict) and ((x.get("spine") or {}).get("ok") is True or x.get("ok") is True) for x in receipts
    )
    prior = (ans.provenance or {}).get("memory_receipt") or {}
    facts = prior
    if (ans.provenance or {}).get("memory_retry_payload"):
        try:
            from scripts.lib.cio_ask_research import retry_research_memory

            facts = retry_research_memory(ans, apply=bool((d.config.get("lifecycle") or {}).get("memory_apply", False)))
        except Exception as exc:
            return {
                "state": "pending",
                "reason": "FACT_MEMORY_SYNC:" + type(exc).__name__,
                "summary_verified": summaries_ok,
            }
    # No gathered facts needs no fact write; an unmeasured/failed retry never
    # proves that there were zero facts to write.
    if not isinstance(facts, dict):
        return {"state": "pending", "reason": "FACT_MEMORY_RECEIPT_INVALID", "summary_verified": summaries_ok}
    try:
        planned = int(facts.get("planned_count", facts.get("appended", 0)) or 0)
        applied = int(facts.get("applied_count", 0) or 0)
        duplicate = int(facts.get("skipped_duplicate", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return {"state": "pending", "reason": "FACT_MEMORY_RECEIPT_INVALID", "summary_verified": summaries_ok}
    facts_failed = (
        facts.get("ok") is False
        or facts.get("not_measured") is True
        or bool(facts.get("refused") or facts.get("error"))
        or str(facts.get("status") or "").lower() in {"pending", "failed", "error", "unavailable"}
        or min(planned, applied, duplicate) < 0
    )
    facts_ok = not facts_failed and (not planned or (facts.get("apply") is True and applied + duplicate >= planned))
    return {
        "state": "synced" if summaries_ok and facts_ok else "pending",
        "reason": None if summaries_ok and facts_ok else "SHARED_MEMORY_NOT_ACKNOWLEDGED",
        "summary_verified": summaries_ok,
        "private_ledger_verified": private_verified,
        "facts_planned": planned,
        "facts_applied": applied,
        "ref": ans.answer_id,
    }


def _post_to_telegram(d: AskDeps, thread_id: str, text: str) -> dict:
    """Native publication only queues an intent; transport acknowledgement is not delivery."""
    if not d.notification_enqueue:
        return {"state": "not_configured", "reason": "NO_NOTIFICATION_ENQUEUE"}
    has_tg = any(x.get("channel") == "telegram" for x in d.store.channel_links(thread_id))
    if not (has_tg or d.config.get("mirror_cc_to_telegram")):
        return {"state": "not_required", "reason": "NO_CHANNEL_TARGET"}
    try:
        res = d.notification_enqueue(f"{text}\n\nThread {thread_id}") or {}
        ref = res.get("queued")
        if res.get("ok") is True and isinstance(ref, str) and ref.strip():
            return {"state": "queued", "ref": ref}
        return {"state": "failed", "reason": "NOTIFICATION_INTENT_NOT_ACKNOWLEDGED"}
    except Exception as exc:
        return {"state": "failed", "reason": "NOTIFICATION_ENQUEUE_FAILED:" + type(exc).__name__}


def default_deps():
    cfg = load_config()
    store = AskEventStore()
    if not store.write_authorized():
        cfg = {**cfg, "enabled": False, "_error": "CIO_ASK_STORE_NOT_APPROVED"}
    return AskDeps(
        store=store,
        memory=SpineAskMemory(ledger=store),
        tracker=None,
        resolver=None,
        sizing=None,
        cost=CostGate(cfg, store),
        config=cfg,
        deep_provider=_default_deep_provider(),
        notification_enqueue=_default_notification_enqueue,
        delivery_read=_default_delivery_read,
        run_async=False,
    )
