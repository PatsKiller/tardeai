"""telegram_alert.py — Telegram bot alerts for Trade AI v12.

Setup (one time, 2 minutes):
  1. Open Telegram, search @BotFather
  2. Send /newbot — follow prompts, copy the bot token
  3. Add TELEGRAM_BOT_TOKEN=<token> to .env
  4. Message your new bot once (so it has a chat_id)
  5. Visit: https://api.telegram.org/bot<token>/getUpdates
     Copy the "chat" -> "id" value
  6. Add TELEGRAM_CHAT_ID=<id> to .env

Telegram supports Markdown formatting (bold *text*, italic _text_).
Messages limited to 4096 chars — long messages split automatically.
No cost. No Twilio account needed.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from telegram_transport import MAX_MSG_LEN, send_document, send_message, smart_split


def _env(k: str, default: str = "") -> str:
    if k not in os.environ:
        try:
            import sys
            from pathlib import Path
            _lib = str(Path(__file__).resolve().parent / "lib")
            if _lib not in sys.path:
                sys.path.insert(0, _lib)
            from env_bootstrap import ensure_loaded
            ensure_loaded()
        except Exception:
            pass
    return os.getenv(k, default).strip()

def _enabled() -> bool:
    return _env("ENABLE_TELEGRAM", "true").lower() == "true"

def _token() -> str:
    return _env("TELEGRAM_BOT_TOKEN")

def _chat_ids() -> list:
    """Support comma-separated chat IDs for multiple recipients."""
    raw = _env("TELEGRAM_CHAT_ID")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _smart_split(text: str, limit: int) -> list[str]:
    """Split text at newline boundaries, falling back to sentence then hard cut."""
    return smart_split(text, limit)


def _raw_send_telegram_result(
    message: str,
    chat_ids: list = None,
    *,
    reply_markup: dict | None = None,
    thread_id: str | None = None,
) -> dict:
    """Low-level Telegram send with provider message ids. No routing."""
    # FQDN/v3 normalization at the send chokepoint: rewrite any internal IP/localhost + legacy /v2/
    # dashboard link to the public Tailscale FQDN + /v3/ so no notification can leak a wrong URL.
    try:
        from notification_url_builder import publicize_message
        message = publicize_message(message)
    except Exception:
        pass
    token = _token()
    targets = chat_ids or _chat_ids()
    if not token or not targets:
        return {"ok": False, "message_ids": [], "chat_ids": []}
    ok = True
    message_ids: list[str] = []
    try:
        chunks = _smart_split(message, MAX_MSG_LEN)
        for cid in targets:
            for i, chunk in enumerate(chunks):
                # Attach keyboard only on the final chunk so buttons stay with the full body.
                markup = reply_markup if (reply_markup and i == len(chunks) - 1) else None
                result = send_message(
                    token=token,
                    chat_id=cid,
                    text=chunk,
                    reply_markup=markup,
                    thread_id=thread_id,
                )
                if not result.get("ok"):
                    print(f"[telegram] Error to {cid}: {result.get('status_code')}")
                    ok = False
                    continue
                mid = result.get("message_id")
                if mid is not None and str(mid).strip():
                    message_ids.append(str(mid))
    except Exception as e:
        print(f"[telegram] Error: {e}")
        ok = False
    # Persist recognized reports so the v3 Reports portal can surface them (best-effort, never blocks).
    try:
        from report_capture import capture
        capture(message, ok=ok, channel="telegram")
    except Exception:
        pass
    return {
        "ok": ok,
        "message_ids": message_ids,
        "chat_ids": [str(c) for c in targets],
    }


def _raw_send_telegram(
    message: str,
    chat_ids: list = None,
    *,
    reply_markup: dict | None = None,
    thread_id: str | None = None,
) -> bool:
    """Low-level Telegram send. No routing — called after router approval."""
    return bool(
        _raw_send_telegram_result(
            message,
            chat_ids,
            reply_markup=reply_markup,
            thread_id=thread_id,
        ).get("ok")
    )


def _legacy_send(
    message: str,
    bypass_router: bool,
    *,
    reply_markup: dict | None = None,
    chat_ids: list | None = None,
    thread_id: str | None = None,
) -> bool:
    """Pre-normalization behaviour, unchanged. Requires no new table."""
    targets = chat_ids or _chat_ids()
    if not _token() or not targets:
        print("[telegram] Skipped — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False
    if not bypass_router:
        try:
            from telegram_alert_router import should_send_telegram, mark_sent, classify_alert
            if not should_send_telegram(message):
                level = classify_alert(message)
                print(f"[telegram] Suppressed ({level}): {message[:60]}...")
                try:
                    from report_capture import archive_message
                    archive_message(message, suppressed=True, reason=level)
                except Exception:
                    pass
                return False
            mark_sent(message)
        except ImportError:
            pass  # Router not available — send normally
    return _raw_send_telegram(
        message, chat_ids=targets, reply_markup=reply_markup, thread_id=thread_id
    )


def publish_operator_message(message: str, *, bypass_router: bool = False,
                             source_producer: str = "legacy_send_telegram") -> dict:
    """Mode-aware publish. Returns the structured PublishResult mapping.

    OFF     legacy router + legacy sender; the normalized tables are never touched.
    SHADOW  legacy delivery happens exactly as in OFF; the normalized decision is
            additionally persisted when the migration is present. Shadow persistence
            is best-effort and can never suppress or fail a legacy send.
    ACTIVE  the normalized outbox owns routing and delivery.
    """
    from alert_runtime_mode import MODE_ACTIVE, MODE_OFF, MODE_SHADOW, get_mode

    mode = get_mode()

    if mode == MODE_OFF:
        delivered = _legacy_send(message, bypass_router)
        return {
            "accepted": True, "route_mode": "LEGACY", "runtime_mode": MODE_OFF,
            "queued": False, "delivered": bool(delivered), "suppressed": not delivered,
            "reason": "legacy_delivery" if delivered else "legacy_router_suppressed_or_unconfigured",
            "alert_id": None, "incident_id": None,
        }

    if mode == MODE_SHADOW:
        delivered = _legacy_send(message, bypass_router)
        shadow: dict = {"persisted": False}
        try:
            from alert_runtime_mode import can_persist_shadow
            if can_persist_shadow():
                from alert_outbox import publish_legacy_message
                shadow = publish_legacy_message(
                    message, source_producer=source_producer, bypass_router=bypass_router)
                shadow["persisted"] = True
        except Exception as e:
            # Never let shadow bookkeeping affect the operator's alert.
            print(f"[telegram] shadow persist skipped: {type(e).__name__}: {str(e)[:120]}")
        return {
            "accepted": True, "route_mode": "LEGACY_SHADOWED", "runtime_mode": MODE_SHADOW,
            "queued": False, "delivered": bool(delivered), "suppressed": not delivered,
            "reason": "legacy_delivery_with_shadow_evaluation",
            "alert_id": shadow.get("alert_id"), "incident_id": shadow.get("incident_id"),
            "shadow": shadow,
        }

    # ACTIVE — missing tables raise rather than silently dropping the alert.
    from alert_runtime_mode import require_active_capability
    require_active_capability()
    from alert_outbox import publish_legacy_message
    return publish_legacy_message(message, source_producer=source_producer,
                                  bypass_router=bypass_router)


def _comms_gateway_owns(message_class: str) -> bool:
    """True when COMMS_GATEWAY_MODE is CANARY/ACTIVE and class is allowlisted."""
    try:
        from scripts.lib.comms.channel_adapters import telegram_class_allowed
        from scripts.lib.comms.mode import MODE_ACTIVE, MODE_CANARY, get_gateway_mode
    except ImportError:
        try:
            from lib.comms.channel_adapters import telegram_class_allowed  # type: ignore
            from lib.comms.mode import MODE_ACTIVE, MODE_CANARY, get_gateway_mode  # type: ignore
        except ImportError:
            return False
    mode = get_gateway_mode(refresh=True)
    if mode not in (MODE_CANARY, MODE_ACTIVE):
        return False
    return telegram_class_allowed(mode, message_class)


def _best_effort_comms_publish(
    message: str,
    *,
    message_class: str,
    producer: str = "telegram_alert.send_telegram",
) -> None:
    """Record CommunicationEvent without claiming delivery ownership (OFF/SHADOW)."""
    try:
        from scripts.lib.comms.adapters import from_plain_message
        from scripts.lib.comms.client import publish_communication
    except ImportError:
        try:
            from lib.comms.adapters import from_plain_message  # type: ignore
            from lib.comms.client import publish_communication  # type: ignore
        except ImportError:
            return
    try:
        subject_key = f"telegram:{message_class}:{(message or '')[:48]}"
        publish_communication(
            from_plain_message(
                producer=producer,
                body=message,
                subject_key=subject_key,
                message_class=message_class,
            )
        )
    except Exception:
        return


def _send_via_comms_gateway(
    message: str,
    *,
    message_class: str,
    reply_markup: dict | None = None,
    chat_ids: list | None = None,
    thread_id: str | None = None,
    producer: str = "telegram_alert.send_telegram",
) -> bool:
    """Publish CommunicationEvent then gateway-deliver. No legacy dual-send.

    Order: ``publish_communication`` → ``send_via_gateway(..., deliver=True,
    event_id=...)`` so ``require_event_id`` binds the same observation. Never
    also calls ``_legacy_send`` for the same message.
    """
    try:
        from scripts.lib.comms.adapters import from_plain_message
        from scripts.lib.comms.channel_adapters import send_via_gateway
        from scripts.lib.comms.client import publish_communication
    except ImportError:
        from lib.comms.adapters import from_plain_message  # type: ignore
        from lib.comms.channel_adapters import send_via_gateway  # type: ignore
        from lib.comms.client import publish_communication  # type: ignore

    subject_key = f"telegram:{message_class}:{(message or '')[:48]}"
    published = publish_communication(
        from_plain_message(
            producer=producer,
            body=message,
            subject_key=subject_key,
            message_class=message_class,
        )
    )
    if not published.ok or not published.event_id:
        print(
            f"[telegram] gateway publish failed — refusing dual-send for "
            f"owned class {message_class}"
        )
        return False

    # Reuse the reservation minted by publish_communication when present.
    existing_dlv = (
        published.delivery_ids[0] if published.delivery_ids else None
    )
    result = send_via_gateway(
        "telegram",
        body=message,
        producer=producer,
        subject_key=subject_key,
        message_class=message_class,
        deliver=True,
        event_id=published.event_id,
        reply_markup=reply_markup,
        chat_ids=chat_ids,
        thread_id=thread_id,
        _existing_delivery_id=existing_dlv,
    )
    if not result.get("delivered"):
        print(
            f"[telegram] gateway deliver blocked/failed "
            f"({result.get('error')}): {message[:60]}..."
        )
        return False
    return True


def send_telegram(
    message: str,
    bypass_router: bool = False,
    *,
    reply_markup: dict | None = None,
    chat_ids: list | None = None,
    thread_id: str | None = None,
    message_class: str = "operator_alert",
    _gateway_owned: bool = False,
) -> bool:
    """Send/publish an operator alert. Returns True when the event was ACCEPTED.

    Accepted means the platform has taken responsibility for the event — delivered
    now, queued for a digest, or recorded for Command Center. It deliberately does
    NOT mean "a Telegram message was sent": returning False for a correctly digested
    event made callers treat normal routing as failure and retry, which is exactly
    the storm this normalization exists to stop. Callers needing delivery detail
    should use publish_operator_message() and read `delivered`.

    When ``COMMS_GATEWAY_MODE`` is CANARY/ACTIVE and ``message_class`` is
    allowlisted, the communications gateway owns delivery (publish then
    ``send_via_gateway(deliver=True)``) — no legacy dual-send.

    ``_gateway_owned=True`` skips gateway re-entry (recursion guard if a provider
    path ever called ``send_telegram``). Prefer ``_raw_send_telegram`` instead.
    """
    if not _enabled():
        return False
    # Phase 6 Tier D broker — SHADOW ingest only; never suppresses delivery.
    try:
        from lib.advisory.notification_broker import wrap_send_hook
        wrap_send_hook(message, producer="send_telegram", bypass_router=bypass_router)
    except Exception:
        pass

    # Recursion guard: never re-enter send_via_gateway from a gateway-owned call.
    if _gateway_owned:
        return _legacy_send(
            message,
            bypass_router,
            reply_markup=reply_markup,
            chat_ids=chat_ids,
            thread_id=thread_id,
        )

    mc = (message_class or "operator_alert").strip() or "operator_alert"
    if _comms_gateway_owns(mc):
        try:
            return _send_via_comms_gateway(
                message,
                message_class=mc,
                reply_markup=reply_markup,
                chat_ids=chat_ids,
                thread_id=thread_id,
            )
        except Exception as e:
            print(
                f"[telegram] gateway-owned send failed ({type(e).__name__}: {str(e)[:160]}) "
                f"— not dual-sending legacy for owned class"
            )
            return False

    # OFF/SHADOW or class not allowlisted: legacy send + best-effort ledger publish.
    # Keyboards / explicit destinations stay on legacy transport until outbox owns them.
    if reply_markup is not None or chat_ids is not None or thread_id is not None:
        ok = _legacy_send(
            message,
            bypass_router,
            reply_markup=reply_markup,
            chat_ids=chat_ids,
            thread_id=thread_id,
        )
        _best_effort_comms_publish(message, message_class=mc)
        return ok
    try:
        result = publish_operator_message(message, bypass_router=bypass_router)
    except Exception as e:
        # ACTIVE with a missing migration lands here. Loud, and NOT silently dropped:
        # fall back to legacy delivery so the operator still gets the alert.
        print(f"[telegram] normalized publish failed ({type(e).__name__}: {str(e)[:160]}) "
              f"— falling back to legacy delivery")
        ok = _legacy_send(message, bypass_router)
        _best_effort_comms_publish(message, message_class=mc)
        return ok
    _best_effort_comms_publish(message, message_class=mc)
    if not result.get("delivered") and result.get("route_mode") not in (None, "LEGACY"):
        print(f"[telegram] {result.get('route_mode')} ({result.get('reason')}): {message[:60]}...")
    return bool(result.get("accepted"))


def send_telegram_document(
    file_path: str,
    caption: str = "",
    *,
    bypass_router: bool = True,
    chat_ids: list | None = None,
    message_class: str = "operator_alert",
) -> bool:
    """Send a file via the approved transport sendDocument chokepoint.

    Producers must call this instead of raw Bot API sendDocument. Credentials and
    chat selection stay inside telegram_alert / telegram_transport.

    Document bytes are not yet gateway-mediated: when COMMS owns the class we
    still send via the approved chokepoint and publish a CommunicationEvent for
    the caption (no dual text send). OFF/SHADOW keeps legacy + best-effort publish.
    """
    if not _enabled():
        return False
    from pathlib import Path

    path = Path(file_path)
    if not path.is_file():
        print(f"[telegram] document missing: {file_path}")
        return False
    cap = caption or path.name
    try:
        from notification_url_builder import publicize_message
        cap = publicize_message(cap)
    except Exception:
        pass
    if not bypass_router:
        try:
            from telegram_alert_router import should_send_telegram, mark_sent, classify_alert
            if not should_send_telegram(cap):
                level = classify_alert(cap)
                print(f"[telegram] document suppressed ({level}): {cap[:60]}...")
                return False
            mark_sent(cap)
        except ImportError:
            pass
    token = _token()
    targets = chat_ids or _chat_ids()
    if not token or not targets:
        print("[telegram] document skipped — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    mc = (message_class or "operator_alert").strip() or "operator_alert"
    # Optional CANARY chat filter when gateway owns the class.
    if _comms_gateway_owns(mc):
        try:
            from scripts.lib.comms.channel_adapters import _telegram_canary_chats
            from scripts.lib.comms.mode import MODE_CANARY, get_gateway_mode
        except ImportError:
            from lib.comms.channel_adapters import _telegram_canary_chats  # type: ignore
            from lib.comms.mode import MODE_CANARY, get_gateway_mode  # type: ignore
        if get_gateway_mode(refresh=True) == MODE_CANARY:
            allow = _telegram_canary_chats()
            if allow:
                targets = [c for c in targets if c in allow]
                if not targets:
                    print("[telegram] document blocked — no chat in COMMS_GATEWAY_CANARY_CHATS")
                    return False

    ok = True
    for cid in targets:
        result = send_document(token=token, chat_id=cid, file_path=str(path), caption=cap)
        if not result.get("ok"):
            print(f"[telegram] document error to {cid}: {result.get('status_code')}")
            ok = False
    try:
        from report_capture import capture
        capture(cap, ok=ok, channel="telegram_document")
    except Exception:
        pass
    # Ledger: always best-effort for documents (gateway does not yet own file bytes).
    _best_effort_comms_publish(
        cap, message_class=mc, producer="telegram_alert.send_telegram_document"
    )
    return ok


def build_telegram_message(
    scored_tickers: List[Dict[str, Any]],
    delta: Dict[str, Any],
    run_label: str,
    date_str: str,
    market_snapshot: Optional[Dict] = None,
    options_summary: Optional[Dict] = None,
    halt_data: Optional[Dict] = None,
    trade_plans: Optional[Dict] = None,
    short_summary: Optional[Dict] = None,
) -> str:
    """Build the full Telegram message. Mirrors WhatsApp format but adds v12 extras."""
    # Iris-aware categorization
    blocked     = [t for t in scored_tickers if t.get("disqualified")]
    downgraded  = [t for t in scored_tickers if t.get("decision_changed") and not t.get("disqualified")
                   and t.get("original_decision") == "GO"]
    go_tickers  = [t for t in scored_tickers if t.get("decision") == "GO" and not t.get("disqualified")]
    events      = delta.get("events", [])
    new_count   = len(delta.get("new_tickers", []))
    fade_count  = len(delta.get("faded", []))
    grade_up    = sum(1 for e in events if e.get("event") == "GRADE_UP")

    lines = [f"⚡ *Trade AI v12.1d [{run_label}]* | {date_str}", ""]

    # Market context
    if market_snapshot:
        indices = market_snapshot.get("indices", {})
        vix     = market_snapshot.get("vix", {})
        sectors = market_snapshot.get("sectors", [])
        breadth = market_snapshot.get("breadth_label", "Neutral")
        b_e = {"Bullish": "🟢", "Neutral": "🟡", "Bearish": "🔴"}.get(breadth, "🟡")

        # SPY / QQQ / IWM with green/red indicator per sign
        def _idx(sym):
            d = indices.get(sym, {})
            pct = d.get("change_percent", 0) or 0
            px  = d.get("price", 0) or 0
            col = "🟢" if pct > 0 else ("🔴" if pct < 0 else "⚪")
            sign = "+" if pct >= 0 else ""
            px_str = f" ${px:.2f}" if px else ""
            return f"{col} *{sym}* {sign}{pct:.2f}%{px_str}"

        vix_val = vix.get("price", 0) or 0
        vix_pct = vix.get("change_percent", 0) or 0
        vix_dir = vix.get("direction", "flat")
        v_e = "🔺" if "ris" in vix_dir or "spik" in vix_dir else ("🔻" if "fall" in vix_dir or "col" in vix_dir else "➡️")
        vix_sign = "+" if vix_pct >= 0 else ""

        # Top 3 leaders / bottom 3 laggards
        sorted_sectors = sorted(sectors, key=lambda s: s.get("change_percent", 0) or 0, reverse=True)
        leaders  = [f"{s['symbol']} {(s.get('change_percent',0) or 0):+.1f}%" for s in sorted_sectors[:3]]
        laggards = [f"{s['symbol']} {(s.get('change_percent',0) or 0):+.1f}%" for s in sorted_sectors[-3:]]

        lines += [
            "*📊 Market:*",
            f"  {_idx('SPY')}",
            f"  {_idx('QQQ')}",
            f"  {_idx('IWM')}",
            f"  {v_e} *VIX* {vix_val:.1f} ({vix_sign}{vix_pct:.1f}%) {vix_dir}",
            f"  {b_e} {breadth}",
            f"  ▲ {' · '.join(leaders)}",
            f"  ▼ {' · '.join(laggards)}",
            "",
        ]

    # Halt alerts (v12)
    if halt_data:
        halted  = halt_data.get("halted_tickers", [])
        resumed = halt_data.get("resumed_tickers", [])
        if halted:
            syms = ", ".join(h["symbol"] for h in halted[:5])
            lines.append(f"🚨 *HALTED:* {syms}")
        if resumed:
            syms = ", ".join(r["symbol"] for r in resumed[:5])
            lines.append(f"✅ *RESUMED:* {syms}")
        if halted or resumed:
            lines.append("")

    # Squeeze summary (v12)
    if short_summary and short_summary.get("any_squeeze"):
        top_sq = short_summary.get("top_squeezers", [])[:3]
        sq_str = "  ".join(f"{s['symbol']} {s['short_pct']:.0f}%" for s in top_sq)
        lines.append(f"🔥 *Short squeeze fuel:* {sq_str}")
        lines.append("")

    # Iris: blocked tickers (most critical — always first)
    if blocked:
        lines.append("🚫 *BLOCKED BY IRIS:*")
        for t in blocked:
            reason = (t.get("disqualification_reason") or t.get("critic_reasoning") or "flagged")[:90]
            orig = t.get("original_decision", "GO")
            lines.append(f"  ❌ *{t['symbol']}* (was {orig})")
            lines.append(f"     _{reason}_")
        lines.append("")

    # Iris: downgraded tickers
    if downgraded:
        lines.append("⬇ *DOWNGRADED BY IRIS:*")
        for t in downgraded:
            reason = (t.get("critic_reasoning") or "risk flag")[:80]
            lines.append(f"  ↓ *{t['symbol']}*: {t.get('original_decision','GO')} → {t['decision']}")
            lines.append(f"     _{reason}_")
        lines.append("")

    # GO-tier picks
    if go_tickers:
        lines.append("*🎯 GO-Tier Picks:*")
        for t in go_tickers[:5]:
            sym    = t["symbol"]
            score  = t["score"]
            rvol   = t.get("relative_volume", 0)
            s_arr  = t.get("score_arrow", "→")
            r_arr  = t.get("rvol_arrow", "→")
            sq_e   = t.get("squeeze_emoji", "")
            days   = t.get("consecutive_go_days", 1)
            top    = t.get("top_catalyst") or {}
            cat    = (top.get("title") or "No catalyst")[:55]
            emoji  = {"high_impact": "🔥", "medium_impact": "⚡", "low_impact": "📰"}.get(
                t.get("catalyst_tier", ""), "•")
            days_str = f"  📅 {days}d" if days > 1 else ""
            halt_str = "  🚨HALT" if t.get("is_halted") else ("  ✅RESUMED" if t.get("is_resumed") else "")
            plan = (trade_plans or {}).get(sym, {})
            plan_str = ""
            if plan:
                plan_str = (f"\n    💰 Entry: {plan.get('entry_zone','?')}  "
                            f"Stop: {plan.get('stop_loss','?')}  "
                            f"R1: {plan.get('target_r1','?')}  "
                            f"R:R {plan.get('risk_reward','?')}")
            # Add Ollama AI context if available from Stage 6 (free — already computed)
            ollama_line = ""
            ollama_flag = t.get("ollama_flag", "")
            ollama_sum = t.get("ollama_summary", "")
            ollama_risk = t.get("ollama_risk", "")
            if ollama_flag and ollama_flag not in ("NEUTRAL", ""):
                flag_emoji = {"GO":"🟢","WATCH":"👀","DILUTION":"⚠️","TRAP":"🚨","AVOID":"❌"}.get(ollama_flag, "•")
                ai_text = ollama_sum or ollama_risk or ""
                if ai_text:
                    ollama_line = f"\n  {flag_emoji} _{ollama_flag}: {ai_text[:60]}_"
            lines.append(
                f"  {emoji}{sq_e} *{sym}* ({score} {s_arr}) "
                f"RVOL {rvol:.1f}x {r_arr}{days_str}{halt_str}"
                f"\n  _{cat}_{plan_str}{ollama_line}"
            )
        lines.append("")
    else:
        lines.append("_No GO-tier setups this run._")
        lines.append("")

    # Options flow
    if options_summary and options_summary.get("total_sweeps", 0) > 0:
        lines.append(f"⚡ *Options:* {options_summary.get('sweep_summary_text','')}")
        lines.append("")

    # Delta summary
    parts = []
    if new_count:  parts.append(f"🆕 {new_count} new")
    if grade_up:   parts.append(f"📈 {grade_up} ↑")
    if fade_count: parts.append(f"👻 {fade_count} faded")
    if parts:
        lines += ["─" * 18, "  ".join(parts)]

    # Iris footer — only if critique ran
    critiqued = [t for t in scored_tickers if t.get("critic_verdict")]
    if critiqued:
        confirmed = sum(1 for t in critiqued if t.get("critic_verdict") == "CONFIRM")
        cat_replaced = sum(1 for t in scored_tickers if t.get("catalyst_verified") is False)
        iris_parts = [f"🔍 Iris: {len(critiqued)}/{len(scored_tickers)} reviewed"]
        iris_parts.append(f"{confirmed} confirmed")
        if blocked: iris_parts.append(f"{len(blocked)} blocked")
        if downgraded: iris_parts.append(f"{len(downgraded)} downgraded")
        if cat_replaced: iris_parts.append(f"{cat_replaced} catalyst replaced")
        lines.append("─" * 18)
        lines.append(" · ".join(iris_parts))

    return "\n".join(lines)
