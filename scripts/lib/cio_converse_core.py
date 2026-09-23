"""CIO multi-channel converse core — READ_ONLY_ADVISORY.

Shared free-text / command / plan continuity path used by Telegram and WhatsApp.
Transport (ingress/egress) stays outside this module.

No broker/order/stop/2FA authority.
"""
from __future__ import annotations

import hashlib
import inspect as _inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Reuse telegram helpers for parse/format/context (single source of truth)
from scripts.lib.cio_telegram_converse import (
    ACK_RE,
    DEFAULT_DEDUP,
    DEFAULT_MSG_MAP,
    DEFAULT_RATE,
    answer_reentry_purchase_query,
    emit_operator_message,
    format_reentry_purchase_reply,
    format_structured_reply,
    handle_cio_slash,
    looks_like_reentry_purchase_query,
    mark_message_seen,
    mark_wake_rate,
    message_seen,
    parse_ids_from_text,
    parse_reply_footer,
    plan_id_for_reply_message,
    rate_limit_ok,
    format_decision_thread_reply,
    load_decision_thread_context,
    record_decision_thread_note,
    _now,
)
from scripts.lib.cio_operator_desk_loop import handle_operator_desk_question
from scripts.lib.reply_provenance import (
    ROLE_WORDING_ONLY,
    ReplyProvenance,
    finalize_operator_reply,
    provenance_for_desk,
)


SendFn = Callable[..., dict[str, Any]]

# Plain-text command prefixes accepted on WhatsApp (no leading /cio required)
PLAIN_CMD_RE = re.compile(
    r"^\s*(?:/cio\s+)?(help|plans|plan|thesis|traces|status|actions|portfolio|hermes|risk|"
    r"reentry|re-entry|ack|rate|defer|done|reject)\b",
    re.I,
)


def format_reply_for_channel(
    *,
    channel: str,
    summary: str,
    evidence_refs: Optional[list[dict[str, Any]]] = None,
    options: Optional[list[dict[str, Any]]] = None,
    recommendation: str = "",
    risks: Optional[list[str]] = None,
    plan_id: Optional[str] = None,
    goal_id: Optional[str] = None,
    action_id: Optional[str] = None,
    revisit_at: Optional[str] = None,
    thesis_version: Optional[str] = None,
    situation_type: Optional[str] = None,
    llm_deferred: bool = False,
    deep_links: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
    thesis_alignment: Optional[str] = None,
    multi_domain_summary: Optional[str] = None,
) -> str:
    """Shared structured formatter; WhatsApp gets plain-text friendly body."""
    text = format_structured_reply(
        summary=summary,
        evidence_refs=evidence_refs,
        options=options,
        recommendation=recommendation,
        risks=risks,
        plan_id=plan_id,
        goal_id=goal_id,
        action_id=action_id,
        revisit_at=revisit_at,
        thesis_version=thesis_version,
        situation_type=situation_type,
        llm_deferred=llm_deferred,
        deep_links=deep_links,
        symbols=symbols,
        thesis_alignment=thesis_alignment,
        multi_domain_summary=multi_domain_summary,
    )
    if (channel or "").lower() == "whatsapp":
        # Plain-text friendly: drop markdown markers without eating plan_id underscores
        text = text.replace("`", "")
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        # Only strip whole-line italic (_line_) not mid-token underscores
        lines_out = []
        for ln in text.split("\n"):
            s = ln.strip()
            if len(s) >= 2 and s.startswith("_") and s.endswith("_") and s.count("_") == 2:
                ln = ln.replace(s, s[1:-1], 1)
            lines_out.append(ln)
        text = "\n".join(lines_out)
        text = text.replace(
            "Reply to this message to continue · /cio ack",
            "Reply to this message to continue · text: ack",
        )
        # Honest WA command hint
        if "No orders/stops" in text:
            text = text.replace(
                "No orders/stops from chat. READ_ONLY_ADVISORY.",
                "Commands: plans | thesis | ack [plan_id] | status\n"
                "Full /cio slash set still available on Telegram.\n"
                "No orders/stops from chat. READ_ONLY_ADVISORY.",
            )
    return text


