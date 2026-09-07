#!/usr/bin/env python3
"""run_telegram_callback_poller.py — Poll Telegram for callback queries and commands.

Runs as a long-poll loop (25s timeout per poll). Processes:
- Inline button callbacks (approve/reject/half/2x/info)
- /ptapprove, /ptreject, /ptpending, /ptstatus commands
- Stop confirmation replies

Designed to run as a persistent background process or frequent cron.
Uses flock to prevent duplicate instances.

Paper mode only. No live trading.
"""
import json, logging, os, sys, time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [tg-poller] %(message)s")
log = logging.getLogger(__name__)

OFFSET_FILE = PROJECT_ROOT / "data" / "portfolios" / "state" / ".telegram_callback_offset"


def _inbound_api():
    """Lazy import of the gateway inbound half (Wave C).

    Returns a dict of callables, or None when the gateway package is absent
    (the poller then degrades to the legacy file-offset path so it never dies
    on an import).
    """
    try:
        from scripts.lib.comms.inbound import (  # noqa: F401
            build_inbound_event,
            claim_update,
            commit_checkpoint,
            get_checkpoint_offset,
            quarantine_callback,
        )
        from scripts.lib.comms.client import publish_communication
        return {
            "build_inbound_event": build_inbound_event,
            "claim_update": claim_update,
            "commit_checkpoint": commit_checkpoint,
            "get_checkpoint_offset": get_checkpoint_offset,
            "quarantine_callback": quarantine_callback,
            "publish_communication": publish_communication,
        }
    except Exception:
        return None


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _get_offset():
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset):
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))


