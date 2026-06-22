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
    """Tailscale FQDN deep-link to the exact order item in the v3 Broker Orders tab. Host comes from
    env (TAILSCALE_HOSTNAME) — never hardcoded; None when unset (link simply omitted)."""
    host = os.getenv("TAILSCALE_HOSTNAME", "").strip()
    if not host:
        return None
    return f"https://{host}/v3/trading?tab=Broker+Orders&intent={intent_id}"


def _approval_chat() -> str | None:
    """Approval requests route to the PROPOSALS chat (operator clarification 2026-06-11: same account that
    receives proposal approvals/stop warnings): env TELEGRAM_APPROVAL_CHAT_ID overrides, else the FIRST
    configured chat (TRADEAI_PROPOSAL_ALERT_CHAT_ID ordering in tg_chat_ids). Never hardcoded."""
    v = os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "").strip()
    if v:
        return v
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from tg_chat_ids import chat_ids
        ids = chat_ids()
        return ids[0] if ids else None
    except Exception:
        return None


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


def _execution_notice(intent) -> str:
    """Truthful execution-gate state for THIS intent (replaces the old blanket 'DISABLED this phase' line,
    which went stale once Stage-2c protective/trailing stops were gate-removed 2026-06-19 + DB-authorized —
    telling the operator a live, enabled order is 'disabled' is the bug). Fail-safe: any uncertainty falls
    back to the conservative disabled wording. The per-order 2FA above is always the last gate regardless."""
    try:
        from brokers import execution_guard as _g
        if intent is not None and _g._is_protective_stop(intent):
            if _g._protective_unlocked():
                return ("✅ Protective/trailing stops are LIVE-ENABLED — this SELL stop WILL submit to "
                        "Schwab once approved (the 2FA above is the final gate).")
            return "⛔ Protective stops are currently locked (system control off)."
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


def _send_approval_request(intent, code: str) -> None:
    """Inline-button approval message (operator request 2026-06-11): one-tap Approve/Reject, code kept as
    manual fallback. TEST-fixture intents are labeled so scaffold smoke never reads like a real plan."""
    chat = _approval_chat()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not (chat and token):
        return
    qty = intent.quantity.qty or intent.quantity.notional or intent.quantity.contracts
    is_test = intent.instrument.symbol in ("TEST", "ZZGUARD") or (intent.meta.thesis or "").startswith("scaffold")
    link = intent_deep_link(intent.intent_id)
    text = (f"🔐 *TRADE APPROVAL REQUEST*{' — ⚠️ SCAFFOLD TEST FIXTURE' if is_test else ''}\n\n"
            f"{intent.direction.value} *{qty} sh* {intent.instrument.symbol} ({intent.broker})\n"
            f"entry {intent.entry.method.value}"
            f"{' @' + str(intent.entry.limit_price) if intent.entry.limit_price else ''}\n"
            f"intent `{intent.intent_id[:8]}` · expires {TTL_MIN}min\n"
            f"manual fallback code: `{code}`\n"
            + (f"[Open this order in Command Center]({link})\n" if link else "")
            + f"_2nd factor: web popup — you must TYPE the ticker ({intent.instrument.symbol}) to confirm_\n"
            f"_{_execution_notice(intent)}_")
    kb = {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"bkapprove:{intent.intent_id}:{code}"},
        {"text": "❌ Reject", "callback_data": f"bkreject:{intent.intent_id}"}]]}
    try:
        import requests, json as _j
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "Markdown",
                            "reply_markup": kb}, timeout=10)
    except Exception:
        pass
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
        qty = intent.quantity.qty or intent.quantity.notional or intent.quantity.contracts
        sym = intent.instrument.symbol
        subj = f"[Trade AI] Approval code {code} — {intent.direction.value} {qty} {sym}" + (" (SCAFFOLD TEST)" if is_test else "")
        body = (f"Trade approval requested.\n\n"
                f"{intent.direction.value} {qty} sh {sym} ({intent.broker})\n"
                f"entry {intent.entry.method.value}"
                f"{(' @ ' + str(intent.entry.limit_price)) if intent.entry.limit_price else ''}"
                f"{(' stop ' + str(intent.entry.stop_price)) if getattr(intent.entry, 'stop_price', None) else ''}\n"
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


def status(intent_id: str) -> dict:
    cur = _conn().cursor()
    cur.execute("""SELECT channel, status, confirmed_at, expires_at FROM trade_approvals
                   WHERE intent_id=%s ORDER BY id DESC""", (intent_id,))
    rows = [{"channel": c, "status": st, "confirmed_at": str(ca) if ca else None,
             "expires_at": str(ex) if ex else None} for c, st, ca, ex in cur.fetchall()]
    return {"intent_id": intent_id, "channels": rows, "fully_approved": is_fully_approved(intent_id)}