def _normalize_command_text(text: str) -> Optional[str]:
    """Map plain WA commands to /cio slash form. None if not a command."""
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith("/cio"):
        return raw
    # bare "cio plans" / "plans" / "thesis history"
    m = PLAIN_CMD_RE.match(raw)
    if not m:
        return None
    # already has /cio?
    if lower.startswith("/cio"):
        return raw
    # strip optional leading "cio "
    body = raw
    if lower.startswith("cio "):
        body = raw[4:].strip()
    return f"/cio {body}"


def _s0_route(text: str, plan_id: Optional[str]) -> dict:
    """Route one operator turn. Degrades to a bare marker, never raises.

    A converse wake must not fail because routing is unavailable — the operator
    said something, and losing that is worse than losing the enrichment.
    """
    try:
        from scripts.lib.cio_s0_operator_loop import route_turn

        return route_turn(text, plans=_open_plans_snapshot(), plan_id=plan_id)
    except Exception as exc:                                    # noqa: BLE001
        return {"action": "unrouted", "reason": str(exc)[:120],
                "authority": "READ_ONLY_ADVISORY"}


def _open_plans_snapshot() -> list:
    """Open plans for attach resolution. Empty list if unreadable."""
    try:
        import json as _json

        from maturity_control.store import resolve_root

        p = resolve_root() / "data" / "cio" / "cio_plans_projection.json"
        doc = _json.loads(p.read_text(encoding="utf-8"))
        return [v for v in (doc.get("plans") or {}).values()
                if isinstance(v, dict)]
    except Exception:
        return []


def enqueue_operator_wake_channel(
    *,
    chat_id: str,
    message_id: str,
    text: str,
    plan_id: Optional[str],
    goal_id: Optional[str],
    action_id: Optional[str],
    event_id: Optional[str],
    channel: str = "telegram",
    target_agent: str = "alex",
    actor_id: str = "cio_converse",
) -> Optional[str]:
    try:
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore
        store = CIOWakeJobStore()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        # Prefix channel so TG and WA message ids cannot collide
        mid_key = f"{channel}_{message_id}"
        wake_job_id = f"wake_op_{target_agent}_{mid_key}_{hour}"[:120]
        store.enqueue(
            {
                "wake_job_id": wake_job_id,
                "trigger_type": "OPERATOR_MESSAGE",
                "trigger_ref": str(message_id),
                "trigger_hash": hashlib.sha256(
                    f"{channel}:{chat_id}:{message_id}".encode()
                ).hexdigest()[:16],
                "reason_codes": ["OPERATOR_MESSAGE"],
                "required_domains": ["portfolio"],
                "wake_intent": "NEW_RUN",
                "idempotency_key": wake_job_id,
                "context": {
                    "target_agent": target_agent,
                    "channel": channel,
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "text": text[:2000],
                    "plan_id": plan_id,
                    "goal_id": goal_id,
                    "action_id": action_id,
                    "event_id": event_id,
                    "authority": "READ_ONLY_ADVISORY",
                    # S0 routing: extract the symbol, decide mint vs attach, and
                    # carry a stable turn id. Without this the wake arrives with
                    # bare text, the S0 plan is minted with symbols: [], and
                    # nothing downstream can load registry[symbol] — which is
                    # why the desk appeared to know only SCHD.
                    "s0": _s0_route(text, plan_id),
                },
            },
            actor_id=actor_id,
            actor_type="system",
            authority="READ_ONLY_ADVISORY",
        )
        return wake_job_id
    except Exception:
        return None


def _wa_plain(text: str) -> str:
    return re.sub(r"\*([^*]+)\*", r"\1", text).replace("`", "")


# ── reply provenance per path ────────────────────────────────────────────────
# Operator, 2026-09-13 19:05: "the routing should be internal Command Center
# first and when it has to go out for other stuff it needs to let us know".
# Each builder declares what ITS path actually read -- never what it might have.


def _attention_provenance(ans: dict[str, Any]) -> ReplyProvenance:
    label = f"office situation scan · decision {ans.get('reason') or 'unknown'}"
    if not ans.get("same_brain"):
        # answer_attention_query is called here without office= / envelope=, so
        # detect_office_situations runs on an EMPTY office. Say so; do not dress
        # it up as a read of the office state.
        label += " · no office state loaded (scan ran on an empty office)"
    return ReplyProvenance(kind="attention", stores_read=[label])


