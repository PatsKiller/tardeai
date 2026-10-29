"""Ask the CIO — one brain for the Command Center ask bar, "My questions" and Telegram. READ_ONLY_ADVISORY.

Phases 8, 10 and 11 (operator 2026-10-23). The contract is ``scripts/lib/cio_ask_contract.py``.

How a question flows (both channels, one function):

    CC  POST /api/v2/cio/ask ─┐                                  ┌─ Telegram long-poll (cio_telegram_bot)
                              ▼                                  ▼
            cio_converse_core.process_operator_message(channel="cc" | "telegram", ask_options=...)
                 │  begin_turn  — thread (new / follow-up by thr_ id, reply, or explicit), entities, quantities, recall
                 │  desk loop   — handle_operator_desk_question (unchanged: intent → Trade-AI facts → grounded answer)
                 │  compose     — MBI guard, recall block, sizing context (operator-named quantities only), tracking
                 │  _prepare_reply (Sources, authority tail) → send
                 └  finish_turn — ledger events + CIO memory (spine, keyed by security_guid) + channel link

Because both channels pass through ``process_operator_message`` and ``compose`` is pure given the same facts, the
answer text is identical on CC and Telegram. Threads cross-link: the footer names the thread id; a Telegram reply to
any message of a thread, or any message naming ``thr_…``, is a follow-up in that thread; a CC ask is mirrored to
Telegram when ``mirror_cc_to_telegram`` is on.

Deep path (Phase 9): ``request_deep`` reserves budget through the cost gate and calls
``DEEP_RESEARCH_ENTRYPOINT``; until that module lands (or while the cap awaits approval) the thread shows
``deep_pending`` / ``capped`` and says why.

Never sizes, orders, stops or weights. Model text proposing any of those is stripped and the strip recorded.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.cio_ask_contract import (
    AskAnswer,
    AskRequest,
    AskResearchContext,
    Confidence,
    DEEP_RESEARCH_ENTRYPOINT,
    EntityRef,
    NamedQuantity,
    ResearchBudget,
    SizingContextRow,
    Source,
    make_thread_id,
    mbi_guard_payload,
    mbi_guard_text,
    parse_named_quantities,
    private_entity_guid,
    research_context_for_model,
    utc_now_iso,
    validate_answer,
)
from scripts.lib.cio_ask_memory import SpineAskMemory, format_recall
from scripts.lib.cio_ask_store import AskEventStore, event_id_for

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "cio_ask.json"
THREAD_RE = re.compile(r"\bthr_([0-9a-f]{16})\b")
DEEP_RE = re.compile(
    r"\b(go\s+deeper|deep\s+(?:research|dive|answer)|research\s+(?:this|it)\s+(?:deeply|in\s+depth|fully)"
    r"|full\s+prospectus)\b",
    re.I,
)
OPERATOR_STOP_RE = re.compile(r"\bstop\s+(?:at|of|near|around)\s+\$?(\d+(?:\.\d+)?)", re.I)


from scripts.lib.cio_ask_runtime import load_config as load_config


# ── dependencies (injectable; tests pass fakes) ────────────────────────────────────────────────────────────────────


from scripts.lib.cio_ask_runtime import CostGate as CostGate


def _global_cap_check(process_id: str, projected_usd: float) -> dict:
    from scripts.lib.llm_consumption import check_cost_cap
    return check_cost_cap(process_id, projected_usd=projected_usd)


class DefaultSizingFacts:
    """House facts for sizing context. Read-only; every miss is a named gap, never a zero."""

    def price(self, symbol: str) -> tuple[Optional[float], Optional[str]]:
        from scripts.lib.cio_operator_desk_loop import subject_price_facts  # noqa: PLC0415

        p = (subject_price_facts([symbol]) or {}).get(symbol.upper()) or {}
        return (float(p["close"]) if p.get("close") is not None else None, p.get("price_date"))

    def portfolio(self) -> tuple[Optional[float], Optional[str]]:
        from scripts.lib import portfolio_positions as pp  # noqa: PLC0415

        doc = pp.load_store(None) or {}
        tv = (doc.get("portfolio_totals") or {}).get("total_value")
        return (float(tv) if tv else None, doc.get("as_of") or doc.get("data_as_of"))

    def position_value(self, symbol: str) -> Optional[float]:
        from scripts.lib.data_broker.positions_context import get_positions_context  # noqa: PLC0415

        ctx = get_positions_context(lambda *a, **k: [], [symbol]).get(symbol.upper()) or {}
        return float(ctx["market_value"]) if ctx.get("market_value") is not None else 0.0

    def concentration_limit(self, cfg: dict) -> tuple[Optional[float], str]:
        ref = str((cfg.get("sizing") or {}).get("concentration_limit_path") or "")
        path, _, key = ref.partition("#")
        try:
            node: Any = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
            for k in key.split("."):
                node = node[k]
            return float(node), ref
        except Exception:  # noqa: BLE001
            return None, f"{ref} (unreadable)"


class DefaultResolver:
    """Entities named in the question: the shared operator subject resolver (registry-bound, never guesses)."""

    def __call__(self, text: str) -> list[EntityRef]:
        from scripts.lib.operator_subject_resolver import resolve_subjects  # noqa: PLC0415

        out: list[EntityRef] = []
        for s in resolve_subjects(text) or []:
            kind = s.get("kind")
            if s.get("symbol") and s.get("guid"):
                out.append(
                    EntityRef(
                        name=str(s.get("matched") or s["symbol"]),
                        symbol=str(s["symbol"]).upper(),
                        security_guid=str(s["guid"]),
                        issuer_guid=s.get("issuer_guid"),
                        kind="security",
                        resolution="CONFIRMED",
                    )
                )
            elif kind == "company" and s.get("matched"):
                name = str(s["matched"])
                out.append(
                    EntityRef(
                        name=name,
                        kind="private_entity",
                        entity_guid=private_entity_guid(name),
                        resolution="UNRESOLVED_PRIVATE",
                        note="no listed security in the instrument feed — tracked by name",
                    )
                )
        return out


from scripts.lib.cio_ask_runtime import _default_notification_enqueue as _default_telegram_send


from scripts.lib.cio_ask_runtime import _default_delivery_read as _default_delivery_read


from scripts.lib.cio_ask_runtime import _default_deep_provider as _default_deep_provider


from scripts.lib.cio_ask_runtime import AskDeps as AskDeps


_DEPS_OVERRIDE: Optional[AskDeps] = None


def set_deps(deps: Optional[AskDeps]) -> None:
    """Tests install fakes here; None restores the defaults."""
    global _DEPS_OVERRIDE
    _DEPS_OVERRIDE = deps


def default_deps() -> AskDeps:
    from scripts.lib.cio_ask_tracking import DirectiveBackend, Tracker  # noqa: PLC0415

    cfg = load_config()
    store = AskEventStore()
    if not store.write_authorized():
        cfg = {**cfg, "enabled": False, "_error": "CIO_ASK_STORE_NOT_APPROVED"}
    at = cfg.get("auto_track") or {}
    return AskDeps(
        store=store,
        memory=SpineAskMemory(ledger=store),
        tracker=Tracker(
            directives=DirectiveBackend(ttl_days=int(at.get("directive_ttl_days") or 90)),
            enabled_steps={k: bool(at.get(k, True)) for k in ("watchlist", "cio_record", "directive")},
        ),
        resolver=DefaultResolver(),
        sizing=DefaultSizingFacts(),
        cost=CostGate(cfg, store, _global_cap_check),
        config=cfg,
        deep_provider=_default_deep_provider(),
        telegram_send=_default_telegram_send,
        notification_enqueue=_default_telegram_send,
        delivery_read=_default_delivery_read,
    )


def _deps(deps: Optional[AskDeps]) -> Optional[AskDeps]:
    if deps is not None:
        return deps
    if _DEPS_OVERRIDE is not None:
        return _DEPS_OVERRIDE
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("CIO_ASK_DEFAULT_DEPS_UNDER_TEST") != "1":
        return None  # §24.6: tests never touch production state; a test that wants the ask path injects fakes
    return default_deps()


# ── the turn ───────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class AskTurn:
    request: AskRequest
    thread_id: str
    turn_kind: str  # ask | follow_up | reanswer
    entities: list[EntityRef]
    quantities: list[NamedQuantity]
    recall: dict[str, list[dict]] = field(default_factory=dict)
    deep_requested: bool = False
    tracking: dict[str, dict] = field(default_factory=dict)
    sizing: list[SizingContextRow] = field(default_factory=list)
    mbi_findings: list[dict] = field(default_factory=list)
    trigger: Optional[dict] = None
    what_changed: Optional[str] = None

    @property
    def ask_id(self) -> str:
        return self.request.ask_id

    @property
    def symbols(self) -> list[str]:
        return [e.symbol for e in self.entities if e.symbol]


def _thread_entities(store: AskEventStore, thread_id: str) -> list[EntityRef]:
    t = store.thread(thread_id) or {}
    out = []
    for e in t.get("entities") or []:
        try:
            out.append(EntityRef.from_dict(e))
        except TypeError:
            continue
    return out


def _find_thread(store: AskEventStore, text: str) -> Optional[str]:
    for m in THREAD_RE.finditer(text or ""):
        tid = "thr_" + m.group(1)
        if store.thread(tid):
            return tid
    return None


def begin_turn(
    *,
    channel: str,
    chat_id: str,
    message_id: str,
    text: str,
    reply_to_message_id: Optional[str] = None,
    reply_to_text: Optional[str] = None,
    options: Optional[dict] = None,
    deps: Optional[AskDeps] = None,
) -> Optional[AskTurn]:
    """Resolve thread, entities, quantities and recall. Writes nothing."""
    d = _deps(deps or (options or {}).get("deps"))
    if d is None or not d.config.get("enabled"):
        return None
    if channel in ("telegram", "whatsapp") and not d.config.get("telegram_hook", True):
        return None
    opts = options or {}
    store = d.store
    thread_id = opts.get("thread_id") or None
    if thread_id and not store.thread(thread_id):
        thread_id = None  # unknown id → a new thread, never a silent attach to nothing
    if not thread_id:
        thread_id = _find_thread(store, text) or _find_thread(store, reply_to_text or "")
    if not thread_id and reply_to_message_id:
        thread_id = store.thread_for_channel_message(channel, chat_id, str(reply_to_message_id))
    turn_kind = opts.get("turn_kind") or ("follow_up" if thread_id else "ask")
    question = THREAD_RE.sub("", text or "").strip() or text
    req = AskRequest(
        question=question,
        channel=channel if channel in ("cc", "telegram", "whatsapp", "event") else "cc",
        source_ref=str(message_id),
        depth=str(opts.get("depth") or "quick"),
        thread_id=thread_id,
        chat_id=str(chat_id),
        trigger=opts.get("trigger"),
    )
    if not thread_id:
        thread_id = make_thread_id(req.ask_id)
        req.thread_id = None
    else:
        t = store.thread(thread_id) or {}
        turns = t.get("turns") or []
        req.parent_ask_id = turns[-1]["ask_id"] if turns else None
    try:
        entities = d.resolver(question) or []
    except Exception:  # noqa: BLE001
        entities = []
    if turn_kind != "ask":
        known = _thread_entities(store, thread_id)
        keys = {e.memory_key for e in entities}
        entities = entities + [e for e in known if e.memory_key not in keys]
    req.entities = entities
    quantities = parse_named_quantities(question, [e.symbol for e in entities if e.symbol])
    req.named_quantities = quantities
    recall: dict[str, list[dict]] = {}
    max_items = int((d.config.get("recall") or {}).get("max_items") or 4)
    for e in entities:
        try:
            items = d.memory.recall(entity=e, limit=max_items, exclude_refs=(req.ask_id,))
        except Exception:  # noqa: BLE001
            items = []
        if items:
            recall[e.memory_key or e.name] = items
    return AskTurn(
        request=req,
        thread_id=thread_id,
        turn_kind=turn_kind,
        entities=entities,
        quantities=quantities,
        recall=recall,
        deep_requested=(req.depth == "deep" or bool(DEEP_RE.search(question))),
        trigger=opts.get("trigger"),
        what_changed=opts.get("what_changed"),
    )


# ── sizing context (operator-named quantities only) ────────────────────────────────────────────────────────────────


def compute_sizing(
    quantities: list[NamedQuantity], entities: list[EntityRef], facts: Any, cfg: dict, *, question: str = ""
) -> list[SizingContextRow]:
    if not quantities:
        return []
    by_sym = {e.symbol: e for e in entities if e.symbol}
    ref_pct = float((cfg.get("sizing") or {}).get("reference_stop_pct") or 8.0)
    m = OPERATOR_STOP_RE.search(question or "")
    operator_stop = float(m.group(1)) if m else None
    rows: list[SizingContextRow] = []
    port, port_as_of = _try(lambda: facts.portfolio(), (None, None))
    limit, limit_src = _try(lambda: facts.concentration_limit(cfg), (None, "unavailable"))
    for q in quantities:
        gaps: list[str] = []
        price, price_as_of = _try(lambda: facts.price(q.symbol), (None, None))
        existing = _try(lambda: facts.position_value(q.symbol), None)
        if price is None:
            gaps.append("no price on record")
        if not port:
            gaps.append("portfolio value unavailable")
        exposure = (q.amount * price if q.unit == "shares" else q.amount) if (price or q.unit == "usd") else None
        pct = round(exposure / port * 100, 2) if exposure is not None and port else None
        combined = round((exposure + (existing or 0)) / port * 100, 2) if exposure is not None and port else None
        stop_px, basis = None, None
        if price is not None:
            if operator_stop is not None and operator_stop < price:
                stop_px, basis = operator_stop, "operator-named"
            else:
                stop_px, basis = (
                    round(price * (1 - ref_pct / 100), 2),
                    f"reference {ref_pct:g}% below price (illustrative)",
                )
        loss = round(exposure * (1 - stop_px / price), 2) if exposure is not None and stop_px and price else None
        rows.append(
            SizingContextRow(
                symbol=q.symbol,
                security_guid=(by_sym.get(q.symbol).security_guid if by_sym.get(q.symbol) else None),
                operator_amount=q.amount,
                operator_unit=q.unit,
                reference_price=price,
                price_as_of=price_as_of,
                exposure_usd=round(exposure, 2) if exposure is not None else None,
                pct_of_portfolio=pct,
                existing_exposure_usd=existing,
                combined_pct_of_portfolio=combined,
                concentration_limit_pct=limit,
                concentration_limit_source=limit_src,
                over_concentration_limit=(combined > limit) if combined is not None and limit is not None else None,
                reference_stop_price=stop_px,
                reference_stop_basis=basis,
                loss_at_reference_usd=loss,
                loss_at_reference_pct_of_portfolio=round(loss / port * 100, 3) if loss is not None and port else None,
                portfolio_value_usd=port,
                portfolio_as_of=port_as_of,
                gaps=gaps,
            )
        )
    return rows


def _try(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def _usd(v: Optional[float]) -> str:
    return "n/a" if v is None else f"${v:,.0f}"


def format_sizing(rows: list[SizingContextRow]) -> str:
    if not rows:
        return ""
    lines = ["Sizing context — the quantities you named (exposure and risk, not a recommendation):"]
    for r in rows:
        amt = (
            f"{r.operator_amount:,.0f} {r.symbol}"
            if r.operator_unit == "shares"
            else f"${r.operator_amount:,.0f} of {r.symbol}"
        )
        bits = [f"≈ {_usd(r.exposure_usd)}"]
        if r.pct_of_portfolio is not None:
            bits.append(f"{r.pct_of_portfolio:.1f}% of portfolio")
        if r.combined_pct_of_portfolio is not None and r.existing_exposure_usd:
            bits.append(f"{r.combined_pct_of_portfolio:.1f}% with what you hold")
        if r.over_concentration_limit:
            bits.append(f"over the {r.concentration_limit_pct:g}% single-position limit")
        elif r.concentration_limit_pct is not None and r.combined_pct_of_portfolio is not None:
            bits.append(f"within the {r.concentration_limit_pct:g}% limit")
        if r.loss_at_reference_usd is not None:
            bits.append(
                f"loss at {r.reference_stop_basis} stop (${r.reference_stop_price:,.2f}) ≈ "
                f"{_usd(r.loss_at_reference_usd)}"
                + (
                    f" ({r.loss_at_reference_pct_of_portfolio:.2f}%)"
                    if r.loss_at_reference_pct_of_portfolio is not None
                    else ""
                )
            )
        if r.gaps:
            bits.append("gaps: " + ", ".join(r.gaps))
        lines.append(f"- {amt}: " + " · ".join(bits))
    return "\n".join(lines)


# ── compose / finish ───────────────────────────────────────────────────────────────────────────────────────────────


def _insert_before_tail(text: str, block: str) -> str:
    try:
        from scripts.lib.cio_operator_desk_loop import _insert_before_authority_tail  # noqa: PLC0415

        return _insert_before_authority_tail(text, block)
    except Exception:  # noqa: BLE001
        return (text.rstrip() + "\n\n" + block).strip()


def _tracking_line(turn: AskTurn) -> str:
    bits = []
    for e in turn.entities:
        tr = turn.tracking.get(e.memory_key or e.name) or {}
        if not tr:
            continue
        label = e.symbol or e.name
        acts = []
        if (tr.get("watchlist") or {}).get("action") in ("added", "tagged_existing"):
            acts.append("My Watchlist")
        if (tr.get("directive") or {}).get("action") in ("created", "reused"):
            acts.append("catalyst watch")
        if (tr.get("cio_record") or {}).get("action") in ("created", "updated", "unchanged"):
            acts.append("CIO record")
        if acts:
            bits.append(f"{label} → " + ", ".join(acts))
    return ("Tracking: " + "; ".join(bits)) if bits else ""


def footer(turn: AskTurn) -> str:
    return f"Thread {turn.thread_id} · reply here or open My questions in the Command Center to follow up."


def compose(turn: AskTurn, desk_text: str, *, dry_run: bool = False, deps: Optional[AskDeps] = None) -> str:
    """The operator-facing answer. Same inputs → same text on every channel."""
    d = _deps(deps)
    clean, findings = mbi_guard_text(desk_text or "")
    turn.mbi_findings = findings
    blocks: list[str] = []
    if turn.what_changed:
        blocks.append("What changed: " + turn.what_changed)
    for e in turn.entities:
        r = format_recall(
            e,
            turn.recall.get(e.memory_key or e.name) or [],
            max_items=int(((d.config if d else {}).get("recall") or {}).get("max_items") or 4),
        )
        if r:
            blocks.append(r)
    if d is not None:
        turn.sizing = compute_sizing(turn.quantities, turn.entities, d.sizing, d.config, question=turn.request.question)
        if not dry_run:
            auto_track(turn, deps=d)
    s = format_sizing(turn.sizing)
    if s:
        blocks.append(s)
    t = _tracking_line(turn)
    if t:
        blocks.append(t)
    if turn.deep_requested:
        blocks.append("Deep research requested — the prospectus (3/6/12 months) follows in this thread.")
    blocks.append(footer(turn))
    return _insert_before_tail(clean, "\n\n".join(blocks))


def auto_track(turn: AskTurn, *, deps: Optional[AskDeps] = None) -> None:
    """Phase 10: track each entity once per thread. An entity the operator untracked stays untracked."""
    d = _deps(deps)
    if d is None or not (d.config.get("auto_track") or {}).get("enabled", True):
        return
    thread = d.store.thread(turn.thread_id) or {}
    states = {e.get("key"): (e.get("tracking") or {}) for e in thread.get("entities") or []}
    for e in turn.entities:
        key = e.memory_key or f"name:{e.name}"
        if (states.get(key) or {}).get("state") in ("tracked", "untracked"):
            turn.tracking[e.memory_key or e.name] = states[key].get("actions") or {}
            continue
        actions = d.tracker.track(
            e,
            question=turn.request.question,
            ask_id=turn.ask_id,
            thread_id=turn.thread_id,
            channel=turn.request.channel,
        )
        turn.tracking[e.memory_key or e.name] = actions
        d.store.append(
            "ask.tracking_changed",
            {
                "thread_id": turn.thread_id,
                "entity_key": key,
                "name": e.name,
                "symbol": e.symbol,
                "state": "tracked",
                "actions": actions,
                "by": "auto",
            },
            event_id=event_id_for("ask.tracking_changed", turn.thread_id, key, "tracked"),
        )
        _remember(d, e, "ask.tracking_changed", f"tracked from question: {turn.request.question}", turn.ask_id)


from scripts.lib.cio_ask_runtime import _remember as _remember


def finish_turn(
    turn: AskTurn,
    *,
    final_text: str,
    provenance: Optional[dict] = None,
    outbound_message_id: Any = None,
    dry_run: bool = False,
    status: Optional[str] = None,
    deps: Optional[AskDeps] = None,
    cost_usd: float = 0.0,
) -> Optional[AskAnswer]:
    """Append the ask, its entities, the answer version and memory. Idempotent per (ask_id, version)."""
    d = _deps(deps)
    if d is None or dry_run:
        return None
    st = d.store
    req = turn.request
    _, created = st.append(
        "ask.asked",
        {
            "thread_id": turn.thread_id,
            "ask_id": req.ask_id,
            "question": req.question,
            "channel": req.channel,
            "source_ref": req.source_ref,
            "chat_id": req.chat_id,
            "asked_at": req.asked_at,
            "parent_ask_id": req.parent_ask_id,
            "turn_kind": turn.turn_kind,
            "trigger": turn.trigger,
            "named_quantities": [q.to_dict() for q in req.named_quantities],
        },
        event_id=event_id_for("ask.asked", req.ask_id),
    )
    for e in turn.entities:
        st.append(
            "ask.entity_resolved",
            {"thread_id": turn.thread_id, "ask_id": req.ask_id, "entity": e.to_dict()},
            event_id=event_id_for("ask.entity_resolved", req.ask_id, e.memory_key or e.name),
        )
    if outbound_message_id not in (None, "") and req.chat_id:
        link_channel(
            st,
            thread_id=turn.thread_id,
            channel=req.channel if req.channel != "event" else "telegram",
            chat_id=req.chat_id,
            message_id=outbound_message_id,
        )
    if req.channel in ("telegram", "whatsapp") and req.chat_id:
        link_channel(st, thread_id=turn.thread_id, channel=req.channel, chat_id=req.chat_id, message_id=req.source_ref)
    prior = _latest_answer_for_ask(st, req.ask_id)
    if prior is not None and not created:
        return prior  # the same inbound message processed twice: one answer
    sources = _sources_from_provenance(provenance, turn)
    ans = AskAnswer(
        ask_id=req.ask_id,
        thread_id=turn.thread_id,
        version=st.next_version(req.ask_id),
        depth="quick",
        status=status or ("reanswer" if turn.turn_kind == "reanswer" else "quick"),
        summary=final_text,
        entities=turn.entities,
        sizing_context=turn.sizing,
        sources=sources,
        confidence=Confidence(
            level="low" if not sources else "medium", rationale="desk-loop answer grounded in Trade-AI house facts"
        ),
        recall=[{"key": k, "items": v} for k, v in turn.recall.items()],
        what_changed=turn.what_changed,
        trigger=turn.trigger,
        mbi_guard={"stripped": len(turn.mbi_findings), "findings": turn.mbi_findings},
        cost_usd=cost_usd,
        provenance=provenance or {},
    )
    record_answer(ans, turn=turn, deps=d)
    return ans


def record_answer(ans: AskAnswer, *, turn: Optional[AskTurn] = None, deps: Optional[AskDeps] = None) -> None:
    from scripts.lib.cio_ask_runtime import record_answer as shared_record_answer
    shared_record_answer(ans, turn=turn, deps=_deps(deps))


from scripts.lib.cio_ask_runtime import _plain as _plain


def _latest_answer_for_ask(store: AskEventStore, ask_id: str) -> Optional[AskAnswer]:
    evs = [e for e in store.events() if e.get("kind") == "ask.answer_version" and e.get("ask_id") == ask_id]
    if not evs:
        return None
    try:
        return AskAnswer.from_dict(max(evs, key=lambda e: int(e.get("version") or 0))["answer"])
    except Exception:  # noqa: BLE001
        return None


def _sources_from_provenance(prov: Optional[dict], turn: AskTurn) -> list[Source]:
    out: list[Source] = []
    now = utc_now_iso()
    for s in (prov or {}).get("stores_read") or []:
        out.append(Source(title=str(s)[:200], kind="house_store", as_of=now))
    for c in (prov or {}).get("citations") or []:
        if isinstance(c, dict):
            out.append(
                Source(
                    title=str(c.get("title") or c.get("label") or c.get("url") or "citation")[:200],
                    kind=str(c.get("kind") or "web"),
                    url=c.get("url"),
                    as_of=str(c.get("as_of") or c.get("date") or now),
                )
            )
    return out[:20]


from scripts.lib.cio_ask_runtime import link_channel as link_channel


# ── CC entry point ─────────────────────────────────────────────────────────────────────────────────────────────────


def cc_chat_id() -> str:
    """CC asks share the operator's CIO chat id so desk memory and pending replies are one conversation."""
    try:
        from scripts.lib.cio_telegram_converse import allowlist_chat_ids  # noqa: PLC0415

        chats = sorted(allowlist_chat_ids() or [])
        if chats:
            return str(chats[0])
    except Exception:  # noqa: BLE001
        pass
    return "cc:operator"


