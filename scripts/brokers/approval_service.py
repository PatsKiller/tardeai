"""Two-factor trade approval service (operator requirement 2026-06-11).

For any FUTURE live submission, an intent must hold a FULLY-APPROVED record: BOTH channels confirmed —
  web      : UI popup -> POST /api/v2/broker-orders/approve  (channel='web')
  telegram : notification with one-time 6-digit code -> operator replies; callback confirms (channel='telegram')
within TTL (default 10 min), single-use, bound to one intent_id. Fail-closed everywhere: missing/expired/
reused/partial approvals all deny. This is the FOURTH lock (env flag + DB control + standing signed approval
+ per-trade 2FA) and is fully testable today while execution remains BROKER_DISABLED.
"""
from __future__ import annotations

import os
import sys
import secrets
import datetime as dt
import json
from dataclasses import asdict, is_dataclass

TTL_MIN = int(os.getenv("TRADE_APPROVAL_TTL_MIN", "10"))

# How many of the two channels (web typed-ticker, telegram code) must confirm before a submit is
# allowed. Operator directive 2026-06-15: EITHER channel is sufficient — typing the ticker is enough
# fat-finger protection on its own, and the operator does not want to be forced through both. Set to 2
# to restore strict dual-channel 2FA. Both channels are still REQUESTED and usable; only the threshold
# to count as approved changes.
REQUIRED_CHANNELS = int(os.getenv("TRADE_APPROVAL_REQUIRED_CHANNELS", "1"))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()




def _json_safe(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _intent_payload(intent) -> dict:
    try:
        payload = asdict(intent) if is_dataclass(intent) else dict(getattr(intent, "__dict__", {}))
    except Exception:
        payload = {}
    payload.setdefault("intent_id", str(getattr(intent, "intent_id", "")))
    payload.setdefault("correlation_id", str(getattr(intent, "correlation_id", "")))
    payload.setdefault("broker", getattr(intent, "broker", None))
    payload.setdefault("account_key", getattr(intent, "account_key", None))
    inst = getattr(intent, "instrument", None)
    payload.setdefault("instrument", {"symbol": getattr(inst, "symbol", None)})
    return json.loads(json.dumps(payload, default=_json_safe))


def _ensure_intent_persisted(cur, intent) -> None:
    iid = str(getattr(intent, "intent_id", "") or "").strip()
    if not iid:
        return
    corr = str(getattr(intent, "correlation_id", "") or "").strip() or None
    broker = getattr(intent, "broker", None) or "schwab"  # hardcode-ok: Stage 2b pilot is Schwab-only; intent.broker is the real source
    account_key = getattr(intent, "account_key", None)
    inst = getattr(intent, "instrument", None)
    symbol = (getattr(inst, "symbol", None) or "").strip().upper() or None
    payload = _intent_payload(intent)

    cur.execute("""
        INSERT INTO broker_order_intents
          (intent_id, correlation_id, broker, account_key, symbol, state, intent_json, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'PREFLIGHTED', %s::jsonb, NOW())
        ON CONFLICT (intent_id) DO UPDATE SET
          correlation_id = EXCLUDED.correlation_id,
          broker = EXCLUDED.broker,
          account_key = EXCLUDED.account_key,
          symbol = EXCLUDED.symbol,
          state = CASE
            WHEN broker_order_intents.state IN ('SUBMITTED','FILLED','CANCELLED','REJECTED')
              THEN broker_order_intents.state
            ELSE EXCLUDED.state
          END,
          intent_json = EXCLUDED.intent_json,
          updated_at = NOW()
    """, (iid, corr, broker, account_key, symbol, json.dumps(payload, default=_json_safe)))

def request_approval(intent) -> dict:
    """Create a pending 2FA approval for an intent: web row (requires TYPING THE TICKER to confirm —
    anti-fat-finger, operator-confirmed 2026-06-12) + telegram row w/ one-time code; notify operator
    with a Tailscale deep-link straight to this intent. ONE ORDER AT A TIME: while any OTHER intent
    holds an unexpired pending/confirmed approval, a new request is refused (fail closed)."""
    conn = _conn(); cur = conn.cursor()
    _ensure_intent_persisted(cur, intent)
    # one-order-at-a-time slot check (operator requirement 2026-06-12)
    cur.execute("""SELECT DISTINCT intent_id FROM trade_approvals
                   WHERE intent_id<>%s AND status IN ('pending','confirmed') AND expires_at > NOW()""",
                (intent.intent_id,))
    holders = [str(r[0]) for r in cur.fetchall()]
    if holders:
        conn.rollback()
        return {"ok": False, "reason": "one order at a time: another intent holds an active approval "
                                       "(reject it or let it expire first)", "holder_intent_ids": holders}
    code = f"{secrets.randbelow(1000000):06d}"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=TTL_MIN)
    # invalidate any prior pending approvals for this intent (one active approval set at a time)
    cur.execute("""UPDATE trade_approvals SET status='superseded'
                   WHERE intent_id=%s AND status='pending'""", (intent.intent_id,))
    ticker_phrase = (intent.instrument.symbol or "").strip().upper()
    for channel in ("web", "telegram"):
        # web row's code = the ticker the operator must TYPE (not click) in the confirm popup
        cur.execute("""INSERT INTO trade_approvals
                       (intent_id, correlation_id, channel, code, status, expires_at)
                       VALUES (%s,%s,%s,%s,'pending',%s)""",
                    (intent.intent_id, intent.correlation_id, channel,
                     code if channel == "telegram" else ticker_phrase, expires))
    conn.commit()
    _send_approval_request(intent, code)
    return {"ok": True, "intent_id": intent.intent_id, "expires_at": expires.isoformat(),
            "channels": ["web", "telegram"], "ttl_min": TTL_MIN,
            "web_confirm": "type-the-ticker required", "intent_persisted": True}