def _reentry_facts_provenance(ans: dict[str, Any]) -> ReplyProvenance:
    path = ans.get("desk_path")
    as_of = str(ans.get("as_of") or "")[:16].replace("T", " ")
    if path:
        stores = [Path(str(path)).name + (f" · computed {as_of}" if as_of else "")]
    else:
        stores = ["reentry_decision_desk_latest.json — not found on any candidate path"]
    prov = ReplyProvenance(kind="reentry_facts", stores_read=stores)
    if str(ans.get("source") or "") == "deepseek_flash":
        prov.model = ans.get("model") or "deepseek-flash"
        prov.model_role = ROLE_WORDING_ONLY
        prov.went_outside = [f"{prov.model} — {ROLE_WORDING_ONLY} (polish of the desk card)"]
    return prov


def _decision_thread_provenance(decision_id: str, thread: dict[str, Any]) -> ReplyProvenance:
    stores: list[str] = []
    if thread.get("catalog_error"):
        stores.append(f"decision catalog — unreadable ({thread.get('catalog_error')})")
    elif thread.get("symbol"):
        stores.append(f"decision catalog · {decision_id} · {thread.get('symbol')}")
    else:
        stores.append(f"decision catalog — no row for {decision_id}")
    if thread.get("disposition"):
        at = str(thread.get("disposition_at") or "")[:16].replace("T", " ")
        stores.append("operator dispositions" + (f" · recorded {at}" if at else ""))
    if thread.get("why_now") or thread.get("action_label"):
        stores.append("capital plan (position_decisions)")
    return ReplyProvenance(kind="decision_thread", stores_read=stores)