def ask_from_cc(
    question: str,
    *,
    request_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    depth: str = "quick",
    deps: Optional[AskDeps] = None,
    chat_id: Optional[str] = None,
    converse: Optional[Callable[..., dict]] = None,
) -> dict[str, Any]:
    """Ask from the Command Center. Same function the Telegram path uses, so the answer is identical."""
    d = _deps(deps)
    if d is None or not d.config.get("enabled"):
        return {"ok": False, "error": "ASK_DISABLED"}
    q = str(question or "").strip()
    max_chars = int(d.config.get("max_question_chars") or 2000)
    if not q:
        return {"ok": False, "error": "QUESTION_EMPTY"}
    if len(q) > max_chars:
        return {"ok": False, "error": "QUESTION_TOO_LONG", "max_chars": max_chars}
    if depth not in ("quick", "deep"):
        depth = "quick"
    rid = str(request_id or ("cc_" + uuid.uuid4().hex[:16]))
    cid = chat_id or cc_chat_id()
    captured: dict[str, Any] = {}

    def _capture(_cid: str, body: str, reply_to: Optional[str] = None) -> dict:
        captured["text"] = body
        return {"ok": True, "message_id": None}

    if converse is None:
        from scripts.lib.cio_converse_core import process_operator_message as converse  # noqa: PLC0415
    out = converse(
        channel="cc",
        chat_id=cid,
        message_id=rid,
        text=q,
        allowlist={cid},
        converse_on=True,
        send_fn=_capture,
        ask_options={"thread_id": thread_id, "depth": depth, "deps": d, "defer_deep": True},
    )
    text = captured.get("text") or out.get("reply_preview") or ""
    ask = out.get("ask") or {}
    if not ask.get("ask_id"):
        # Answered by a branch outside the desk loop (attention, rate limit…): still the operator's question.
        turn = begin_turn(
            channel="cc", chat_id=cid, message_id=rid, text=q, options={"thread_id": thread_id, "depth": depth}, deps=d
        )
        if turn is not None:
            text = compose(turn, text, deps=d)
            a = finish_turn(turn, final_text=text, provenance=out.get("reply_provenance"), deps=d)
            ask = {
                "ask_id": turn.ask_id,
                "thread_id": turn.thread_id,
                "version": a.version if a else None,
                "deep_requested": turn.deep_requested,
            }
    tid = ask.get("thread_id")
    if tid and d.config.get("mirror_cc_to_telegram") and d.telegram_send and text:
        try:
            res = d.telegram_send(f"Asked in the Command Center: {q}\n\n{text}") or {}
            if res.get("message_id") is not None:
                link_channel(d.store, thread_id=tid, channel="telegram", chat_id=cid, message_id=res["message_id"])
        except Exception:  # noqa: BLE001
            pass
    if tid and ask.get("deep_requested"):
        request_deep(tid, ask["ask_id"], deps=d)  # after the quick answer is recorded and mirrored
    return {
        "ok": True,
        "ask_id": ask.get("ask_id"),
        "thread_id": tid,
        "answer_text": text,
        "thread": d.store.thread(tid) if tid else None,
        "converse_kind": out.get("kind"),
    }