def _allowed_chats():
    chats = set()
    g = os.environ.get("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "").strip()
    if g:
        chats.add(g)
    std = os.environ.get("TELEGRAM_CHAT_ID", "")
    for c in std.split(","):
        if c.strip():
            chats.add(c.strip())
    return chats


def poll_once(timeout=25):
    """Single long-poll iteration. Returns number of updates processed."""
    import urllib.request
    token = _token()
    if not token:
        log.error("No TELEGRAM_BOT_TOKEN")
        return 0

    inbound = _inbound_api()
    if inbound is not None:
        # Wave C: single-consumer durable checkpoint. The offset is advanced only
        # after the inbound CommunicationEvent is persisted, never before.
        offset = inbound["get_checkpoint_offset"]()
    else:
        offset = _get_offset()
    from urllib.parse import urlencode
    params = urlencode({
        "offset": offset + 1,
        "timeout": timeout,
        "allowed_updates": json.dumps(["callback_query", "message"]),
    })
    url = f"https://api.telegram.org/bot{token}/getUpdates?{params}"

    try:
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout + 10)
        data = json.loads(resp.read())
    except Exception as e:
        log.error(f"getUpdates failed: {e}")
        return 0

    if not data.get("ok"):
        return 0

    results = data.get("result", [])
    if not results:
        return 0

    allowed = _allowed_chats()
    processed = 0

    for update in results:
        uid = update.get("update_id")

        if inbound is not None:
            # Replay denial: skip updates already committed by a prior poll.
            claim = inbound["claim_update"](uid)
            if claim.already_processed:
                continue
            # Persist a canonical INBOUND event before business processing (C3).
            try:
                event = inbound["build_inbound_event"](update)
                published = inbound["publish_communication"](event)
            except Exception as e:
                log.error(f"inbound event persist failed: {e}")
                published = None
            if published is None or not getattr(published, "ok", False):
                # Unresolvable update — quarantine it and do NOT advance the
                # checkpoint, so it is re-delivered rather than silently dropped.
                try:
                    inbound["quarantine_callback"](
                        "inbound_persist_failed",
                        provider_coordinates={"update_id": uid},
                        update_id=uid,
                    )
                except Exception:
                    pass
                continue
        else:
            _save_offset(uid)

        # Handle callback queries (inline button presses)
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
            if chat_id in allowed:
                try:
                    from telegram_callback_handler import handle_callback_query
                    handle_callback_query(cb)
                    processed += 1
                    log.info(f"callback: {cb.get('data', '?')} from chat={chat_id}")
                except Exception as e:
                    log.error(f"callback error: {e}")
            if inbound is not None:
                inbound["commit_checkpoint"](uid)
            continue

        # Handle messages (commands)
        msg = update.get("message", {})
        if not msg:
            if inbound is not None:
                inbound["commit_checkpoint"](uid)
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if chat_id not in allowed or not text:
            if inbound is not None:
                inbound["commit_checkpoint"](uid)
            continue

        # Route all recognized commands
        lower = text.lower()
        handled = False
        # Proposal commands
        if lower.startswith("/ptapprove") or lower.startswith("/ptreject") or \
           lower.startswith("/ptpending") or lower.startswith("/ptstatus"):
            try:
                _handle_proposal_command(msg, text, chat_id)
                handled = True
            except Exception as e:
                log.error(f"command error: {e}")
        # Stop decision commands
        elif lower.startswith("/stopexit") or lower.startswith("/stophold") or \
             lower.startswith("/stopdelay") or lower.startswith("/stopset"):
            try:
                _handle_stop_command(msg, text, chat_id)
                handled = True
            except Exception as e:
                log.error(f"stop command error: {e}")
        # Paper status shortcut
        elif lower in ("paper status", "/paper status", "paper pending", "/paper pending"):
            try:
                _handle_proposal_command(msg, "/ptpending", chat_id)
                handled = True
            except Exception as e:
                log.error(f"paper status error: {e}")
        # ATM commands
        elif lower.startswith("/atm"):
            try:
                _handle_atm_command(msg, text, chat_id)
                handled = True
            except Exception as e:
                log.error(f"atm command error: {e}")
        # Guard scope approval — operator answers a /approve or /deny code.
        # Placed BEFORE the Schwab branch deliberately: that branch matches the
        # bare substring "code=" anywhere in the message, which is broad enough
        # to swallow a message that merely mentions a code.
        # LLM spend caps. There is no admin page for these anywhere — not in the
        # Command Center, not in api_v2 — so before this the only way to change a
        # cap was a hand-written UPDATE against production, which on 2026-09-06
        # promptly left the registry and the database disagreeing.
        elif lower.startswith("/caps") or lower.startswith("/cap "):
            try:
                _handle_llm_caps(msg, text, chat_id)
                handled = True
            except Exception as e:
                log.error(f"llm caps command error: {e}")
        elif lower.startswith("/approve") or lower.startswith("/deny"):
            try:
                _handle_guard_approval(msg, text, chat_id)
                handled = True
            except Exception as e:
                log.error(f"guard approval error: {e}")
        # Schwab OAuth callback — operator pastes the 127.0.0.1?code=... URL
        elif "127.0.0.1?code=" in text or "code=" in text.lower():
            try:
                _handle_schwab_callback(msg, text, chat_id)
                handled = True
            except Exception as e:
                log.error(f"schwab callback error: {e}")

        if inbound is not None:
            # The inbound event is persisted; advance the durable checkpoint so
            # a crash or a replayed poll does not re-deliver the same update.
            inbound["commit_checkpoint"](uid)

        if handled:
            processed += 1
            log.info(f"command: {text[:40]} from chat={chat_id}")

    return processed


