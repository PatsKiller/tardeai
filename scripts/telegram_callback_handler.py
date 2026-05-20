#!/usr/bin/env python3
"""telegram_callback_handler.py — Handle inline button callbacks for proposal alerts.

Processes callback_query from Telegram for proposal approve/reject/info buttons.
All actions route Telegram → bot poll → MS-01. No inbound HTTP required.

Paper mode only. No live trading.
"""
import json, logging, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger(__name__)


def _token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not t:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                t = line.split("=", 1)[1].strip()
    return t


def _allowed_chat_ids():
    chats = set()
    g = os.environ.get("TELEGRAM_PROPOSAL_DECISIONS_CHAT_ID", "").strip()
    if g:
        chats.add(g)
    std = os.environ.get("TELEGRAM_CHAT_ID", "")
    for c in std.split(","):
        if c.strip():
            chats.add(c.strip())
    return chats


def _tg_post(method, data):
    """POST to Telegram API."""
    import urllib.request
    token = _token()
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        log.error(f"Telegram {method} failed: {e}")
        return {}


def answer_callback(cb_id, text, show_alert=False):
    _tg_post("answerCallbackQuery", {
        "callback_query_id": cb_id,
        "text": text[:200],
        "show_alert": show_alert,
    })


def send_reply(chat_id, reply_to_message_id, text):
    _tg_post("sendMessage", {
        "chat_id": chat_id,
        "reply_to_message_id": reply_to_message_id,
        "text": text,
        "parse_mode": "Markdown",
    })


def handle_callback_query(cb):
    """Main callback handler for proposal inline buttons."""
    cb_id = cb["id"]
    data = cb.get("data", "")
    user = cb.get("from", {})
    user_id = str(user.get("id", ""))
    user_name = user.get("first_name", "operator")
    chat_id = str(cb["message"]["chat"]["id"])
    message_id = cb["message"]["message_id"]

    if chat_id not in _allowed_chat_ids():
        answer_callback(cb_id, "Not authorized", show_alert=True)
        return

    if ":" not in data:
        answer_callback(cb_id, "Invalid action")
        return

    action, pid_str = data.split(":", 1)
    try:
        pid = int(pid_str)
    except ValueError:
        answer_callback(cb_id, "Bad proposal ID")
        return

    now_short = datetime.now().strftime("%H:%M ET")

    if action == "ptapprove":
        result = _run_approve(pid, user_id, {})
        _post_confirmation(chat_id, message_id, result, f"APPROVED by {user_name} at {now_short}")
        answer_callback(cb_id, _short_result(result))

    elif action == "ptapprove_half":
        result = _run_approve(pid, user_id, {"shares_multiplier": 0.5})
        _post_confirmation(chat_id, message_id, result, f"APPROVED \u00bd\u00d7 by {user_name} at {now_short}")
        answer_callback(cb_id, _short_result(result))

    elif action == "ptapprove_2x":
        result = _run_approve(pid, user_id, {"shares_multiplier": 2.0})
        _post_confirmation(chat_id, message_id, result, f"APPROVED 2\u00d7 by {user_name} at {now_short}")
        answer_callback(cb_id, _short_result(result))

    elif action == "ptreject":
        result = _run_reject(pid, user_id, "telegram_inline_reject")
        _post_confirmation(chat_id, message_id, result, f"REJECTED by {user_name} at {now_short}")
        answer_callback(cb_id, _short_result(result))

    elif action == "ptinfo":
        from proposal_alerter import build_proposal_info
        info_text = build_proposal_info(pid)
        send_reply(chat_id, message_id, info_text)
        answer_callback(cb_id, "Details posted")

    else:
        answer_callback(cb_id, f"Unknown action: {action}")