# ── deep path (Phase 9 hand-off) ───────────────────────────────────────────────────────────────────────────────────


def request_deep(thread_id: str, ask_id: str, *, deps: Optional[AskDeps] = None,
                 request_id: Optional[str] = None) -> dict[str, Any]:
    """Genuine operator request; scheduled checks use their own admitted lifecycle entry."""
    d = _deps(deps)
    if d is None:
        return {"ok": False, "error": "ASK_DISABLED"}
    from scripts.lib.cio_ask_lifecycle import request_deep as execute

    return execute(thread_id, ask_id, deps=d, request_id=request_id, automated=False)


def sync_answer_memory(ans: AskAnswer, *, deps: Optional[AskDeps] = None) -> dict:
    from scripts.lib.cio_ask_runtime import sync_answer_memory as shared_sync
    return shared_sync(ans, deps=_deps(deps))


def _post_to_telegram(d: AskDeps, thread_id: str, text: str) -> dict:
    if not d.telegram_send:
        return {"state": "not_configured", "reason": "NO_CHANNEL_TARGET"}
    has_tg = any(x.get("channel") == "telegram" for x in d.store.channel_links(thread_id))
    if not (has_tg or d.config.get("mirror_cc_to_telegram")):
        return {"state": "not_required", "reason": "NO_CHANNEL_TARGET"}
    try:
        res = d.telegram_send(f"{text}\n\nThread {thread_id}") or {}
        if res.get("message_id") is not None:
            link_channel(
                d.store,
                thread_id=thread_id,
                channel="telegram",
                chat_id=str(
                    res.get("chat_id")
                    or next(
                        (
                            r.get("chat_id")
                            for r in reversed(d.store.channel_links(thread_id))
                            if r.get("channel") == "telegram"
                        ),
                        "cc:operator",
                    )
                ),
                message_id=res["message_id"],
            )
            return {"state": "delivered", "ref": str(res["message_id"])}
        if res.get("ok") is True and res.get("queued"):
            return {"state": "queued", "ref": str(res["queued"])}
        return {"state": "failed", "reason": "DELIVERY_NOT_ACKNOWLEDGED"}
    except Exception as exc:  # noqa: BLE001
        return {"state": "failed", "reason": "DELIVERY_FAILED:" + type(exc).__name__}


