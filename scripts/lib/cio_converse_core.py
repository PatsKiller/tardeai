"""CIO multi-channel converse core — READ_ONLY_ADVISORY.

Shared free-text / command / plan continuity path used by Telegram and WhatsApp.
Transport (ingress/egress) stays outside this module.

No broker/order/stop/2FA authority.
"""
from __future__ import annotations

import hashlib
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
    assemble_context,
    build_template_advisory,
    emit_operator_message,
    ensure_converse_plan,
    format_structured_reply,
    handle_cio_slash,
    mark_message_seen,
    mark_wake_rate,
    message_seen,
    parse_ids_from_text,
    parse_reply_footer,
    plan_id_for_reply_message,
    rate_limit_ok,
    record_plan_message,
    format_decision_thread_reply,
    load_decision_thread_context,
    record_decision_thread_note,
    _now,
)

SendFn = Callable[..., dict[str, Any]]

# Plain-text command prefixes accepted on WhatsApp (no leading /cio required)
PLAIN_CMD_RE = re.compile(
    r"^\s*(?:/cio\s+)?(help|plans|plan|thesis|traces|status|actions|portfolio|hermes|risk|"
    r"ack|rate|defer|done|reject)\b",
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
                },
            },
            actor_id=actor_id,
            actor_type="system",
            authority="READ_ONLY_ADVISORY",
        )
        return wake_job_id
    except Exception:
        return None


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

    def _send(body: str, reply_to: Optional[str] = None) -> dict[str, Any]:
        if dry_run or send_fn is None:
            return {"ok": True, "message_id": None, "dry_run": True}
        try:
            return send_fn(chat_id, body, reply_to=reply_to)  # type: ignore[call-arg]
        except TypeError:
            return send_fn(chat_id, body)  # type: ignore[misc]
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

    # Deterministic commands (slash or plain)
    if is_cmd and cmd_text:
        reply = handle_cio_slash(cmd_text)
        if channel == "whatsapp":
            reply = re.sub(r"\*([^*]+)\*", r"\1", reply).replace("`", "")
        sent = _send(reply)
        out.update({
            "handled": True,
            "kind": "slash",
            "reply_preview": reply[:200],
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
            reply = handle_cio_slash(f"/cio ack {pid}")
            if channel == "whatsapp":
                reply = re.sub(r"\*([^*]+)\*", r"\1", reply).replace("`", "")
            sent = _send(reply)
            out.update({
                "handled": True,
                "kind": "ack",
                "plan_id": pid,
                "outbound_message_id": sent.get("message_id"),
            })
            return out

    # free-text converse
    if not rate_limit_ok(chat_id, path=rate_path, limit=wakes_limit):
        _send("Rate limit: too many converse wakes this hour. Try: status or plans.")
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
        reply = format_decision_thread_reply(
            decision_id=decision_id,
            operator_text=text,
            thread=thread,
        )
        if channel == "whatsapp":
            reply = re.sub(r"\*([^*]+)\*", r"\1", reply).replace("`", "")
        sent = _send(reply, reply_to=reply_to_message_id)
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
            "reply_preview": reply[:500],
            "outbound_message_id": sent.get("message_id"),
            "telegram_out_message_id": sent.get("message_id") if channel == "telegram" else None,
        })
        return out

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
    }

    event_id = None
    wake_id = None
    if not dry_run:
        # source label for bus
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

    ctx = assemble_context(text, plan_id=plan_id, action_id=action_id, goal_id=goal_id)
    advisory = build_template_advisory(text, ctx)
    new_plan_id = plan_id
    llm_deferred = True
    if not dry_run:
        new_plan_id = ensure_converse_plan(
            advisory, plan_id=plan_id, symbols=ctx.get("symbols") or [], text=text,
        )
        try:
            from scripts.lib.cio_plans import CIOPlanStore
            from scripts.lib.cio_plan_enrichment import enrich_plan
            store = CIOPlanStore()
            plan_obj = store.get_plan(new_plan_id) if new_plan_id else None
            if plan_obj:
                enr = enrich_plan(
                    plan_obj,
                    source="OPERATOR_MESSAGE",
                    wake_id=str(wake_id or message_id_s),
                    extra_context={
                        "operator_text": text[:500],
                        "symbols": ctx.get("symbols"),
                        "channel": channel,
                    },
                    plan_store=store,
                )
                plan_obj = enr.get("plan") or plan_obj
                llm_deferred = plan_obj.get("narrative_source") != "llm"
                advisory = {
                    "summary": plan_obj.get("summary") or advisory.get("summary"),
                    "evidence_refs": plan_obj.get("evidence_refs") or advisory.get("evidence_refs"),
                    "options": plan_obj.get("options") or advisory.get("options"),
                    "recommendation": plan_obj.get("recommendation") or advisory.get("recommendation"),
                    "risks": plan_obj.get("risks") or advisory.get("risks"),
                    "revisit_at": plan_obj.get("revisit_at") or advisory.get("revisit_at"),
                    "llm_deferred": llm_deferred,
                    "deep_links": plan_obj.get("cc_deep_links") or advisory.get("deep_links"),
                }
        except Exception:
            llm_deferred = True

    # P3/P6: thesis pin + CC deep links from plan
    thesis_pin = None
    sit_type = "S0_OPERATOR_CONVERSE"
    plan_links = advisory.get("deep_links")
    plan_symbols = ctx.get("symbols") or []
    if not dry_run and new_plan_id:
        try:
            from scripts.lib.cio_plans import CIOPlanStore
            pref = CIOPlanStore().get_plan(new_plan_id)
            if pref:
                thesis_pin = pref.get("thesis_version")
                sit_type = pref.get("situation_type") or sit_type
                plan_links = pref.get("cc_deep_links") or plan_links
                plan_symbols = pref.get("symbols") or plan_symbols
                goal_id = goal_id or (
                    (pref.get("linked_goal_ids") or [None])[0]
                )
        except Exception:
            pass
    if not thesis_pin:
        try:
            from scripts.lib.cio_theses import safe_current_pin
            thesis_pin = safe_current_pin("desk")
        except Exception:
            pass

    reply = format_reply_for_channel(
        channel=channel,
        summary=advisory["summary"],
        evidence_refs=advisory.get("evidence_refs"),
        options=advisory.get("options"),
        recommendation=advisory.get("recommendation") or "",
        risks=advisory.get("risks"),
        plan_id=new_plan_id,
        goal_id=goal_id,
        action_id=action_id,
        revisit_at=advisory.get("revisit_at"),
        thesis_version=thesis_pin,
        situation_type=sit_type,
        llm_deferred=bool(advisory.get("llm_deferred", llm_deferred)),
        deep_links=plan_links,
        symbols=plan_symbols,
    )

    sent_mid = None
    if not dry_run:
        sent = _send(reply, reply_to=reply_to_message_id)
        sent_mid = sent.get("message_id")
        if sent_mid and new_plan_id:
            record_plan_message(
                new_plan_id,
                sent_mid,
                chat_id,
                path=msg_map_path,
                channel=channel,
            )
        # close wake trace (fail-soft) — same as TG
        if wake_id:
            try:
                from scripts.lib.cio_wake_traces import close_trace
                close_trace(
                    wake_id=str(wake_id),
                    outcome="deferred" if llm_deferred else "ok",
                    plan_id=new_plan_id,
                    situation_type="S0_OPERATOR_CONVERSE",
                    agent_id="alex",
                    source="OPERATOR_MESSAGE",
                )
            except Exception:
                pass

    out.update({
        "handled": True,
        "kind": "converse",
        "event_id": event_id,
        "wake_job_id": wake_id,
        "plan_id": new_plan_id,
        "attached_plan_id": plan_id,
        "outbound_message_id": sent_mid,
        "telegram_out_message_id": sent_mid if channel == "telegram" else None,
        "reply_preview": reply[:240],
        "llm_deferred": bool(advisory.get("llm_deferred", llm_deferred)),
    })
    return out