def _run_approve(pid, user_id, overrides):
    """Approve a proposal with optional overrides. Re-uses existing approve_proposal."""
    try:
        from paper_trade_logger import approve_proposal
        import psycopg2.extras
        from db_adapter import _get_conn

        # Fetch proposal for override calculation
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM paper_trade_proposals WHERE id=%s", (pid,))
        p = cur.fetchone()
        conn.close()

        if not p:
            return {"ok": False, "error": f"proposal #{pid} not found"}
        if p["status"] != "PENDING":
            return {"ok": False, "symbol": p["symbol"], "error": f"status is {p['status']}, not PENDING"}

        # Calculate effective values
        eff_shares = int(p.get("proposed_shares") or 0)
        if "shares" in overrides:
            eff_shares = int(overrides["shares"])
        elif "shares_multiplier" in overrides:
            eff_shares = max(1, int(eff_shares * float(overrides["shares_multiplier"])))

        override_kwargs = {}
        if eff_shares != int(p.get("proposed_shares") or 0):
            override_kwargs["override_shares"] = eff_shares
        if "target" in overrides:
            override_kwargs["override_target"] = float(overrides["target"])
        if "stop" in overrides:
            override_kwargs["override_stop"] = float(overrides["stop"])

        # Store override payload
        if overrides:
            try:
                conn2 = _get_conn()
                cur2 = conn2.cursor()
                cur2.execute("UPDATE paper_trade_proposals SET override_payload=%s, approved_by=%s WHERE id=%s",
                             (json.dumps(overrides), user_id, pid))
                conn2.commit()
                conn2.close()
            except Exception:
                pass

        result = approve_proposal(pid, **override_kwargs)
        if result.get("success"):
            return {
                "ok": True,
                "symbol": result.get("symbol", p["symbol"]),
                "shares": result.get("shares", eff_shares),
                "entry_price": result.get("entry", float(p.get("proposed_entry") or 0)),
                "stop_price": result.get("stop", float(p.get("proposed_stop") or 0)),
                "target_price": result.get("target", float(p.get("proposed_target1") or 0)),
                "risk_gate_decision": result.get("risk_gate", "?"),
            }
        return {"ok": False, "symbol": p["symbol"], "error": result.get("message", "Approval failed")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _run_reject(pid, user_id, reason):
    """Reject a proposal."""
    try:
        from paper_trade_logger import reject_proposal
        result = reject_proposal(pid, reason)
        if result.get("success"):
            return {"ok": True, "symbol": result.get("symbol", "?"), "message": result.get("message", "Rejected")}
        return {"ok": False, "error": result.get("message", "Rejection failed")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _post_confirmation(chat_id, original_msg_id, result, label):
    sym = result.get("symbol", "?")
    if result.get("ok"):
        body = f"\u2014 *{label}*\n"
        if result.get("shares"):
            body += (f"{sym}: shares={result['shares']} "
                     f"entry=${result.get('entry_price', 0):.2f} "
                     f"stop=${result.get('stop_price', 0):.2f} "
                     f"target=${result.get('target_price', 0):.2f}\n"
                     f"Risk gate: {result.get('risk_gate_decision', '?')}")
        else:
            body += f"{sym}: {result.get('message', 'done')}"
    else:
        body = f"\u2014 *{label} FAILED*: {result.get('error', 'unknown')}"
    send_reply(chat_id, original_msg_id, body)


def _short_result(result):
    if result.get("ok"):
        return f"{result.get('symbol', '?')} OK"
    return f"Failed: {result.get('error', 'unknown')[:100]}"


def resolve_proposal_from_reply(chat_id, reply_msg_id):
    """Look up proposal_id from a replied-to message."""
    if not reply_msg_id:
        return None
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT proposal_id FROM telegram_proposal_messages WHERE chat_id=%s AND message_id=%s",
            (str(chat_id), int(reply_msg_id)),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def parse_pt_command(text, pid_from_reply=None):
    """Parse /ptapprove or /ptreject with optional overrides."""
    overrides = {}
    parts = text.split()
    pid = pid_from_reply

    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.lower().strip()
            v = v.strip()
            try:
                if k == "shares":
                    overrides["shares"] = int(v)
                elif k in ("target", "stop"):
                    overrides[k] = float(v)
                elif k == "multiplier":
                    overrides["shares_multiplier"] = float(v)
            except ValueError:
                pass
        elif part.isdigit() and pid is None:
            pid = int(part)

    return pid, overrides