def intent_deep_link(intent_id: str) -> str | None:
    """Tailscale FQDN deep-link to the exact order item in the v3 Broker Orders tab.

    ALWAYS path form /v3/go/order/{id} — never ?tab=…&intent=… (Telegram truncates at &).
    """
    iid = str(intent_id or "").strip()
    if not iid:
        return None
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from notification_url_builder import build_broker_order_url
        url = build_broker_order_url(iid)
        if url and "/go/order/" in url and "&" not in url.split("?", 1)[0]:
            # path segment must not contain bare multi-query form
            return url
        if url and "/go/order/" in url:
            return url
    except Exception:
        pass
    host = (os.getenv("TAILSCALE_HOSTNAME") or "ms01-openclaw.tail163d14.ts.net").strip()
    # Hard fallback — still path-only, never &intent=
    return f"https://{host}/v3/go/order/{iid}"


def _load_intent_any(intent_id: str):
    """Rehydrate ANY persisted OrderIntent (not just protective) from broker_order_intents. None on miss."""
    try:
        from db_adapter import _get_conn
        from brokers.order_intent import OrderIntent
        cur = _get_conn().cursor()
        cur.execute("SELECT intent_json FROM broker_order_intents WHERE intent_id=%s", (str(intent_id),))
        r = cur.fetchone()
        if not r or not r[0]:
            return None
        payload = r[0] if isinstance(r[0], dict) else json.loads(r[0])
        return OrderIntent.from_dict(payload)
    except Exception:
        return None


def _acct_label(acct: str | None) -> str:
    """Display account for Telegram/HTML — underscores break legacy Markdown (_schwab_taxable_)."""
    return str(acct or "broker").replace("_", " ")


def _intent_qty(intent) -> float | None:
    q = getattr(getattr(intent, "quantity", None), "qty", None)
    if q is None:
        q = getattr(getattr(intent, "quantity", None), "notional", None)
    if q is None:
        q = getattr(getattr(intent, "quantity", None), "contracts", None)
    try:
        return float(q) if q is not None else None
    except Exception:
        return None


