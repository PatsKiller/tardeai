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

TTL_MIN = int(os.getenv("TRADE_APPROVAL_TTL_MIN", "10"))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def request_approval(intent) -> dict:
    """Create a pending 2FA approval for an intent: web row + telegram row w/ one-time code; notify operator."""
    code = f"{secrets.randbelow(1000000):06d}"
    conn = _conn(); cur = conn.cursor()
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=TTL_MIN)
    # invalidate any prior pending approvals for this intent (one active approval set at a time)
    cur.execute("""UPDATE trade_approvals SET status='superseded'
                   WHERE intent_id=%s AND status='pending'""", (intent.intent_id,))
    for channel in ("web", "telegram"):
        cur.execute("""INSERT INTO trade_approvals
                       (intent_id, correlation_id, channel, code, status, expires_at)
                       VALUES (%s,%s,%s,%s,'pending',%s)""",
                    (intent.intent_id, intent.correlation_id, channel,
                     code if channel == "telegram" else None, expires))
    conn.commit()
    _send_approval_request(intent, code)
    return {"intent_id": intent.intent_id, "expires_at": expires.isoformat(),
            "channels": ["web", "telegram"], "ttl_min": TTL_MIN}


def _approval_chat() -> str | None:
    """Approval requests route to a DEDICATED chat (the operator's second account):
    env TELEGRAM_APPROVAL_CHAT_ID, else the LAST configured alert chat (secondary). Never hardcoded."""
    v = os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "").strip()
    if v:
        return v
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from tg_chat_ids import chat_ids
        ids = chat_ids()
        return ids[-1] if ids else None
    except Exception:
        return None


def _send_approval_request(intent, code: str) -> None:
    """Inline-button approval message (operator request 2026-06-11): one-tap Approve/Reject, code kept as
    manual fallback. TEST-fixture intents are labeled so scaffold smoke never reads like a real plan."""
    chat = _approval_chat()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not (chat and token):
        return
    qty = intent.quantity.qty or intent.quantity.notional or intent.quantity.contracts
    is_test = intent.instrument.symbol in ("TEST", "ZZGUARD") or (intent.meta.thesis or "").startswith("scaffold")
    text = (f"🔐 *TRADE APPROVAL REQUEST*{' — ⚠️ SCAFFOLD TEST FIXTURE' if is_test else ''}\n\n"
            f"{intent.direction.value} *{qty} sh* {intent.instrument.symbol} ({intent.broker})\n"
            f"entry {intent.entry.method.value}"
            f"{' @' + str(intent.entry.limit_price) if intent.entry.limit_price else ''}\n"
            f"intent `{intent.intent_id[:8]}` · expires {TTL_MIN}min\n"
            f"manual fallback code: `{code}`\n"
            f"_(Execution remains DISABLED this phase)_")
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


def reject(intent_id: str) -> dict:
    """Operator reject: supersede all pending approvals for the intent."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""UPDATE trade_approvals SET status='superseded'
                   WHERE intent_id=%s AND status IN ('pending','confirmed')""", (intent_id,))
    n = cur.rowcount; conn.commit()
    return {"ok": True, "rejected_rows": n}


def confirm(intent_id: str, channel: str, code: str | None = None) -> dict:
    """Confirm one channel. telegram requires the matching one-time code. Fail-closed on everything."""
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
    cur.execute("UPDATE trade_approvals SET status='confirmed', confirmed_at=NOW() WHERE id=%s", (aid,))
    conn.commit()
    return {"ok": True, "channel": channel, "fully_approved": is_fully_approved(intent_id)}


def is_fully_approved(intent_id: str) -> bool:
    """True only if BOTH channels confirmed, unexpired, unconsumed."""
    try:
        cur = _conn().cursor()
        cur.execute("""SELECT count(DISTINCT channel) FROM trade_approvals
                       WHERE intent_id=%s AND status='confirmed'
                         AND expires_at > NOW()""", (intent_id,))
        return (cur.fetchone()[0] or 0) >= 2
    except Exception:
        return False   # fail closed


def consume(intent_id: str) -> bool:
    """Mark an approval set used (would be called at submission time — single-use)."""
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""UPDATE trade_approvals SET status='consumed'
                       WHERE intent_id=%s AND status='confirmed'""", (intent_id,))
        n = cur.rowcount; conn.commit()
        return n >= 2
    except Exception:
        return False


def status(intent_id: str) -> dict:
    cur = _conn().cursor()
    cur.execute("""SELECT channel, status, confirmed_at, expires_at FROM trade_approvals
                   WHERE intent_id=%s ORDER BY id DESC""", (intent_id,))
    rows = [{"channel": c, "status": st, "confirmed_at": str(ca) if ca else None,
             "expires_at": str(ex) if ex else None} for c, st, ca, ex in cur.fetchall()]
    return {"intent_id": intent_id, "channels": rows, "fully_approved": is_fully_approved(intent_id)}