# ── untrack ────────────────────────────────────────────────────────────────────────────────────────────────────────


def untrack(thread_id: str, entity_key: str, *, deps: Optional[AskDeps] = None, by: str = "operator") -> dict:
    d = _deps(deps)
    if d is None:
        return {"ok": False, "error": "ASK_DISABLED"}
    t = d.store.thread(thread_id)
    if not t:
        return {"ok": False, "error": "THREAD_NOT_FOUND"}
    ent = next((e for e in t["entities"] if e.get("key") == entity_key), None)
    if not ent:
        return {"ok": False, "error": "ENTITY_NOT_IN_THREAD"}
    tr = ent.get("tracking") or {}
    if tr.get("state") == "untracked":
        return {"ok": True, "already": True, "thread": t}
    actions = d.tracker.untrack(ent, thread_id=thread_id, prior_actions=tr.get("actions") or {})
    d.store.append(
        "ask.tracking_changed",
        {
            "thread_id": thread_id,
            "entity_key": entity_key,
            "name": ent.get("name"),
            "symbol": ent.get("symbol"),
            "state": "untracked",
            "actions": actions,
            "by": by,
        },
        event_id=event_id_for("ask.tracking_changed", thread_id, entity_key, "untracked"),
    )
    try:
        _remember(d, EntityRef.from_dict(ent), "ask.tracking_changed", f"untracked by {by} ({thread_id})", thread_id)
    except TypeError:
        pass
    return {"ok": True, "actions": actions, "thread": d.store.thread(thread_id)}