def intent_action_summary(intent) -> dict:
    """Human labels for 2FA messages: distinguish market sell-all vs stop vs trailing vs buy."""
    sym = (getattr(getattr(intent, "instrument", None), "symbol", None) or "?").upper()
    qty = _intent_qty(intent)
    qty_s = f"{qty:g}" if qty is not None else "?"
    acct = _acct_label(getattr(intent, "account_key", None) or getattr(intent, "broker", None))
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    instr = str(ev.get("instruction") or "").upper()
    ot = str(ev.get("order_type") or "").upper()
    try:
        from brokers.execution_guard import PROTECTIVE_STOP_MARKER, QUEUE_ENTRY_MARKER
        sid = getattr(getattr(intent, "meta", None), "strategy_id", None)
        is_protective = sid == PROTECTIVE_STOP_MARKER
        is_queue_entry = sid == QUEUE_ENTRY_MARKER
    except Exception:
        is_protective = False
        is_queue_entry = False

    if is_queue_entry:
        entry_px = getattr(getattr(intent, "entry", None), "limit_price", None)
        stop_px = (intent.exit_policy.stop.price if intent.exit_policy and intent.exit_policy.stop else None)
        tgt_px = (intent.exit_policy.targets[0].price if intent.exit_policy and intent.exit_policy.targets else None)
        ep = f"${float(entry_px):.2f}" if entry_px is not None else "limit"
        sp = f"${float(stop_px):.2f}" if stop_px is not None else "stop"
        tp = f"${float(tgt_px):.2f}" if tgt_px is not None else None
        risk_ps = (float(entry_px) - float(stop_px)) if entry_px is not None and stop_px is not None else None
        risk_usd = (risk_ps * float(qty)) if risk_ps is not None and qty is not None else None
        invest = (float(entry_px) * float(qty)) if entry_px is not None and qty is not None else None
        rr = None
        if risk_ps and risk_ps > 0 and tgt_px is not None and entry_px is not None:
            rr = round((float(tgt_px) - float(entry_px)) / risk_ps, 2)
        detail = f"BUY LIMIT {ep} + child STOP {sp} GTC"
        if tp:
            detail += f" + TARGET {tp} (OCO)"
        if risk_usd is not None:
            detail += f" · risk ${risk_usd:,.0f}"
        if invest is not None:
            detail += f" · invest ${invest:,.0f}"
        if rr is not None:
            detail += f" · R:R {rr}:1"
        return {
            "kind": "trade",
            "symbol": sym,
            "action": "buy",
            "action_label": "Queue entry bracket",
            "approve_btn": "Approve BUY",
            "headline": f"BUY {qty_s} sh {sym} LIMIT {ep} + STOP {sp} ({acct})",
            "detail": detail,
            "entry": entry_px,
            "stop": stop_px,
            "target": tgt_px,
            "dollar_risk": round(risk_usd, 2) if risk_usd is not None else None,
            "dollar_size": round(invest, 2) if invest is not None else None,
            "risk_reward": rr,
        }

    if is_protective and instr == "SELL":
        if ot == "MARKET":
            try:
                from brokers.protective_stop_pilot import market_tif
                tif = market_tif(qty)
            except Exception:
                tif = "DAY"
            return {
                "kind": "sell",
                "symbol": sym,
                "action": "selling",
                "action_label": "Market sell-all",
                "approve_btn": "Approve SELL",
                "headline": f"SELL {qty_s} sh {sym} @ MARKET {tif} ({acct})",
                "detail": f"Fractional OK · immediate exit · {tif} TIF",
            }
        if ot == "TRAILING_STOP":
            pct = ev.get("trail_pct")
            pct_s = f"{float(pct):g}%" if pct is not None else "trail"
            return {
                "kind": "stop",
                "symbol": sym,
                "action": "trailing stop",
                "action_label": "Trailing stop",
                "approve_btn": "Approve STOP",
                "headline": f"SELL {qty_s} sh {sym} TRAILING STOP {pct_s} GTC ({acct})",
                "detail": "Protective trailing stop · GTC",
            }
        if ot == "STOP_LIMIT":
            sp = ev.get("stop_price") or getattr(getattr(intent, "entry", None), "stop_price", None)
            sp_s = f"${float(sp):.2f}" if sp is not None else "stop"
            return {
                "kind": "stop",
                "symbol": sym,
                "action": "stop",
                "action_label": "Stop-limit",
                "approve_btn": "Approve STOP",
                "headline": f"SELL {qty_s} sh {sym} STOP-LIMIT {sp_s} GTC ({acct})",
                "detail": "Protective stop-limit · GTC",
            }
        sp = ev.get("stop_price") or getattr(getattr(intent, "entry", None), "stop_price", None)
        sp_s = f"${float(sp):.2f}" if sp is not None else "stop"
        return {
            "kind": "stop",
            "symbol": sym,
            "action": "stop",
            "action_label": "Protective stop",
            "approve_btn": "Approve STOP",
            "headline": f"SELL {qty_s} sh {sym} STOP {sp_s} GTC ({acct})",
            "detail": "Protective sell stop · GTC",
        }

    direction = getattr(getattr(intent, "direction", None), "value", "LONG")
    entry = getattr(getattr(intent, "entry", None), "method", None)
    entry_s = getattr(entry, "value", str(entry or "LIMIT"))
    return {
        "kind": "trade",
        "symbol": sym,
        "action": direction.lower(),
        "action_label": direction.title(),
        "approve_btn": "Approve",
        "headline": f"{direction} {qty_s} sh {sym} ({acct})",
        "detail": f"entry {entry_s}",
    }


