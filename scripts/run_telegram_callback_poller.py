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
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [tg-poller] %(message)s")
log = logging.getLogger(__name__)

OFFSET_FILE = PROJECT_ROOT / "data" / "portfolios" / "state" / ".telegram_callback_offset"


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
        _save_offset(update["update_id"])

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
            continue

        # Handle messages (commands)
        msg = update.get("message", {})
        if not msg:
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if chat_id not in allowed or not text:
            continue

        # Route proposal commands
        lower = text.lower()
        if lower.startswith("/ptapprove") or lower.startswith("/ptreject") or \
           lower.startswith("/ptpending") or lower.startswith("/ptstatus"):
            try:
                _handle_proposal_command(msg, text, chat_id)
                processed += 1
                log.info(f"command: {text[:40]} from chat={chat_id}")
            except Exception as e:
                log.error(f"command error: {e}")

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