# ── list projection for the page ───────────────────────────────────────────────────────────────────────────────────


def list_threads(*, deps: Optional[AskDeps] = None, limit: int = 50) -> list[dict[str, Any]]:
    d = _deps(deps)
    if d is None:
        return []
    rows = []
    for t in d.store.threads().values():
        last = None
        for turn in t["turns"]:
            for a in turn["answers"]:
                last = a
        rows.append(
            {
                "thread_id": t["thread_id"],
                "title": t["title"],
                "created_at": t["created_at"],
                "updated_at": t["updated_at"],
                "status": t["status"],
                "channels": t["channels"],
                "turns": len(t["turns"]),
                "reanswers": t["reanswers"],
                "lifecycle": t.get("lifecycle"),
                "entities": [
                    {
                        "key": e.get("key"),
                        "name": e.get("name"),
                        "symbol": e.get("symbol"),
                        "kind": e.get("kind"),
                        "tracking": (e.get("tracking") or {}).get("state"),
                    }
                    for e in t["entities"]
                ],
                "last_answer_excerpt": _plain((last or {}).get("summary") or "", 220),
            }
        )
    rows.sort(key=lambda r: str(r["updated_at"] or ""), reverse=True)
    return rows[: max(1, min(int(limit or 50), 500))]


__all__ = [
    "AskDeps",
    "AskTurn",
    "CostGate",
    "set_deps",
    "default_deps",
    "load_config",
    "begin_turn",
    "compose",
    "finish_turn",
    "record_answer",
    "auto_track",
    "compute_sizing",
    "format_sizing",
    "ask_from_cc",
    "request_deep",
    "untrack",
    "list_threads",
    "link_channel",
    "cc_chat_id",
    "footer",
]