def intent_action_summary_for_id(intent_id: str) -> dict:
    intent = _load_intent_any(intent_id)
    if intent is None:
        return {"kind": "unknown", "action": "order", "action_label": "Order",
                "approve_btn": "Approve", "headline": "Unknown order", "detail": ""}
    return intent_action_summary(intent)


def active_approval_detail(intent_id: str) -> dict:
    """Operator-facing owner for the one-order-at-a-time 2FA lock."""
    summ = intent_action_summary_for_id(intent_id)
    expires_at = None
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""SELECT MAX(expires_at) FROM trade_approvals
                       WHERE intent_id=%s AND status IN ('pending','confirmed')""", (intent_id,))
        r = cur.fetchone()
        expires_at = r[0] if r else None
    except Exception:
        expires_at = None
    expires_et = None
    if expires_at:
        try:
            import zoneinfo
            et = expires_at.astimezone(zoneinfo.ZoneInfo("America/New_York"))
            expires_et = et.strftime("%H:%M ET")
        except Exception:
            expires_et = str(expires_at)
    return {
        "intent_id": intent_id,
        "symbol": summ.get("symbol"),
        "action": summ.get("action"),
        "headline": summ.get("headline"),
        "detail": summ.get("detail"),
        "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else expires_at,
        "expires_et": expires_et,
    }


def _execution_notice(intent) -> str:
    """Truthful execution-gate state for THIS intent (replaces the old blanket 'DISABLED this phase' line,
    which went stale once Stage-2c protective/trailing stops were gate-removed 2026-06-19 + DB-authorized —
    telling the operator a live, enabled order is 'disabled' is the bug). Fail-safe: any uncertainty falls
    back to the conservative disabled wording. The per-order 2FA above is always the last gate regardless."""
    try:
        from brokers import execution_guard as _g
        if intent is not None and _g._is_protective_stop(intent):
            summ = intent_action_summary(intent)
            if _g._protective_unlocked():
                if summ.get("kind") == "sell":
                    return ("✅ Live SELL enabled — this market sell-all WILL submit to Schwab once you "
                            "approve (2FA above is the final gate).")
                if summ.get("action") == "trailing stop":
                    return ("✅ Live STOP enabled — this trailing stop WILL submit to Schwab once you "
                            "approve (2FA above is the final gate).")
                return ("✅ Live STOP enabled — this sell stop WILL submit to Schwab once you "
                        "approve (2FA above is the final gate).")
            return "⛔ Protective orders are currently locked (system control off)."
        if intent is not None and _g._is_options_execution(intent):
            if _g._options_unlocked() and _g._live_future_unlocked():
                return ("✅ Options execution LIVE — this order WILL submit to Schwab once approved "
                        "(2FA is the final gate).")
            return "⛔ Options execution locked — run options_pilot_arm.py --approve."
        if intent is not None and _g._live_future_unlocked():
            return "✅ Execution is LIVE — this order WILL submit once approved."
    except Exception:
        pass
    return "(Execution remains DISABLED this phase)"


def execution_notice(intent_id: str) -> str:
    """Public: the truthful execution notice for a persisted intent id (used by the telegram callback)."""
    return _execution_notice(_load_intent_any(intent_id))


def _approval_telegram_payload(intent, code: str) -> str:
    """Build plain-text body for a 2FA approval ping (routed via send_telegram)."""
    is_test = intent.instrument.symbol in ("TEST", "ZZGUARD") or (intent.meta.thesis or "").startswith("scaffold")
    link = intent_deep_link(intent.intent_id)
    summ = intent_action_summary(intent)
    sym = intent.instrument.symbol
    title = summ["action_label"].upper() + " APPROVAL" + (" — ⚠️ SCAFFOLD TEST" if is_test else "")
    notice = _execution_notice(intent)
    return (f"🔐 {title}\n\n{summ['headline']}\n{summ['detail']}\n"
            f"intent {intent.intent_id[:8]} · expires {TTL_MIN}min\nmanual fallback code: {code}\n"
            + (f"Open in Command Center:\n{link}\n" if link else "")
            + f"2nd factor: type ticker {sym} in web OR reply with code {code}\n{notice}")


def _post_telegram_approval(plain: str) -> bool:
    """Send approval message via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        from pathlib import Path as _P
        scripts_dir = str(_P(__file__).resolve().parents[1])
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        ok = bool(send_telegram(plain))
        try:
            root = str(_P(__file__).resolve().parents[2])
            if root not in sys.path:
                sys.path.insert(0, root)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="approval",
                producer="approval_service", subject_key="ops:trade_approval",
                retention_class="operational", severity="urgent",
                sanitized_body=plain[:500], short_summary=plain[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        if not ok:
            print("[approval_service] send_telegram returned False", file=sys.stderr)
        return ok
    except Exception as e:
        print(f"[approval_service] telegram send error: {e}", file=sys.stderr)
        return False


def resend_pending_telegram(intent_id: str) -> dict:
    """Re-push the Telegram approval ping for a pending intent (e.g. after a Markdown parse failure)."""
    intent = _load_intent_any(intent_id)
    if intent is None:
        return {"ok": False, "reason": "intent not found"}
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT code, status, expires_at FROM trade_approvals
                   WHERE intent_id=%s AND channel='telegram' ORDER BY id DESC LIMIT 1""", (intent_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "reason": "no telegram approval row"}
    code, status, expires = r
    if status != "pending":
        return {"ok": False, "reason": f"telegram channel not pending ({status})"}
    if expires and expires < dt.datetime.now(dt.timezone.utc):
        return {"ok": False, "reason": "approval expired"}
    plain = _approval_telegram_payload(intent, code)
    sent = _post_telegram_approval(plain)
    return {"ok": sent, "intent_id": intent_id, "code": code}


def _send_approval_request(intent, code: str) -> None:
    """Approval ping via send_telegram chokepoint; code kept as manual fallback.
    TEST-fixture intents are labeled so scaffold smoke never reads like a real plan."""
    plain = _approval_telegram_payload(intent, code)
    _post_telegram_approval(plain)
    is_test = intent.instrument.symbol in ("TEST", "ZZGUARD") or (intent.meta.thesis or "").startswith("scaffold")
    _send_approval_email(intent, code, is_test)


def _send_approval_email(intent, code: str, is_test: bool) -> None:
    """Deliver the SAME one-time code by email (operator directive 2026-06-15: 'email or telegram, either
    one'). The operator can confirm from whichever they see first — enter the code in the modal, or type
    the ticker. Best-effort: any failure is swallowed (Telegram remains the primary channel)."""
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        import email_notifier
        sym = intent.instrument.symbol
        summ = intent_action_summary(intent)
        subj = f"[Trade AI] {summ['action_label']} approval {code} — {sym}" + (" (SCAFFOLD TEST)" if is_test else "")
        body = (f"{summ['action_label']} approval requested.\n\n"
                f"{summ['headline']}\n"
                f"{summ['detail']}\n"
                f"intent {intent.intent_id[:8]} · expires {TTL_MIN} min\n\n"
                f"ONE-TIME CODE: {code}\n\n"
                f"Approve from EITHER channel — enter this code in the Command Center confirm box, "
                f"reply to the Telegram message, or type the ticker ({sym}) in the web popup. Any one is enough.")
        email_notifier.send_email(subj, body)
    except Exception:
        pass


def reject(intent_id: str) -> dict:
    """Operator reject: supersede all pending approvals for the intent."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""UPDATE trade_approvals SET status='superseded'
                   WHERE intent_id=%s AND status IN ('pending','confirmed')""", (intent_id,))
    n = cur.rowcount; conn.commit()
    return {"ok": True, "rejected_rows": n}


def confirm(intent_id: str, channel: str, code: str | None = None) -> dict:
    """Confirm one channel. telegram requires the matching one-time code; web requires the operator to
    have TYPED the ticker symbol exactly (anti-fat-finger — a click alone never confirms). Fail-closed
    on everything."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT id, code, expires_at, status FROM trade_approvals
                   WHERE intent_id=%s AND channel=%s ORDER BY id DESC LIMIT 1""", (intent_id, channel))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "reason": "no pending approval for this intent/channel"}
    aid, want_code, expires, status = r
    now = dt.datetime.now(dt.timezone.utc)
    if status != "pending":
        return {"ok": False, "reason": f"approval is {status} (single-use)"}
    if expires and now > expires:
        cur.execute("UPDATE trade_approvals SET status='expired' WHERE id=%s", (aid,)); conn.commit()
        return {"ok": False, "reason": "approval expired"}
    if channel == "telegram" and (not code or code != want_code):
        return {"ok": False, "reason": "invalid confirmation code"}
    if channel == "web" and (not code or code.strip().upper() != (want_code or "").strip().upper() or not want_code):
        return {"ok": False, "reason": "web confirmation requires typing the ticker symbol exactly"}
    cur.execute("UPDATE trade_approvals SET status='confirmed', confirmed_at=NOW() WHERE id=%s", (aid,))
    conn.commit()
    return {"ok": True, "channel": channel, "fully_approved": is_fully_approved(intent_id)}


def is_fully_approved(intent_id: str) -> bool:
    """True if at least REQUIRED_CHANNELS distinct channel(s) confirmed, unexpired, unconsumed.
    Default 1 (either web typed-ticker OR telegram code) per operator directive 2026-06-15."""
    try:
        cur = _conn().cursor()
        cur.execute("""SELECT count(DISTINCT channel) FROM trade_approvals
                       WHERE intent_id=%s AND status='confirmed'
                         AND expires_at > NOW()""", (intent_id,))
        return (cur.fetchone()[0] or 0) >= REQUIRED_CHANNELS
    except Exception:
        # Never leave the shared global connection in an aborted-transaction state — a swallowed query
        # error (e.g. a malformed intent_id) would otherwise poison it and silently fail-close every
        # subsequent gate/query on that connection. Roll back before failing closed.
        try:
            _conn().rollback()
        except Exception:
            pass
        return False   # fail closed


def consume(intent_id: str) -> bool:
    """Mark an approval set used at submission time (single-use). Burns the confirmed channel(s) AND
    supersedes any leftover *pending* rows for this intent — with single-channel approval, request_approval
    still creates both web+telegram pending rows, and the unconfirmed one would otherwise linger in
    pending and keep holding the one-order-at-a-time slot, blocking the NEXT submit. (bugfix 2026-06-15)"""
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""UPDATE trade_approvals SET status='consumed'
                       WHERE intent_id=%s AND status='confirmed'""", (intent_id,))
        n = cur.rowcount
        cur.execute("""UPDATE trade_approvals SET status='superseded'
                       WHERE intent_id=%s AND status='pending'""", (intent_id,))
        conn.commit()
        return n >= REQUIRED_CHANNELS
    except Exception:
        return False


_SUBMITTED_PILOT_STATUSES = frozenset({"submitted", "filled", "working", "accepted", "partially_filled"})


def submission_lookup(intent_id: str) -> dict | None:
    """Broker row for an intent that already reached Schwab (idempotent replay after 2FA burn)."""
    iid = str(intent_id or "").strip()
    if not iid:
        return None
    try:
        cur = _conn().cursor()
        cur.execute("""SELECT broker_order_id, status, symbol, account_key, qty, kind, updated_at
                       FROM schwab_pilot_orders
                       WHERE intent_id=%s AND broker_order_id IS NOT NULL
                       ORDER BY id DESC LIMIT 1""", (iid,))
        r = cur.fetchone()
        if not r:
            return None
        oid, st, sym, acct, qty, kind, upd = r
        if str(st or "").lower() not in _SUBMITTED_PILOT_STATUSES:
            return None
        return {"broker_order_id": str(oid), "status": str(st), "symbol": sym,
                "account_key": acct, "qty": float(qty) if qty is not None else None,
                "kind": kind, "updated_at": str(upd) if upd else None}
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
        return None


def status(intent_id: str) -> dict:
    cur = _conn().cursor()
    cur.execute("""SELECT channel, status, confirmed_at, expires_at FROM trade_approvals
                   WHERE intent_id=%s ORDER BY id DESC""", (intent_id,))
    rows = [{"channel": c, "status": st, "confirmed_at": str(ca) if ca else None,
             "expires_at": str(ex) if ex else None} for c, st, ca, ex in cur.fetchall()]
    sub = submission_lookup(intent_id)
    out = {"intent_id": intent_id, "channels": rows, "fully_approved": is_fully_approved(intent_id)}
    if sub:
        out["submitted"] = True
        out["submission"] = sub
    return out
