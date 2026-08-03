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
from telegram_transport import MAX_MSG_LEN, send_message, smart_split


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


def _raw_send_telegram(message: str, chat_ids: list = None, *,
                       reply_markup: dict | None = None,
                       parse_mode: str = "Markdown",
                       thread_id: str | None = None) -> dict:
    """Low-level Telegram send. Returns dict with ok, results (per-chat delivery detail)."""
    try:
        from notification_url_builder import publicize_message
        message = publicize_message(message)
    except Exception:
        pass
    token = _token()
    targets = chat_ids or _chat_ids()
    if not token or not targets:
        return {"ok": False, "reason": "missing_token_or_chat_id"}
    all_ok = True
    results = []
    try:
        chunks = _smart_split(message, MAX_MSG_LEN)
        for cid in targets:
            for chunk in chunks:
                result = send_message(token=token, chat_id=cid, text=chunk,
                                     thread_id=thread_id, reply_markup=reply_markup,
                                     parse_mode=parse_mode)
                results.append({"chat_id": cid, **result})
                if not result.get("ok"):
                    print(f"[telegram] Error to {cid}: {result.get('status_code')}")
                    all_ok = False
    except Exception as e:
        print(f"[telegram] Error: {e}")
        all_ok = False
    try:
        from report_capture import capture
        capture(message, ok=all_ok, channel="telegram")
    except Exception:
        pass
    return {"ok": all_ok, "results": results}


def _legacy_send(message: str, bypass_router: bool) -> bool:
    """Pre-normalization behaviour, unchanged. Requires no new table."""
    if not _token() or not _chat_ids():
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
    return _raw_send_telegram(message).get("ok", False)


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


def send_telegram(message: str, bypass_router: bool = False) -> bool:
    """Send/publish an operator alert. Returns True when the event was ACCEPTED.

    Accepted means the platform has taken responsibility for the event — delivered
    now, queued for a digest, or recorded for Command Center. It deliberately does
    NOT mean "a Telegram message was sent": returning False for a correctly digested
    event made callers treat normal routing as failure and retry, which is exactly
    the storm this normalization exists to stop. Callers needing delivery detail
    should use publish_operator_message() and read `delivered`.
    """
    if not _enabled():
        return False
    try:
        result = publish_operator_message(message, bypass_router=bypass_router)
    except Exception as e:
        # ACTIVE with a missing migration lands here. Loud, and NOT silently dropped:
        # fall back to legacy delivery so the operator still gets the alert.
        print(f"[telegram] normalized publish failed ({type(e).__name__}: {str(e)[:160]}) "
              f"— falling back to legacy delivery")
        return _legacy_send(message, bypass_router)
    if not result.get("delivered") and result.get("route_mode") not in (None, "LEGACY"):
        print(f"[telegram] {result.get('route_mode')} ({result.get('reason')}): {message[:60]}...")
    return bool(result.get("accepted"))


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


# ── Chokepoint accessors (2026-08-01: Phase 5 broker consolidation) ───────────────────

# Set of scripts known to bypass the central send_telegram() chokepoint (requests.post directly).
# These should be migrated to chokepoint_send() or send_telegram() at next maintenance touch.
TELEGRAM_BYPASS_SCRIPTS: set[str] = {
    "audit_enrichment_coverage.py",
    "audit_position_basis.py",
    "atm_auto_approver.py",
    "crawl_v3_dashboard.py",
    "freshness_watchdog_heartbeat.py",
    "full_system_backup.py",
    "intel_table_staleness_monitor.py",
    "iris_taxonomy_agent.py",
    "pipeline_health_monitor.py",
    "pipeline_watchdog.py",
    "premarket_watcher.py",
    "previously_traded_watchlist.py",
    "pro_analyst_monitor.py",
    "protection_alerts.py",
    "schwab_position_sync.py",
    "schwab_token_manager.py",
    "system_freshness_monitor.py",
    "technicals_gap_backfill.py",
    "trade_ai_news_monitor.py",
    "watch_directives_service.py",
    "watchlist_entry_planner.py",
    "youtube_cookie_health_check.py",
}


def chokepoint_send(message: str, *, token: str | None = None,
                    chat_id: str | None = None,
                    reply_markup: dict | None = None,
                    parse_mode: str = "Markdown",
                    thread_id: str | None = None,
                    dry_run: bool = False) -> dict:
    """Central Telegram chokepoint — use this instead of requests.post() direct.

    Route all outbound Telegram messages through this function. It applies:
      - URL normalization (notification_url_builder)
      - Smart split (4096-char limit)
      - Report capture (Reports portal)
      - ENV-based token/chat_id fallback (from .env)

    Args:
        message: The raw message text to send.
        token: Optional override for TELEGRAM_BOT_TOKEN.
        chat_id: Optional override for TELEGRAM_CHAT_ID.
        reply_markup: Optional inline keyboard dict (Telegram format).
        parse_mode: Telegram parse mode (\"Markdown\", \"HTML\", \"MarkdownV2\").
        thread_id: Optional message_thread_id for topic groups.
        dry_run: If True, returns mock success without sending.

    Returns:
        dict with ok (bool), results (list of per-chat send results with message_id).
        Truthiness matches ok — use `if result.get(\"ok\")` or `if result:`.
    """
    if dry_run:
        return {"ok": True, "results": [], "dry_run": True}
    tok = token or _token()
    cids = [chat_id] if chat_id else _chat_ids()
    if not tok or not cids:
        print("[telegram:chokepoint] missing token or chat_id — message dropped")
        return {"ok": False, "reason": "missing_token_or_chat_id"}
    if not _enabled():
        return {"ok": False, "reason": "telegram_disabled"}
    return _raw_send_telegram(message, chat_ids=cids,
                             reply_markup=reply_markup, parse_mode=parse_mode,
                             thread_id=thread_id)


def warn_telegram_bypass(caller_file: str) -> None:
    """Warn at runtime if a script is still using direct requests.post() to Telegram.

    Call this from scripts that currently bypass the chokepoint::

        from telegram_alert import warn_telegram_bypass
        warn_telegram_bypass(__file__)

    It prints a one-line warning and records the bypass in the TELEGRAM_BYPASS_SCRIPTS set.
    """
    import os as _os
    fname = _os.path.basename(caller_file)
    TELEGRAM_BYPASS_SCRIPTS.add(fname)
    print(f"[telegram:bypass] WARN: {fname} bypasses the central chokepoint — "
          f"migrate to telegram_alert.chokepoint_send() or send_telegram()")
