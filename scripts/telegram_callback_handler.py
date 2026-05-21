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
    g = os.environ.get("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "").strip()
    if g:
        chats.add(g)
    std = os.environ.get("TELEGRAM_CHAT_ID", "")
    for c in std.split(","):
        if c.strip():
            chats.add(c.strip())
    return chats


def _tg_post(method, data):
    """POST to Telegram API."""
    import urllib.request, urllib.error
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
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        log.error(f"Telegram {method} failed: {e} body={body[:300]}")
        return {"ok": False, "error": body}
    except Exception as e:
        log.error(f"Telegram {method} failed: {e}")
        return {"ok": False, "error": str(e)}


def answer_callback(cb_id, text, show_alert=False):
    _tg_post("answerCallbackQuery", {
        "callback_query_id": cb_id,
        "text": text[:200],
        "show_alert": show_alert,
    })


def send_reply(chat_id, reply_to_message_id, text):
    result = _tg_post("sendMessage", {
        "chat_id": chat_id,
        "reply_to_message_id": reply_to_message_id,
        "text": text,
        "parse_mode": "Markdown",
    })
    # Retry without Markdown if parse failed
    if not result.get("ok"):
        _tg_post("sendMessage", {
            "chat_id": chat_id,
            "reply_to_message_id": reply_to_message_id,
            "text": text,
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

    parts = data.split(":")
    action = parts[0]
    now_short = datetime.now().strftime("%H:%M ET")

    # ── Proposal buttons (ptapprove:123, ptreject:123, ptinfo:123) ──
    if action in ("ptapprove", "ptapprove_half", "ptapprove_2x", "ptreject", "ptinfo"):
        try:
            pid = int(parts[1]) if len(parts) > 1 else None
        except ValueError:
            answer_callback(cb_id, "Bad proposal ID")
            return
        if pid is None:
            answer_callback(cb_id, "Missing proposal ID")
            return

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
            send_reply(chat_id, message_id, build_proposal_info(pid))
            answer_callback(cb_id, "Details posted")
        return

    # ── Stop decision buttons (stopexit:RTX, stophold:RTX, etc.) ──
    sym = parts[1] if len(parts) > 1 else ""

    if action == "stopexit":
        result = _handle_stop_decision(sym, "EXIT", user_id, "operator honored stop via Telegram")
        _post_confirmation(chat_id, message_id, result, f"STOP HONORED \u2014 {sym} marked for exit by {user_name}")
        answer_callback(cb_id, f"{sym}: stop honored" if result.get("ok") else f"Failed: {result.get('error', '?')[:80]}")

    elif action == "stophold":
        result = _handle_stop_decision(sym, "HOLD_OVERRIDE", user_id, "operator override via Telegram")
        _post_confirmation(chat_id, message_id, result, f"OVERRIDE \u2014 {sym} held by {user_name}, watching")
        answer_callback(cb_id, f"{sym}: override logged")

    elif action == "stopdelay":
        mins = int(parts[2]) if len(parts) > 2 else 30
        result = _handle_stop_snooze(sym, mins, user_id)
        _post_confirmation(chat_id, message_id, result, f"POSTPONED \u2014 {sym} snoozed {mins} min")
        answer_callback(cb_id, f"{sym}: snoozed {mins}m")

    elif action == "stoptighten":
        send_reply(chat_id, message_id, f"Reply `/stopset {sym} stop=<price>` to set the new stop level")
        answer_callback(cb_id, "Reply with new stop level")

    elif action == "stoploosen":
        pct = float(parts[2]) if len(parts) > 2 else 5.0
        result = _handle_stop_loosen(sym, pct, user_id)
        _post_confirmation(chat_id, message_id, result, f"STOP LOOSENED \u2014 {sym} stop moved down {pct}%")
        answer_callback(cb_id, f"{sym}: stop loosened {pct}%")

    elif action == "stopinfo":
        from stop_alert_assembler import assemble_stop_alert_data
        data = assemble_stop_alert_data(sym)
        if data:
            info = _build_stop_info(data)
        else:
            info = f"Could not load context for {sym}"
        send_reply(chat_id, message_id, info)
        answer_callback(cb_id, "Context posted")

    else:
        answer_callback(cb_id, f"Unknown: {action}")


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
            # Instant execution: submit to Alpaca paper
            alpaca_status = "not_attempted"
            broker_order_id = None
            try:
                from proposal_paper_submitter import submit_paper
                from session13_db import get_conn as _get_sub_conn
                sub_conn = _get_sub_conn()
                if sub_conn:
                    alpaca_result = submit_paper(sub_conn, pid, dry_run=False)
                    sub_conn.close()
                    alpaca_status = alpaca_result.get("status", "unknown")
                    broker_order_id = alpaca_result.get("order_id")
                    log.info(f"Telegram approve → Alpaca: {alpaca_status} order={broker_order_id}")
            except Exception as ae:
                alpaca_status = f"error: {ae}"
                log.error(f"Telegram approve → Alpaca failed: {ae}")

            return {
                "ok": True,
                "symbol": result.get("symbol", p["symbol"]),
                "shares": result.get("shares", eff_shares),
                "entry_price": result.get("entry", float(p.get("proposed_entry") or 0)),
                "stop_price": result.get("stop", float(p.get("proposed_stop") or 0)),
                "target_price": result.get("target", float(p.get("proposed_target1") or 0)),
                "risk_gate_decision": result.get("risk_gate", "?"),
                "alpaca_status": alpaca_status,
                "broker_order_id": broker_order_id,
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
    # Use plain text to avoid Markdown parse errors with special chars
    if result.get("ok"):
        body = f"{label}\n"
        if result.get("shares"):
            body += (f"{sym}: shares={result['shares']} "
                     f"entry=${result.get('entry_price', 0):.2f} "
                     f"stop=${result.get('stop_price', 0):.2f} "
                     f"target=${result.get('target_price', 0):.2f}\n"
                     f"Risk gate: {result.get('risk_gate_decision', '?')}")
            if result.get("alpaca_status"):
                body += f"\nAlpaca: {result['alpaca_status']}"
                if result.get("broker_order_id"):
                    body += f" (order {result['broker_order_id'][:12]}...)"
        else:
            body += f"{sym}: {result.get('message', 'done')}"
    else:
        body = f"{label} FAILED: {result.get('error', 'unknown')}"
    # Send without Markdown to avoid parse errors
    _tg_post("sendMessage", {
        "chat_id": chat_id,
        "reply_to_message_id": original_msg_id,
        "text": body,
    })


def _short_result(result):
    if result.get("ok"):
        return f"{result.get('symbol', '?')} OK"
    return f"Failed: {result.get('error', 'unknown')[:100]}"


def _handle_stop_decision(symbol, decision, user_id, notes=""):
    """Record a stop decision (EXIT or HOLD_OVERRIDE). Paper mode only."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""INSERT INTO stop_decisions (symbol, decision, decided_by, decided_at, notes)
            VALUES (%s, %s, %s, NOW(), %s)""", (symbol, decision, user_id, notes))
        conn.commit()
        conn.close()
        return {"ok": True, "symbol": symbol, "decision": decision, "message": decision}
    except Exception as e:
        return {"ok": False, "symbol": symbol, "error": str(e)[:200]}


def _handle_stop_snooze(symbol, minutes, user_id):
    """Snooze stop alert for N minutes."""
    try:
        from db_adapter import _get_conn
        from datetime import timedelta
        snooze_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""INSERT INTO stop_snooze (symbol, snoozed_until, snoozed_by, created_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (symbol) DO UPDATE SET snoozed_until=%s, snoozed_by=%s""",
            (symbol, snooze_until, user_id, snooze_until, user_id))
        conn.commit()
        conn.close()
        return {"ok": True, "symbol": symbol, "message": f"snoozed until {snooze_until.strftime('%H:%M UTC')}"}
    except Exception as e:
        return {"ok": False, "symbol": symbol, "error": str(e)[:200]}


def _handle_stop_loosen(symbol, pct, user_id):
    """Loosen stop by pct%. Updates paper_trades stop_loss."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, stop_loss FROM paper_trades WHERE symbol=%s AND status='open' LIMIT 1", (symbol,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "symbol": symbol, "error": "no open paper trade found"}
        tid, old_stop = row[0], float(row[1])
        new_stop = round(old_stop * (1 - pct / 100), 2)
        cur.execute("UPDATE paper_trades SET stop_loss=%s WHERE id=%s", (new_stop, tid))
        conn.commit()
        conn.close()
        return {"ok": True, "symbol": symbol, "message": f"stop ${old_stop:.2f} \u2192 ${new_stop:.2f}"}
    except Exception as e:
        return {"ok": False, "symbol": symbol, "error": str(e)[:200]}


def _build_stop_info(data):
    """Extended context for the More Context button."""
    sym = data["symbol"]
    rsi = data.get("rsi")
    pnl = data.get("current_pnl_dollars")
    regime = (data.get("regime_label") or "unknown").upper().replace("_", " ")
    heat = data.get("portfolio_heat_pct", 0)
    n = data.get("portfolio_triggered_count", 0)
    sector = data.get("sector_note", "")
    tax = data.get("tax_note", "")

    lines = [f"*Extended Context \u2014 {sym}*", ""]
    if rsi:
        rsi_note = "(OVERSOLD)" if rsi < 30 else "(NEUTRAL)" if rsi < 60 else "(ELEVATED)"
        lines.append(f"RSI: {rsi:.0f} {rsi_note}")
    if pnl is not None:
        lines.append(f"Unrealized: {'${:,.0f}'.format(pnl)} {'LOSS' if pnl < 0 else 'GAIN'}")
    lines += ["", f"Regime: {regime}", f"Heat: {heat:.1f}%", f"Triggered: {n}"]
    if sector:
        lines += ["", f"Sector: {sector}"]
    if tax:
        lines.append(f"Tax: {tax}")
    lines += ["", "Commands:",
              f"  `/stopexit {sym}` \u2014 honor stop",
              f"  `/stophold {sym}` \u2014 override, keep holding",
              f"  `/stopdelay {sym} 30` \u2014 snooze 30 min"]
    return "\n".join(lines)


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