def process_operator_message(
    *,
    channel: str,
    chat_id: str,
    message_id: str | int,
    text: str,
    reply_to_message_id: Optional[str] = None,
    reply_to_text: Optional[str] = None,
    user_id: str = "",
    username: str = "",
    allowlist: set[str],
    converse_on: bool,
    dedup_path: Path = DEFAULT_DEDUP,
    msg_map_path: Path = DEFAULT_MSG_MAP,
    rate_path: Path = DEFAULT_RATE,
    dry_run: bool = False,
    send_fn: Optional[SendFn] = None,
    wakes_limit: Optional[int] = None,
    actor_id: str = "cio_converse",
) -> dict[str, Any]:
    """Channel-agnostic converse processor.

    send_fn(chat_id, text, reply_to=None) -> {ok, message_id?, error?}
    """
    out: dict[str, Any] = {
        "handled": False,
        "authority": "READ_ONLY_ADVISORY",
        "reason": "",
        "channel": channel,
    }
    chat_id = str(chat_id or "")
    message_id_s = str(message_id) if message_id is not None else ""
    text = (text or "").strip()

    if not text or not chat_id or not message_id_s:
        out["reason"] = "empty"
        return out

    if not allowlist or chat_id not in allowlist:
        out["reason"] = "not_allowlisted"
        return out

    # Dedup key includes channel so TG/WA ids do not collide
    dedup_key = f"{channel}:{message_id_s}"
    if message_seen(dedup_key, path=dedup_path):
        out["reason"] = "duplicate_message_id"
        return out

    cmd_text = _normalize_command_text(text)
    is_cmd = cmd_text is not None
    is_slash = text.lower().startswith("/cio") or (cmd_text is not None and text.lower().startswith("cio"))

    if not converse_on and not is_cmd:
        out["reason"] = "converse_disabled"
        return out

    if not dry_run:
        mark_message_seen(dedup_key, chat_id, path=dedup_path)

    # Whether send_fn takes reply_to is a property of the function, decided ONCE
    # here. It used to be discovered by calling with reply_to and catching
    # TypeError -- but a TypeError raised INSIDE the send is indistinguishable
    # from a signature mismatch, so the except branch re-called a function that
    # had already delivered. On 2026-09-13 the reply to the operator's Walmart
    # question was recorded twice (operator_conversation_turns id 133 and 134,
    # same chat, same message_id 51667). Never wrap a side-effecting call in a
    # retry that cannot tell "you called me wrong" from "I failed midway".
    try:
        _send_takes_reply_to = "reply_to" in _inspect.signature(send_fn).parameters
    except (TypeError, ValueError):
        _send_takes_reply_to = True  # unintrospectable: prefer the richer call

    def _send(body: str, reply_to: Optional[str] = None) -> dict[str, Any]:
        if dry_run or send_fn is None:
            return {"ok": True, "message_id": None, "dry_run": True}
        try:
            if _send_takes_reply_to:
                return send_fn(chat_id, body, reply_to=reply_to)  # type: ignore[call-arg]
            return send_fn(chat_id, body)  # type: ignore[misc]
        except Exception as exc:
            # Including TypeError. A failure is reported, never retried: the
            # message may already be on its way to the operator.
            return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

    def _prepare_reply(body: str, prov: ReplyProvenance) -> str:
        """THE chokepoint for operator replies. Nothing reaches `_send` on an
        operator-reply branch without passing here: Sources line, Went outside
        line when anything left the Command Center, authority tail last. The
        receipt lands on the result as `reply_provenance`."""
        final, prov = finalize_operator_reply(body, prov)
        if channel == "whatsapp":
            final = _wa_plain(final)
        out["reply_provenance"] = prov.to_dict()
        return final

    # Deterministic commands (slash or plain). Command output, not an answer:
    # outside the Sources contract (docs/OPERATOR_REPLY_ROUTING.md).
    if is_cmd and cmd_text:
        cmd_reply = handle_cio_slash(cmd_text)
        if channel == "whatsapp":
            cmd_reply = _wa_plain(cmd_reply)
        sent = _send(cmd_reply)
        out.update({
            "handled": True,
            "kind": "slash",
            "reply_preview": cmd_reply[:200],
            "telegram_out_message_id": sent.get("message_id"),
            "outbound_message_id": sent.get("message_id"),
        })
        return out

    # ack shortcut
    m_ack = ACK_RE.match(text)
    if m_ack:
        pid = m_ack.group(2)
        if not pid:
            pid = plan_id_for_reply_message(reply_to_message_id, path=msg_map_path)
            if not pid and reply_to_text:
                pid = parse_reply_footer(reply_to_text).get("plan_id")
        if pid:
            cmd_reply = handle_cio_slash(f"/cio ack {pid}")
            if channel == "whatsapp":
                cmd_reply = _wa_plain(cmd_reply)
            sent = _send(cmd_reply)
            out.update({
                "handled": True,
                "kind": "ack",
                "plan_id": pid,
                "outbound_message_id": sent.get("message_id"),
            })
            return out

    # Deterministic attention / "why nothing today" — same CIO brain, no hallucination.
    try:
        from scripts.lib.cio_operator_attention import answer_attention_query, looks_like_attention_query
        from scripts.lib.cio_operator_feedback_loop import ingest_operator_feedback, looks_like_feedback
    except Exception:
        looks_like_attention_query = None  # type: ignore[assignment]
        looks_like_feedback = None  # type: ignore[assignment]
        answer_attention_query = None  # type: ignore[assignment]
        ingest_operator_feedback = None  # type: ignore[assignment]

    if looks_like_feedback and looks_like_feedback(text) and ingest_operator_feedback:
        try:
            from pathlib import Path as _Path
            ingest_operator_feedback(text, root=_Path(__file__).resolve().parents[2], source=channel)
        except Exception:
            pass

    if looks_like_attention_query and looks_like_attention_query(text) and answer_attention_query:
        ans = answer_attention_query(text)
        final_reply = _prepare_reply(ans.get("text") or "No material page. READ_ONLY_ADVISORY.",
                                     _attention_provenance(ans))
        sent = _send(final_reply, reply_to=reply_to_message_id)
        out.update({
            "handled": True,
            "kind": "attention",
            "attention_reason": ans.get("reason"),
            "same_brain": True,
            "reply_preview": final_reply[:500],
            "outbound_message_id": sent.get("message_id"),
            "telegram_out_message_id": sent.get("message_id") if channel == "telegram" else None,
        })
        return out

    # Desk facts + optional DeepSeek Flash polish (skip S0 template wall)
    # A question that names a symbol is the desk loop's to answer (its own row,
    # gates, levels); the book-wide interceptor only serves "what's ready to buy".
    _named = []
    try:
        from scripts.lib.cio_operator_desk_loop import _extract_symbols
        _named = _extract_symbols(text)
    except Exception:
        _named = []
    if looks_like_reentry_purchase_query(text) and not _named:
        ans = answer_reentry_purchase_query(text, use_flash=True)
        final_reply = _prepare_reply(ans.get("text") or format_reentry_purchase_reply(),
                                     _reentry_facts_provenance(ans))
        sent = _send(final_reply, reply_to=reply_to_message_id)
        out.update({
            "handled": True,
            "kind": "reentry_facts",
            "reentry_source": ans.get("source"),
            "reentry_model": ans.get("model"),
            "reply_preview": final_reply[:500],
            "outbound_message_id": sent.get("message_id"),
            "telegram_out_message_id": sent.get("message_id") if channel == "telegram" else None,
        })
        return out

    # free-text converse
    if not rate_limit_ok(chat_id, path=rate_path, limit=wakes_limit):
        final_reply = _prepare_reply(
            "Rate limit: too many converse wakes this hour. Try: status or plans.",
            ReplyProvenance(kind="rate_limited", stores_read=[f"{Path(rate_path).name} (converse wake rate ledger)"]),
        )
        _send(final_reply)
        out["reason"] = "rate_limited"
        out["handled"] = True
        return out

    plan_id = goal_id = action_id = None
    decision_id = None
    if reply_to_message_id:
        plan_id = plan_id_for_reply_message(reply_to_message_id, path=msg_map_path)
        footer = parse_reply_footer(reply_to_text or "")
        plan_id = plan_id or footer.get("plan_id")
        goal_id = footer.get("goal_id")
        action_id = footer.get("action_id")
        decision_id = footer.get("decision_id")
    parsed = parse_ids_from_text(text)
    plan_id = plan_id or parsed.get("plan_id")
    goal_id = goal_id or parsed.get("goal_id")
    action_id = action_id or parsed.get("action_id")
    decision_id = decision_id or parsed.get("decision_id")
    # A quoted CIO card is a decision thread, not a new S0 converse plan.
    if not decision_id and reply_to_text:
        decision_id = parse_ids_from_text(reply_to_text).get("decision_id")

    if decision_id and str(decision_id).startswith("dec_"):
        thread = load_decision_thread_context(decision_id)
        final_reply = _prepare_reply(
            format_decision_thread_reply(decision_id=decision_id, operator_text=text, thread=thread),
            _decision_thread_provenance(str(decision_id), thread if isinstance(thread, dict) else {}),
        )
        sent = _send(final_reply, reply_to=reply_to_message_id)
        if not dry_run:
            record_decision_thread_note(
                decision_id,
                text,
                disposition=str(thread.get("disposition") or ""),
            )
        out.update({
            "handled": True,
            "kind": "decision_thread",
            "decision_id": decision_id,
            "plan_id": None,
            "attached_plan_id": plan_id,
            "reply_preview": final_reply[:500],
            "outbound_message_id": sent.get("message_id"),
            "telegram_out_message_id": sent.get("message_id") if channel == "telegram" else None,
        })
        return out

    # Trade-AI desk loop: Flash analyzes intent → pull vetted facts → answer or defer
    # Natural language understanding is Flash's job; numbers only from Trade-AI.
    # Stage 1+3: Maria skill calls scripts.lib.operator_internal_first.answer_internal_first
    # (same finalize + Hermes join). Desk stays on this path so _prepare_reply remains
    # THE Telegram/WA chokepoint; join honesty is applied below before finalize.
    desk = handle_operator_desk_question(
        text,
        chat_id=chat_id,
        message_id=message_id_s,
        channel=channel,
    )
    # The unanswerable branch carries its refusal in `reply_preview`, not `text`;
    # reading only `text` replaced "I can't answer that from Trade-AI" with a
    # generic line claiming a pull was queued.
    desk_prov = provenance_for_desk(desk, kind="operator_desk")
    reply = (desk.get("text") or desk.get("reply_preview") or "").strip()
    if not reply:
        desk_prov.kind = "failsoft_empty"
        reply = (
            "Trade-AI had no vetted answer for that yet — "
            "try `/cio reentry` or `/cio portfolio`.\n"
            "No orders/stops from chat · READ_ONLY_ADVISORY"
        )
    # Shared Hermes join (Stage 3): never let "0 findings" stand beside a desk res_*.
    try:
        from scripts.lib.hermes_subject_join import (  # noqa: PLC0415
            claim_contradicts_join,
            join_subject_hermes,
        )
        _syms = [str(s).upper() for s in ((desk.get("intent") or {}).get("symbols") or []) if s]
        if _syms:
            _join = join_subject_hermes(_syms[0])
            if _join.sources:
                desk_prov.stores_read = list(desk_prov.stores_read or []) + list(_join.sources)
            if claim_contradicts_join(reply, _join):
                reply = _join.honesty_line + "\n\n" + reply
    except Exception:  # noqa: BLE001
        pass
    final_reply = _prepare_reply(reply, desk_prov)

    # Scope comms-editor footer links to this turn's primary symbols only
    # (purge residual bleed e.g. TROW from prior-turn memory still in the body).
    _primary_tok = None
    try:
        from scripts.lib.comms_editor import set_primary_symbols, reset_primary_symbols
        desk_syms = list((desk.get("intent") or {}).get("symbols") or [])
        if desk_syms:
            _primary_tok = set_primary_symbols(desk_syms)
    except Exception:
        _primary_tok = None

    # Audit wake / rate only — do not use plan enrichment as the Telegram body
    event_id = None
    wake_id = None
    if not dry_run:
        payload = {
            "text": text[:4000],
            "chat_id": chat_id,
            "message_id": message_id_s,
            "channel": channel,
            "reply_to_message_id": str(reply_to_message_id or "") or None,
            "ts": _now(),
            "user_id": str(user_id or ""),
            "username": username or "",
            "plan_id": plan_id,
            "goal_id": goal_id,
            "action_id": action_id,
            "authority": "READ_ONLY_ADVISORY",
            "reply_source": desk.get("reply_source"),
            "desk_kind": desk.get("kind"),
            "pending_id": desk.get("pending_id"),
            # Stores read, what went outside the Command Center, the model and
            # whether the Sources line was on the text that was sent. Field
            # names are the answer-quality monitor's contract.
            "reply_provenance": out.get("reply_provenance"),
        }
        try:
            from scripts.lib.cio_event_bus import CIOEventBus
            evt = CIOEventBus().emit(
                "operator.message",
                payload,
                source=f"cio_{channel}",
                priority="HIGH",
            )
            event_id = getattr(evt, "event_id", None) or (
                evt.get("event_id") if isinstance(evt, dict) else None
            )
        except Exception:
            event_id = emit_operator_message(payload)
        wake_id = enqueue_operator_wake_channel(
            chat_id=chat_id,
            message_id=message_id_s,
            text=text,
            plan_id=plan_id,
            goal_id=goal_id,
            action_id=action_id,
            event_id=event_id,
            channel=channel,
            actor_id=actor_id,
        )
        mark_wake_rate(chat_id, path=rate_path)

    try:
        sent = _send(final_reply, reply_to=reply_to_message_id)
    finally:
        if _primary_tok is not None:
            try:
                reset_primary_symbols(_primary_tok)
            except Exception:
                pass
    out.update({
        "handled": True,
        "kind": "operator_desk",
        "desk_kind": desk.get("kind"),
        "reply_source": desk.get("reply_source"),
        "reply_model": desk.get("model"),
        "pending_id": desk.get("pending_id"),
        "wake_job_id": wake_id,
        "event_id": event_id,
        "plan_id": plan_id,
        # One concept, one key, on EVERY branch. The decision-thread branch
        # above reports the resolved plan as `attached_plan_id` and sets
        # `plan_id` to None; this branch reported it as `plan_id` and omitted
        # `attached_plan_id` entirely. A caller asking "which plan was this
        # message attached to?" therefore had to already know which branch
        # answered in order to know which key to read -- and reading the wrong
        # one returns None, which is indistinguishable from "no plan".
        "attached_plan_id": plan_id,
        "reply_preview": final_reply[:500],
        "outbound_message_id": sent.get("message_id"),
        "telegram_out_message_id": sent.get("message_id") if channel == "telegram" else None,
    })
    return out