def _handle_proposal_command(msg, text, chat_id):
    """Route /pt* commands through the command handler."""
    import urllib.request
    token = _token()
    lower = text.lower()
    message_id = msg.get("message_id")

    # Resolve proposal ID from reply context
    reply_to = msg.get("reply_to_message")
    reply_msg_id = reply_to.get("message_id") if reply_to else None
    pid_from_reply = None
    if reply_msg_id:
        from telegram_callback_handler import resolve_proposal_from_reply
        pid_from_reply = resolve_proposal_from_reply(chat_id, reply_msg_id)

    response = None

    if lower.startswith("/ptpending"):
        from telegram_callback_handler import _tg_post
        # Use the existing pending handler
        try:
            from paper_trade_logger import get_pending_proposals
            proposals = get_pending_proposals()
            if not proposals:
                response = "No PENDING proposals."
            else:
                lines = [f"*PENDING proposals ({len(proposals)}):*\n"]
                for p in proposals[:10]:
                    lines.append(
                        f"`#{p['id']}` *{p['symbol']}* `{p.get('strategy_id', '?')}` "
                        f"${float(p.get('proposed_entry', 0)):.2f} "
                        f"{p.get('proposed_shares', 0)}sh")
                response = "\n".join(lines)
        except Exception as e:
            response = f"Error: {e}"

    elif lower.startswith("/ptstatus"):
        import re
        m = re.search(r'/ptstatus\s+(\d+)', text)
        if m:
            from proposal_alerter import build_proposal_info
            response = build_proposal_info(int(m.group(1)))
        else:
            response = "Usage: `/ptstatus 1234`"

    elif lower.startswith("/ptapprove"):
        from telegram_callback_handler import parse_pt_command, _run_approve
        pid, overrides = parse_pt_command(text, pid_from_reply)
        if pid is None:
            response = "Reply to a proposal alert OR: `/ptapprove 1234 shares=200`"
        else:
            user_id = str(msg.get("from", {}).get("id", ""))
            user_name = msg.get("from", {}).get("first_name", "operator")
            result = _run_approve(pid, user_id, overrides)
            if result.get("ok"):
                ov = ", ".join(f"{k}={v}" for k, v in overrides.items()) if overrides else "as proposed"
                response = (f"\u2705 *APPROVED by {user_name}* ({ov})\n"
                           f"{result.get('symbol', '?')}: shares={result.get('shares')} "
                           f"entry=${result.get('entry_price', 0):.2f} "
                           f"stop=${result.get('stop_price', 0):.2f} "
                           f"target=${result.get('target_price', 0):.2f}\n"
                           f"Risk gate: {result.get('risk_gate_decision', '?')}")
            else:
                response = f"\u274c *FAILED*: {result.get('error', 'unknown')}"

    elif lower.startswith("/ptreject"):
        import re
        from telegram_callback_handler import parse_pt_command, _run_reject
        pid, _ = parse_pt_command(text, pid_from_reply)
        reason_m = re.search(r'/ptreject\s+(?:\d+\s+)?(.+)?$', text)
        reason = (reason_m.group(1) or "").strip() if reason_m else ""
        if pid is None:
            response = "Reply to a proposal alert OR: `/ptreject 1234 reason`"
        else:
            user_id = str(msg.get("from", {}).get("id", ""))
            result = _run_reject(pid, user_id, f"telegram: {reason or 'no reason'}")
            if result.get("ok"):
                response = f"\u2705 *REJECTED*: {result.get('symbol', '?')} — {reason or 'no reason'}"
            else:
                response = f"\u274c *FAILED*: {result.get('error', 'unknown')}"

    if response:
        payload = json.dumps({
            "chat_id": chat_id,
            "reply_to_message_id": message_id,
            "text": response,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.error(f"reply send failed: {e}")


def _handle_stop_command(msg, text, chat_id):
    """Route /stop* text commands."""
    import urllib.request
    token = _token()
    lower = text.lower()
    message_id = msg.get("message_id")
    user_id = str(msg.get("from", {}).get("id", ""))
    user_name = msg.get("from", {}).get("first_name", "operator")
    parts = text.split()
    response = None

    if lower.startswith("/stopexit"):
        sym = parts[1].upper() if len(parts) > 1 else None
        if not sym:
            response = "Usage: /stopexit SYMBOL"
        else:
            from telegram_callback_handler import _handle_stop_decision
            result = _handle_stop_decision(sym, "EXIT", user_id, f"operator honored stop via /stopexit")
            if result.get("ok"):
                response = f"STOP HONORED -- {sym} marked for exit by {user_name}"
            else:
                response = f"FAILED: {result.get('error', 'unknown')}"

    elif lower.startswith("/stophold"):
        sym = parts[1].upper() if len(parts) > 1 else None
        if not sym:
            response = "Usage: /stophold SYMBOL"
        else:
            from telegram_callback_handler import _handle_stop_decision
            result = _handle_stop_decision(sym, "HOLD_OVERRIDE", user_id, f"operator override via /stophold")
            if result.get("ok"):
                response = f"OVERRIDE -- {sym} held by {user_name}, watching"
            else:
                response = f"FAILED: {result.get('error', 'unknown')}"

    elif lower.startswith("/stopdelay"):
        sym = parts[1].upper() if len(parts) > 1 else None
        mins = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
        if not sym:
            response = "Usage: /stopdelay SYMBOL [minutes]"
        else:
            from telegram_callback_handler import _handle_stop_snooze
            result = _handle_stop_snooze(sym, mins, user_id)
            if result.get("ok"):
                response = f"POSTPONED -- {sym} snoozed {mins} min"
            else:
                response = f"FAILED: {result.get('error', 'unknown')}"

    elif lower.startswith("/stopset"):
        # /stopset RTX stop=178.50
        sym = parts[1].upper() if len(parts) > 1 else None
        stop_val = None
        for p in parts[2:]:
            if p.startswith("stop="):
                try:
                    stop_val = float(p.split("=")[1])
                except ValueError:
                    pass
        if not sym or stop_val is None:
            response = "Usage: /stopset SYMBOL stop=PRICE"
        else:
            try:
                from db_adapter import _get_conn
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("SELECT id, stop_loss FROM paper_trades WHERE symbol=%s AND status='open' LIMIT 1", (sym,))
                row = cur.fetchone()
                if row:
                    old_stop = float(row[1])
                    cur.execute("UPDATE paper_trades SET stop_loss=%s WHERE id=%s", (stop_val, row[0]))
                    conn.commit()
                    response = f"STOP SET -- {sym} stop ${old_stop:.2f} -> ${stop_val:.2f}"
                else:
                    response = f"No open paper trade found for {sym}"
                conn.close()
            except Exception as e:
                response = f"FAILED: {e}"

    if response:
        payload = json.dumps({
            "chat_id": chat_id,
            "reply_to_message_id": message_id,
            "text": response,
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.error(f"stop reply send failed: {e}")


_atm_pending_confirm = {}  # chat_id -> (timestamp, action)


def _handle_atm_command(msg, text, chat_id):
    """Handle /atm commands."""
    import urllib.request, time as _time
    token = _token()
    message_id = msg.get("message_id")
    parts = text.strip().split()
    sub = parts[1].lower() if len(parts) > 1 else "status"

    response = ""

    if sub == "status":
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT mode, paused_until, last_state_change_at, last_state_change_by, last_evaluated_at, config_hash FROM atm_state WHERE id=1")
            r = cur.fetchone()
            mode, pu, lsc, lscb, le, ch = r if r else ("?",)*6
            cur.execute("SELECT account_label, enabled FROM accounts ORDER BY id")
            accts = cur.fetchall()
            acct_lines = "\n".join(f"  {a[0]}: {'ON' if a[1] else 'off'}" for a in accts)
            le_age = ""
            if le:
                from datetime import datetime, timezone
                age_min = (datetime.now(timezone.utc) - le.replace(tzinfo=timezone.utc if le.tzinfo is None else le.tzinfo)).total_seconds() / 60
                le_age = f" ({age_min:.0f}m ago)"
            response = (f"ATM Status: {mode.upper()}\n"
                        f"Paused until: {pu or 'n/a'}\n"
                        f"Last change: {lscb} at {str(lsc)[:19]}\n"
                        f"Last evaluated: {str(le)[:19]}{le_age}\n"
                        f"Config hash: {ch or 'none'}\n"
                        f"Accounts:\n{acct_lines}")
        except Exception as e:
            response = f"ATM status error: {e}"

    elif sub == "on":
        _atm_pending_confirm[chat_id] = (_time.time(), "atm_on")
        try:
            from atm_config_manager import get_enabled_accounts
            ea = get_enabled_accounts()
            response = (f"ATM will be set to ACTIVE across {len(ea)} account(s): {', '.join(ea)}\n\n"
                        f"Reply YES within 30 seconds to confirm.")
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "off":
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT mode FROM atm_state WHERE id=1")
            old = cur.fetchone()[0]
            cur.execute("UPDATE atm_state SET mode='disabled', last_state_change_at=NOW(), last_state_change_by=%s WHERE id=1", (f"telegram:{chat_id}",))
            cur.execute("INSERT INTO atm_state_events (old_mode, new_mode, changed_by) VALUES (%s, 'disabled', %s)", (old, f"telegram:{chat_id}"))
            conn.commit()
            response = "ATM DISABLED"
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "dryrun":
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT mode FROM atm_state WHERE id=1")
            old = cur.fetchone()[0]
            cur.execute("UPDATE atm_state SET mode='dry_run', last_state_change_at=NOW(), last_state_change_by=%s WHERE id=1", (f"telegram:{chat_id}",))
            cur.execute("INSERT INTO atm_state_events (old_mode, new_mode, changed_by) VALUES (%s, 'dry_run', %s)", (old, f"telegram:{chat_id}"))
            conn.commit()
            response = "ATM set to DRY_RUN mode (evaluates but does not approve)"
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "pause":
        duration = parts[2] if len(parts) > 2 else "4h"
        try:
            from datetime import datetime, timezone, timedelta
            if duration == "until-tomorrow":
                import pytz
                et = pytz.timezone("US/Eastern")
                tomorrow = datetime.now(et).replace(hour=9, minute=30, second=0) + timedelta(days=1)
                pu = tomorrow.astimezone(timezone.utc)
            elif duration.endswith("h"):
                pu = datetime.now(timezone.utc) + timedelta(hours=int(duration[:-1]))
            else:
                pu = datetime.now(timezone.utc) + timedelta(hours=4)
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT mode FROM atm_state WHERE id=1")
            old = cur.fetchone()[0]
            cur.execute("UPDATE atm_state SET mode='paused', paused_until=%s, pause_reason=%s, last_state_change_at=NOW(), last_state_change_by=%s WHERE id=1",
                        (pu, f"telegram_pause_{duration}", f"telegram:{chat_id}"))
            cur.execute("INSERT INTO atm_state_events (old_mode, new_mode, changed_by, reason) VALUES (%s, 'paused', %s, %s)",
                        (old, f"telegram:{chat_id}", f"pause_{duration}"))
            conn.commit()
            response = f"ATM PAUSED until {str(pu)[:19]} UTC"
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "resume":
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT mode FROM atm_state WHERE id=1")
            old = cur.fetchone()[0]
            cur.execute("UPDATE atm_state SET mode='active', paused_until=NULL, pause_reason=NULL, last_state_change_at=NOW(), last_state_change_by=%s WHERE id=1", (f"telegram:{chat_id}",))
            cur.execute("INSERT INTO atm_state_events (old_mode, new_mode, changed_by) VALUES (%s, 'active', %s)", (old, f"telegram:{chat_id}"))
            conn.commit()
            response = "ATM RESUMED (ACTIVE)"
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "last":
        n = min(int(parts[2]), 20) if len(parts) > 2 and parts[2].isdigit() else 10
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT decided_at, symbol, strategy_id, target_account, decision FROM atm_decision_log ORDER BY decided_at DESC LIMIT %s", (n,))
            rows = cur.fetchall()
            if not rows:
                response = "No ATM decisions yet."
            else:
                lines = [f"Last {len(rows)} ATM decisions:"]
                for r in rows:
                    lines.append(f"  {str(r[0])[:16]} {r[1]} {(r[2] or '?')[:15]} -> {r[3]} = {r[4]}")
                response = "\n".join(lines)
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "accounts":
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT account_label, broker, mode, enabled, auto_execution_capable FROM accounts ORDER BY id")
            rows = cur.fetchall()
            lines = ["ATM Accounts:"]
            for r in rows:
                status = "ENABLED" if r[3] else "disabled"
                auto = "auto" if r[4] else "manual"
                lines.append(f"  {r[0]}: {r[1]}/{r[2]} [{status}] ({auto})")
            response = "\n".join(lines)
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "queue":
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, symbol, strategy_id, target_account, atm_action
                FROM paper_trade_proposals WHERE status='PENDING'
                ORDER BY created_at ASC LIMIT 10
            """)
            rows = cur.fetchall()
            if not rows:
                response = "ATM queue: 0 pending proposals"
            else:
                lines = [f"ATM queue: {len(rows)} pending:"]
                for r in rows:
                    override = f" [{r[4]}]" if r[4] else ""
                    lines.append(f"  #{r[0]} {r[1]} ({(r[2] or '?')[:15]}) -> {r[3]}{override}")
                response = "\n".join(lines)
        except Exception as e:
            response = f"Error: {e}"

    elif sub == "config":
        try:
            from atm_config_manager import load_config
            import yaml
            cfg, h = load_config()
            txt = yaml.dump(cfg, default_flow_style=False)
            if len(txt) > 3800:
                txt = txt[:3800] + "\n... (truncated)"
            response = f"ATM Config (hash: {h}):\n{txt}"
        except Exception as e:
            response = f"Error: {e}"

    else:
        response = ("ATM commands:\n"
                     "/atm status\n/atm on\n/atm off\n/atm dryrun\n"
                     "/atm pause [4h|24h|until-tomorrow]\n/atm resume\n"
                     "/atm config\n/atm last [N]\n/atm accounts\n/atm queue")

    # Check for YES confirmation
    if text.strip().upper() == "YES" and chat_id in _atm_pending_confirm:
        ts, action = _atm_pending_confirm[chat_id]
        if _time.time() - ts <= 30 and action == "atm_on":
            del _atm_pending_confirm[chat_id]
            try:
                from db_adapter import _get_conn
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("SELECT mode FROM atm_state WHERE id=1")
                old = cur.fetchone()[0]
                cur.execute("UPDATE atm_state SET mode='active', last_state_change_at=NOW(), last_state_change_by=%s WHERE id=1", (f"telegram:{chat_id}",))
                cur.execute("INSERT INTO atm_state_events (old_mode, new_mode, changed_by) VALUES (%s, 'active', %s)", (old, f"telegram:{chat_id}"))
                conn.commit()
                response = "ATM ACTIVATED"
            except Exception as e:
                response = f"Activation error: {e}"
        else:
            del _atm_pending_confirm[chat_id]
            response = "Confirmation expired. Run /atm on again."

    if response:
        payload = json.dumps({"chat_id": chat_id, "text": response,
                              "reply_to_message_id": message_id}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.error(f"ATM reply send failed: {e}")


# ── Schwab OAuth callback auto-exchange ──────────────────────────────────────────────

def _handle_llm_caps(msg, text, chat_id):
    """`/caps` to list, `/cap <process_id> <requests> [dollars]` to set.

    Allowlist-gated by the SAME check every other command here uses. A chat
    message must not be able to raise a spend limit from an unknown chat, and
    the module's own MAX_* ceilings bound it even for the operator — a cap is
    only worth having if it holds when someone is in a hurry, and that is
    exactly when caps get raised.
    """
    import os

    import psycopg2

    from scripts.lib.llm_cap_admin import MAX_DOLLARS, MAX_REQUESTS, list_caps, set_caps

    # The dispatch loop already gates on _allowed_chats(); re-checking here is
    # deliberate. This is the one command that can raise a spend limit, and a
    # future refactor of the loop must not silently open it.
    if str(chat_id) not in {str(c) for c in _allowed_chats()}:
        log.warning("llm caps command from non-allowlisted chat %s", chat_id)
        return

    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"))
    except Exception as exc:
        _send(chat_id, f"caps: database unavailable ({type(exc).__name__})")
        return

    try:
        parts = text.split()
        if parts[0].lower() == "/caps":
            rows = list_caps(conn)
            lines = ["*LLM spend caps*  (requests / dollars per day)", ""]
            for r in rows:
                if r["db_requests"] is None:
                    continue
                flag = "  ⚠️ REGISTRY DISAGREES" if r["drift"] else ""
                lines.append(f"`{r['process_id']}`  {r['db_requests']} / ${r['db_dollars']}{flag}")
            lines += ["", "Set with: `/cap <process_id> <requests> [dollars]`",
                      f"Ceilings: {MAX_REQUESTS} requests, ${MAX_DOLLARS}",
                      "",
                      "The GLOBAL cap (LLM_GLOBAL_DAILY_USD_CAP) is not settable here —",
                      "it lives in the bridge's environment and needs a restart."]
            _send(chat_id, "\n".join(lines)[:3800])
            return

        if len(parts) < 3:
            _send(chat_id, "Usage: `/cap <process_id> <requests> [dollars]`")
            return
        pid = parts[1]
        try:
            reqs = int(parts[2])
            dollars = float(parts[3]) if len(parts) > 3 else None
        except ValueError:
            _send(chat_id, "requests must be a whole number, dollars a decimal")
            return

        res = set_caps(pid, requests=reqs, dollars=dollars, conn=conn,
                       actor=f"telegram:{chat_id}")
        if not res.get("ok"):
            _send(chat_id, f"caps NOT changed: {res.get('error')}")
            return
        b, a = res["before"], res["after"]
        _send(chat_id,
              f"*{pid}* updated\n"
              f"was: {b['requests']} / ${b['dollars']}\n"
              f"now: {a['requests']} / ${a['dollars']}\n\n"
              f"Registry and database both written. Revert with:\n"
              f"`/cap {pid} {b['requests']} {b['dollars']}`")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _handle_guard_approval(msg, text, chat_id):
    """Operator answers a guard approval request from their phone.

    This is the ONLY path that converts a PENDING request into a real grant, and
    it runs here rather than in the requesting process for two reasons. First,
    this daemon already owns the single `getUpdates` consumer — a second one
    collides with HTTP 409, which is why the telegram_command_handler cron entry
    is disabled. Second, the process that ASKS must not be the process that
    ANSWERS; keeping them apart is what makes the approval the operator's.

    The agent never types APPROVE. The operator types it, on their own device,
    against a scope and window fixed before they saw it.
    """
    import re
    import subprocess

    try:
        from scripts.lib import guard_remote_approval as gra
    except ImportError:
        from lib import guard_remote_approval as gra          # type: ignore

    parts = text.strip().split()
    verb = parts[0].lower().lstrip("/")
    code = parts[1].strip() if len(parts) > 1 else ""
    reply_to = (msg or {}).get("message_id")

    if not re.fullmatch(r"[A-Za-z0-9]{4,12}", code or ""):
        _send_reply(chat_id, reply_to,
                    "⚠️ Usage: `/approve <CODE>` or `/deny <CODE>`")
        return

    allowed = _allowed_chats()

    if verb == "deny":
        out = gra.deny(code, chat_id=chat_id, allowed_chats=allowed)
        if out.get("ok"):
            r = out["request"]
            _send_reply(chat_id, reply_to,
                        f"\U0001f6d1 Denied `{r['scope']}`. Nothing was granted.")
        else:
            _send_reply(chat_id, reply_to, f"⚠️ Not denied: {out.get('reason')}")
        return

    frm = (msg or {}).get("from") or {}
    out = gra.verify_and_consume(
        code, chat_id=chat_id, allowed_chats=allowed,
        telegram={"update_id": (msg or {}).get("_update_id"),
                  "message_id": reply_to,
                  "from_id": frm.get("id"),
                  "from_username": frm.get("username"),
                  "text": text[:200]},
    )
    if not out.get("ok"):
        _send_reply(chat_id, reply_to, f"❌ Not approved: {out.get('reason')}")
        log.warning(f"guard approval refused: {out.get('reason')}")
        return

    r = out["request"]
    # The reason carries the request id so the grant in the approval ledger is
    # traceable back to the Telegram message that authorised it.
    reason = f"{r['reason']} [remote_request_id={r['request_id']} chat={chat_id}]"
    guard_bin = Path(__file__).resolve().parent.parent / "bin" / "guard"
    if not guard_bin.is_file():
        _send_reply(chat_id, reply_to,
                    f"⚠️ Approved, but `bin/guard` was not found at {guard_bin}. "
                    "Nothing granted.")
        log.error(f"guard binary missing at {guard_bin}")
        return

    # Bare seconds, no unit suffix — see parse_dur in bin/guard.
    cmd = [str(guard_bin), "grant", r["scope"],
           "--for", str(int(r["seconds"])),
           "--uses", str(int(r["uses"])),
           "--reason", reason,
           "--yes"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:                                    # noqa: BLE001
        _send_reply(chat_id, reply_to, f"⚠️ Approved, but the grant failed: {e}")
        log.error(f"guard grant failed: {e}")
        return

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        _send_reply(chat_id, reply_to,
                    f"⚠️ Approved, but the grant failed:\n`{detail}`")
        log.error(f"guard grant rc={proc.returncode}: {detail}")
        return

    mins = int(r["seconds"]) // 60
    _send_reply(chat_id, reply_to,
                f"✅ Granted `{r['scope']}` for {mins} min, {r['uses']} uses.\n"
                f"Revoke any time with `/deny` on a new request, or "
                f"`bin/guard revoke {r['scope']}` at the machine.")
    log.info(f"guard scope {r['scope']} granted remotely, request {r['request_id']}")


def _send_reply(chat_id, reply_to_message_id, text):
    """Send a reply to a specific message in the operator chat."""
    token = _token()
    if not token:
        log.error("No TELEGRAM_BOT_TOKEN for reply")
        return
    payload = urllib.parse.urlencode({
        "chat_id": chat_id, "reply_to_message_id": reply_to_message_id,
        "text": text, "parse_mode": "Markdown",
    }).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.error(f"schwab reply failed: {e}")


def _handle_schwab_callback(msg, text, chat_id):
    """Operator pasted a Schwab OAuth redirect URL containing ?code=.
    Auto-extract the code, exchange for a token, and reply with status."""
    message_id = msg.get("message_id")
    log.info(f"schwab callback from chat={chat_id}: {text[:80]}...")

    # Extract the full redirect URL (the user may have pasted extra text)
    import re as _re
    url_match = _re.search(r'(https?://127\.0\.0\.1[^\s]*)', text)
    if not url_match:
        _send_reply(chat_id, message_id,
                    "❌ Could not find a valid `127.0.0.1?code=...` URL in your message.\n"
                    "Please paste the FULL redirect URL from your browser's address bar.")
        return

    redirect_url = url_match.group(1)
    _send_reply(chat_id, message_id,
                "⏳ Exchanging authorization code for a new 7-day token…")

    # Import and call exchange_code
    import schwab_token_manager as _tm
    result = _tm.exchange_code("schwab_taxable", redirect_url)

    if result.get("ok"):
        expiry = result.get("refresh_expires_at", "?")
        _send_reply(chat_id, message_id,
                    f"✅ Schwab token refreshed\\! Valid until *{expiry[:10]}*.\n"
                    f"Next proactive reauth ≈ {expiry[:10] if expiry else '7 days'}.")
        # Verify with live probe
        try:
            probe = _tm.live_probe("schwab_taxable")
            if probe and probe.get("live_ok"):
                _send_reply(chat_id, message_id,
                            "✓ Live probe passed — quotes, stops, and journal reads are restored.")
        except Exception:
            pass
    else:
        reason = result.get("reason", "unknown error")[:200]
        _send_reply(chat_id, message_id,
                    f"❌ Token exchange failed: `{reason}`\n"
                    "The authorization code may have expired (codes are valid ~5 minutes).\n"
                    "Restart the login and paste the new redirect URL promptly.")


def main():
    """Run continuous long-poll loop."""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Poll once and exit")
    p.add_argument("--daemon", action="store_true", help="Run continuous loop")
    args = p.parse_args()

    if args.once:
        n = poll_once(timeout=5)
        print(f"Processed {n} updates")
        return

    # Daemon mode — continuous long poll
    log.info("Starting Telegram callback poller (long-poll, PID %d)", os.getpid())
    sys.stdout.flush()
    consecutive_errors = 0
    while True:
        try:
            n = poll_once(timeout=25)
            if n > 0:
                log.info(f"Processed {n} updates")
            consecutive_errors = 0
        except KeyboardInterrupt:
            log.info("Stopped")
            break
        except Exception:
            consecutive_errors += 1
            log.exception(f"poll error (consecutive: {consecutive_errors})")
            time.sleep(min(5 * consecutive_errors, 60))


if __name__ == "__main__":
    main()
