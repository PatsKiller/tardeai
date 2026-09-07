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
    # T2: if Markdown parse failed the first message was NOT posted.
    # Send plaintext once. Do not send a second copy when the first succeeded.
    if not result.get("ok"):
        _tg_post("sendMessage", {
            "chat_id": chat_id,
            "reply_to_message_id": reply_to_message_id,
            "text": text,
        })


def edit_message(chat_id, message_id, text):
    """Replace a button-message's text after the action (removes the inline keyboard)."""
    _tg_post("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})


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

    # ── Guard scope approval (gapprove:<request_id> / gdeny:<request_id>) ──
    # The tap IS the authority. Telegram delivers this callback with the
    # sender's own user id from a chat already checked against the allowlist
    # above, and callbacks originate at Telegram's servers — holding the bot
    # token does not let anything fabricate one. So no code is carried or
    # needed. See scripts/lib/guard_remote_approval.settle_by_request_id.
    if action in ("gapprove", "gdeny"):
        import subprocess
        from pathlib import Path as _Path
        try:
            from scripts.lib import guard_remote_approval as _gra
        except ImportError:
            from lib import guard_remote_approval as _gra  # type: ignore

        rid = parts[1] if len(parts) > 1 else ""
        out = _gra.settle_by_request_id(
            rid, approve=(action == "gapprove"), chat_id=chat_id,
            allowed_chats=_allowed_chat_ids(),
            telegram={"message_id": message_id, "from_id": user_id,
                      "from_username": user.get("username"), "text": data},
        )
        if not out.get("ok"):
            answer_callback(cb_id, f"Not settled: {out.get('reason')}", show_alert=True)
            return
        r = out["request"]
        if action == "gdeny":
            answer_callback(cb_id, f"Denied {r['scope']}. Nothing granted.")
            return

        guard_bin = _Path(__file__).resolve().parent.parent / "bin" / "guard"
        if not guard_bin.is_file():
            answer_callback(cb_id, "Approved, but bin/guard not found", show_alert=True)
            return
        reason = f"{r['reason']} [remote_request_id={r['request_id']} chat={chat_id} via=button]"
        proc = subprocess.run(
            [str(guard_bin), "grant", r["scope"], "--for", str(int(r["seconds"])),
             "--uses", str(int(r["uses"])), "--reason", reason, "--yes"],
            capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:150]
            answer_callback(cb_id, f"Approved, grant failed: {detail}", show_alert=True)
            return
        answer_callback(cb_id,
                        f"Granted {r['scope']} for {int(r['seconds']) // 60} min "
                        f"({r['uses']} uses) — {now_short}")
        return

    # ── Broker-order 2FA buttons (bkapprove:<intent_uuid>:<code>, bkreject:<intent_uuid>) ──
    if action in ("bkapprove", "bkreject"):
        try:
            import sys as _sys, os as _os
            _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            from brokers import approval_service
            iid = parts[1] if len(parts) > 1 else ""
            if action == "bkapprove":
                code = parts[2] if len(parts) > 2 else None
                r = approval_service.confirm(iid, "telegram", code)
                if r.get("ok"):
                    full = r.get("fully_approved")
                    submit_line = ""
                    if full:
                        try:
                            from brokers import intent_submit_router as _isr
                            sub = _isr.submit_fully_approved(iid)
                            if sub.get("stage") == "submit" and sub.get("ok"):
                                oid = sub.get("broker_order_id") or (sub.get("result") or {}).get("broker_order_id")
                                submit_line = f"\n✅ LIVE order submitted · #{oid or '—'} ({sub.get('status') or 'submitted'})"
                            elif sub.get("stage") == "modify_cancel":
                                submit_line = f"\n⛔ Replace blocked — old stop not canceled: {(sub.get('error') or 'cancel failed')[:160]}"
                            elif sub.get("stage") == "submit":
                                submit_line = f"\n⛔ Submit failed: {(sub.get('error') or (sub.get('result') or {}).get('error') or 'unknown')[:160]}"
                        except Exception as se:
                            submit_line = f"\n⛔ Submit error: {str(se)[:120]}"
                    summ = approval_service.intent_action_summary_for_id(iid)
                    act = summ.get("action_label") or summ.get("action") or "order"
                    answer_callback(cb_id, f"{act} approved" +
                                    (" — submitting" if full else " — need web ticker"))
                    try:
                        _notice = approval_service.execution_notice(iid)
                    except Exception:
                        _notice = ""
                    if full and submit_line.startswith("\n✅"):
                        status_line = f"APPROVED — {act} submitting to Schwab"
                    elif full:
                        status_line = f"APPROVED — {act} ready to submit"
                    else:
                        tick = summ.get("symbol") or "ticker"
                        status_line = f"Telegram OK — type {tick} in web to finish"
                    edit_message(chat_id, message_id,
                                 f"✅ {act} approved by {user_name} {now_short}\n"
                                 f"intent {iid[:8]} · {status_line}"
                                 + (f"\n{_notice}" if _notice else "") + submit_line)
                else:
                    answer_callback(cb_id, f"Denied: {r.get('reason','')}"[:180], show_alert=True)
            else:
                r = approval_service.reject(iid)
                answer_callback(cb_id, "Approval rejected")
                edit_message(chat_id, message_id,
                             f"❌ Approval REJECTED by {user_name} {now_short}\nintent {iid[:8]}")
        except Exception as e:
            answer_callback(cb_id, f"error: {str(e)[:120]}", show_alert=True)
        return

    # ── Proposal buttons (ptapprove:123, ptreject:123, ptinfo:123) ──
    if action in ("ptapprove", "ptapprove_half", "ptapprove_2x", "ptreject", "ptinfo",
                  "ptmodify_size", "ptmodify_risk"):
        try:
            pid = int(parts[1]) if len(parts) > 1 else None
        except ValueError:
            answer_callback(cb_id, "Bad proposal ID")
            return
        if pid is None:
            answer_callback(cb_id, "Missing proposal ID")
            return

        try:
            import trade_modify as _tm
        except Exception:
            _tm = None

        if action == "ptapprove":
            result = _run_approve(pid, user_id, {})
            _post_confirmation(chat_id, message_id, result, f"APPROVED by {user_name} at {now_short}")
            if _tm:
                _tm.audit_decision("approve", proposal_id=pid, actor=user_name, channel="telegram",
                                   after={"shares": result.get("shares")}, reason="telegram approve")
            answer_callback(cb_id, _short_result(result))
        elif action == "ptapprove_half":
            result = _run_approve(pid, user_id, {"shares_multiplier": 0.5})
            _post_confirmation(chat_id, message_id, result, f"APPROVED \u00bd\u00d7 by {user_name} at {now_short}")
            if _tm:
                _tm.audit_decision("modify_size", proposal_id=pid, actor=user_name, channel="telegram",
                                   after={"shares_multiplier": 0.5, "shares": result.get("shares")}, reason="telegram \u00bd\u00d7")
            answer_callback(cb_id, _short_result(result))
        elif action == "ptapprove_2x":
            result = _run_approve(pid, user_id, {"shares_multiplier": 2.0})
            _post_confirmation(chat_id, message_id, result, f"APPROVED 2\u00d7 by {user_name} at {now_short}")
            if _tm:
                _tm.audit_decision("modify_size", proposal_id=pid, actor=user_name, channel="telegram",
                                   after={"shares_multiplier": 2.0, "shares": result.get("shares")}, reason="telegram 2\u00d7")
            answer_callback(cb_id, _short_result(result))
        elif action == "ptreject":
            result = _run_reject(pid, user_id, "telegram_inline_reject")
            _post_confirmation(chat_id, message_id, result, f"DENIED by {user_name} at {now_short}")
            if _tm:
                _tm.audit_decision("deny", proposal_id=pid, actor=user_name, channel="telegram",
                                   reason="telegram deny")
            answer_callback(cb_id, _short_result(result))
        elif action in ("ptmodify_size", "ptmodify_risk"):
            # Two-step: record what the next reply modifies, then prompt the operator to reply with a value.
            kind = "size" if action == "ptmodify_size" else "risk"
            sym = ""
            if _tm:
                try:
                    p = _tm._proposal(pid) or {}
                    sym = p.get("symbol", "")
                except Exception:
                    pass
                _tm.set_pending(chat_id, pid, kind, sym)
                _tm.audit_decision(f"modify_{kind}_requested", proposal_id=pid, actor=user_name,
                                   channel="telegram", reason="operator requested modify")
            prompt = (f"\u270f\ufe0f Reply with the new SHARE COUNT for {sym or ('#' + str(pid))} "
                      f"(whole number)." if kind == "size" else
                      f"\U0001f3af Reply with the new STOP PRICE for {sym or ('#' + str(pid))} "
                      f"(re-sizes by the same risk engine).")
            send_reply(chat_id, message_id, prompt)
            answer_callback(cb_id, "Reply with the value")
        elif action == "ptinfo":
            from proposal_alerter import build_proposal_info
            send_reply(chat_id, message_id, build_proposal_info(pid))
            answer_callback(cb_id, "Details posted")
        return

    # ── Time-exit proposal buttons (texitapprove:PID, texitreject:PID) — one-tap, paper-gated close ──
    if action in ("texitapprove", "texitreject"):
        try:
            pid = int(parts[1])
        except (ValueError, IndexError):
            answer_callback(cb_id, "Bad proposal ID")
            return
        try:
            import generate_max_hold_exit_proposals as gen
            r = gen.decide(pid, "approve" if action == "texitapprove" else "reject", operator=user_name)
        except Exception as e:
            answer_callback(cb_id, f"Failed: {str(e)[:80]}")
            return
        sym = r.get("symbol", "?")
        if action == "texitreject":
            _post_confirmation(chat_id, message_id, {"success": r.get("ok")}, f"Time-exit DISMISSED -- {sym} by {user_name} at {now_short}")
            answer_callback(cb_id, f"{sym}: dismissed")
        else:
            label = (f"Time-exit CLOSED -- {sym} by {user_name} at {now_short}" if r.get("ok")
                     else f"Time-exit FAILED -- {sym}: {str(r.get('error') or r.get('status'))[:50]}")
            _post_confirmation(chat_id, message_id, {"success": r.get("ok")}, label)
            answer_callback(cb_id, f"{sym}: closed" if r.get("ok") else f"Failed: {str(r.get('error') or r.get('status'))[:70]}")
        return

    # ── Stop decision buttons (stopexit:RTX, stophold:RTX, etc.) ──
    sym = parts[1] if len(parts) > 1 else ""

    if action == "stopexit":
        result = _handle_stop_decision(sym, "EXIT", user_id, "operator honored stop via Telegram")
        _post_confirmation(chat_id, message_id, result, f"STOP HONORED -- {sym} marked for exit by {user_name}")
        answer_callback(cb_id, f"{sym}: stop honored" if result.get("ok") else f"Failed: {result.get('error', '?')[:80]}")
        try:
            from email_notifier import send_email
            send_email(f"Trade AI: {sym} STOP HONORED — exit", f"Stop honored for {sym}.\nDecision: EXIT\nBy: {user_name}")
        except Exception:
            pass

    elif action == "stophold":
        # Handle both stophold:SYMBOL and stophold:TRADE_ID (numeric)
        hold_sym = sym
        if sym.isdigit():
            # Resolve trade ID to symbol
            try:
                from db_adapter import _get_conn
                _c = _get_conn()
                _cur = _c.cursor()
                _cur.execute("SELECT symbol FROM paper_trades WHERE id=%s", (int(sym),))
                _r = _cur.fetchone()
                hold_sym = _r[0] if _r else sym
            except Exception:
                pass
        result = _handle_stop_decision(hold_sym, "HOLD_OVERRIDE", user_id, "operator override via Telegram")
        _post_confirmation(chat_id, message_id, result, f"OVERRIDE -- {hold_sym} held by {user_name}, watching")
        answer_callback(cb_id, f"{hold_sym}: override logged")
        try:
            from email_notifier import send_email
            send_email(f"Trade AI: {hold_sym} STOP OVERRIDE — holding", f"Stop overridden for {hold_sym}.\nDecision: HOLD\nBy: {user_name}")
        except Exception:
            pass

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

    # ── Stop proximity buttons (stopout:TRADE_ID, trail:TRADE_ID:PCT, stophold:TRADE_ID) ──
    elif action == "stopout":
        # Immediate stop-out by trade ID
        try:
            trade_id = int(parts[1])
        except (IndexError, ValueError):
            answer_callback(cb_id, "Bad trade ID")
            return
        result = _execute_stop_out(trade_id, user_id, user_name)
        if result.get("ok"):
            _post_confirmation(chat_id, message_id, result,
                               f"STOPPED OUT -- {result.get('symbol', '?')} closed by {user_name} at {now_short}")
            answer_callback(cb_id, f"{result.get('symbol', '?')}: stopped out")
        else:
            send_reply(chat_id, message_id, f"Stop-out failed: {result.get('error', 'unknown')}")
            answer_callback(cb_id, f"Failed: {result.get('error', '?')[:60]}")

    elif action == "trail":
        # Switch to trailing stop at given percentage
        try:
            trade_id = int(parts[1])
            trail_pct = float(parts[2]) if len(parts) > 2 else 5.0
        except (IndexError, ValueError):
            answer_callback(cb_id, "Bad trail params")
            return
        result = _switch_to_trailing_stop(trade_id, trail_pct, user_id, user_name)
        if result.get("ok"):
            _post_confirmation(chat_id, message_id, result,
                               f"TRAILING STOP SET -- {result.get('symbol', '?')} now trailing at {trail_pct}% by {user_name}")
            answer_callback(cb_id, f"{result.get('symbol', '?')}: trail {trail_pct}%")
        else:
            send_reply(chat_id, message_id, f"Trail switch failed: {result.get('error', 'unknown')}")
            answer_callback(cb_id, f"Failed: {result.get('error', '?')[:60]}")

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

            # Email confirmation
            try:
                from email_notifier import notify_approval_result
                notify_approval_result(
                    result.get("symbol", p["symbol"]), result.get("shares", eff_shares),
                    result.get("entry", float(p.get("proposed_entry") or 0)),
                    result.get("stop", float(p.get("proposed_stop") or 0)),
                    result.get("target", float(p.get("proposed_target1") or 0)),
                    result.get("risk_gate", "?"), alpaca_status, broker_order_id or "")
            except Exception:
                pass

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
        try:
            from stop_change_audit import log_stop_change
            log_stop_change(conn, tid, symbol, old_stop, new_stop,
                            change_type='manual_operator', source='telegram_callback',
                            reason=f'operator widen {pct}%')
        except Exception:
            pass
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


def _execute_stop_out(trade_id: int, user_id: str, user_name: str) -> dict:
    """Immediately close a paper trade at market. Called from stop proximity alert."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return {"ok": False, "error": "no DB connection"}

        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol, strategy_id, entry_price, stop_loss, current_price, status,
                   shares, dollar_risk, entry_time, created_at
            FROM paper_trades WHERE id = %s
        """, (trade_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"trade #{trade_id} not found"}

        cols = [d[0] for d in cur.description]
        trade = dict(zip(cols, row))

        if trade["status"] != "open":
            return {"ok": False, "error": f"trade #{trade_id} status is {trade['status']}, not open",
                    "symbol": trade["symbol"]}

        symbol = trade["symbol"]
        exit_price = float(trade["current_price"] or trade["stop_loss"] or 0)
        entry_price = float(trade["entry_price"] or 0)
        shares = int(trade.get("shares") or 0)
        stop_loss = float(trade["stop_loss"]) if trade.get("stop_loss") else None
        dollar_risk = float(trade["dollar_risk"]) if trade.get("dollar_risk") else None
        pnl = round((exit_price - entry_price) * shares, 2) if entry_price and shares else 0
        pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price > 0 else 0
        r_mult = None
        if dollar_risk and dollar_risk > 0:
            r_mult = round(pnl / dollar_risk, 3)
        elif stop_loss and entry_price and abs(entry_price - stop_loss) > 0:
            r_mult = round((exit_price - entry_price) / abs(entry_price - stop_loss), 3)
        hold_min = None
        entry_time = trade.get("entry_time") or trade.get("created_at")
        if entry_time:
            try:
                from datetime import datetime as _dt2, timezone as _tz2
                _now2 = _dt2.now(_tz2.utc)
                _et2 = entry_time.replace(tzinfo=_tz2.utc) if entry_time.tzinfo is None else entry_time
                hold_min = round((_now2 - _et2).total_seconds() / 60, 1)
            except Exception:
                pass
        verdict = 'WIN' if pnl > 0 else ('LOSS' if pnl < 0 else 'BREAKEVEN')

        # Close the trade
        cur.execute("""
            UPDATE paper_trades
            SET status = 'closed', lifecycle_state = 'closed',
                exit_price = %s, exit_reason = 'operator_stop_out',
                exit_time = NOW(), closed_at = NOW(),
                pnl = %s, pnl_pct = %s, r_multiple = COALESCE(%s, r_multiple),
                hold_time_min = COALESCE(%s, hold_time_min),
                outcome_verdict = %s, decision_state = 'OPERATOR_STOP_OUT'
            WHERE id = %s
        """, (exit_price, pnl, pnl_pct, r_mult, hold_min, verdict, trade_id))

        # Log the risk action
        cur.execute("""
            INSERT INTO paper_trade_risk_actions (paper_trade_id, symbol, action_type, old_value, new_value,
                                                  trigger_price, trigger_reason)
            VALUES (%s, %s, 'operator_stop_out', %s, %s, %s, %s)
        """, (trade_id, symbol, trade["stop_loss"], exit_price, exit_price,
              f"operator {user_name} stop-out via Telegram"))

        conn.commit()

        # Submit close order to Alpaca if applicable
        try:
            _close_alpaca_position(conn, trade)
        except Exception as e:
            log.warning(f"Alpaca close failed for {symbol}: {e}")

        return {"ok": True, "symbol": symbol, "exit_price": exit_price,
                "pnl": round(pnl, 2), "trade_id": trade_id}

    except Exception as e:
        log.error(f"Stop-out failed for trade #{trade_id}: {e}")
        return {"ok": False, "error": str(e)[:200]}


def _switch_to_trailing_stop(trade_id: int, trail_pct: float, user_id: str, user_name: str) -> dict:
    """Switch a trade from fixed stop to trailing stop at trail_pct%."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return {"ok": False, "error": "no DB connection"}

        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol, strategy_id, entry_price, stop_loss, current_price, status
            FROM paper_trades WHERE id = %s
        """, (trade_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"trade #{trade_id} not found"}

        cols = [d[0] for d in cur.description]
        trade = dict(zip(cols, row))

        if trade["status"] != "open":
            return {"ok": False, "error": f"trade #{trade_id} not open",
                    "symbol": trade["symbol"]}

        symbol = trade["symbol"]
        price = float(trade["current_price"] or trade["entry_price"] or 0)
        old_stop = float(trade["stop_loss"] or 0)

        # Calculate new trailing stop: trail_pct% below current high (use current price as baseline)
        new_stop = round(price * (1 - trail_pct / 100), 2)

        # Only move stop UP (never widen risk)
        if new_stop <= old_stop:
            new_stop = old_stop

        cur.execute("""
            UPDATE paper_trades
            SET stop_loss = %s, decision_state = 'TRAILING_STOP_ACTIVE'
            WHERE id = %s
        """, (new_stop, trade_id))

        cur.execute("""
            INSERT INTO paper_trade_risk_actions (paper_trade_id, symbol, action_type, old_value, new_value,
                                                  trigger_price, trigger_reason)
            VALUES (%s, %s, 'trailing_stop_switch', %s, %s, %s, %s)
        """, (trade_id, symbol, old_stop, new_stop, price,
              f"operator {user_name} switched to {trail_pct}% trail via Telegram"))

        conn.commit()

        # Update Alpaca stop order if applicable
        try:
            from open_trade_monitor import _update_stop_on_alpaca
            _update_stop_on_alpaca(conn, trade, new_stop)
        except Exception as e:
            log.warning(f"Alpaca stop update failed for {symbol}: {e}")

        return {"ok": True, "symbol": symbol, "old_stop": old_stop,
                "new_stop": new_stop, "trail_pct": trail_pct, "trade_id": trade_id}

    except Exception as e:
        log.error(f"Trail switch failed for trade #{trade_id}: {e}")
        return {"ok": False, "error": str(e)[:200]}


def _close_alpaca_position(conn, trade):
    """Submit a close order to Alpaca for the given trade."""
    symbol = trade.get("symbol")
    if not symbol:
        return
    try:
        import requests
        key = os.environ.get("ALPACA_API_KEY", "")
        secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            return
        base = "https://paper-api.alpaca.markets"
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        resp = requests.delete(f"{base}/v2/positions/{symbol}", headers=headers, timeout=10)
        if resp.ok:
            log.info(f"Alpaca position closed for {symbol}")
        else:
            log.warning(f"Alpaca close {symbol}: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        log.warning(f"Alpaca close {symbol}: {e}")
