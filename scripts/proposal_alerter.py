#!/usr/bin/env python3
"""proposal_alerter.py — Rich Telegram proposal alerts with callback-only buttons.

All actions use callback_data (Telegram → bot poll → MS-01).
NO url: buttons — LAN addresses are dead links on cellular.

Paper mode only. No live trading. No .env modification.
"""
import json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not t:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                t = line.split("=", 1)[1].strip()
    return t


def _chat_targets():
    """Return list of chat IDs to send to. Prefers decisions group."""
    targets = []
    g = os.environ.get("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "").strip()
    if g:
        targets.append(g)
    else:
        std = os.environ.get("TELEGRAM_CHAT_ID", "")
        targets.extend(c.strip() for c in std.split(",") if c.strip())
    return targets


def format_proposal_alert(proposal, alert_type, current_price):
    """Build rich proposal alert message + inline keyboard.

    alert_type: NEW_PROPOSAL | TARGET_CROSSED | STOP_CROSSED | LARGE_MOVE | STALE | EXPIRED
    Returns (message_text, inline_keyboard_dict_or_None).
    """
    sym = proposal.get("symbol", "?")
    entry = float(proposal.get("proposed_entry") or proposal.get("entry_price") or 0)
    stop = float(proposal.get("proposed_stop") or proposal.get("stop_price") or 0)
    target = float(proposal.get("proposed_target1") or proposal.get("target_price") or 0)
    shares = int(proposal.get("proposed_shares") or proposal.get("shares") or 0)
    strategy = proposal.get("strategy_id", "unknown")
    pid = proposal.get("id", "?")

    position_value = shares * entry
    dollar_risk = shares * (entry - stop) if stop < entry else 0
    dollar_reward = shares * (target - entry) if target > entry else 0
    rr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0
    pct_from_entry = ((current_price - entry) / entry * 100) if entry > 0 else 0

    headers = {
        "NEW_PROPOSAL":   "\U0001f195 *NEW PROPOSAL*",
        "TARGET_CROSSED": "\U0001f3af *TARGET CROSSED — REVIEW NOW*",
        "STOP_CROSSED":   "\U0001f6d1 *STOP CROSSED — TRADE INVALID*",
        "LARGE_MOVE":     "\u26a0\ufe0f *LARGE MOVE — REVIEW NOW*",
        "STALE":          "\u23f0 *PROPOSAL STALE — AUTO-EXPIRES SOON*",
        "EXPIRED":        "\u274e *PROPOSAL AUTO-EXPIRED*",
    }
    header = headers.get(alert_type, alert_type)

    msg = (
        f"{header}\n\n"
        f"*{sym}* — `{strategy}`\n"
        f"Entry ${entry:.2f}  |  Now ${current_price:.2f}  ({pct_from_entry:+.1f}%)\n"
        f"Stop ${stop:.2f}  |  Target ${target:.2f}  |  R:R {rr:.1f}x\n"
        f"Shares {shares:,}  |  Position ${position_value:,.0f}\n"
        f"Risk ${dollar_risk:,.0f}  |  Reward ${dollar_reward:,.0f}\n\n"
        f"Proposal `#{pid}`\n"
        f"_Paper mode — no order submitted_\n\n"
        f"Reply: `/ptapprove {pid}` or `/ptapprove {pid} shares=200 target=2.50`"
    )

    # Callback buttons — all use callback_data (works from cellular via bot poll)
    rows = []
    if alert_type in ("NEW_PROPOSAL", "TARGET_CROSSED", "LARGE_MOVE", "STALE"):
        rows = [
            [
                {"text": "\u2705 Approve", "callback_data": f"ptapprove:{pid}"},
                {"text": "\u274c Reject", "callback_data": f"ptreject:{pid}"},
            ],
            [
                {"text": "\u00bd\u00d7 Shares", "callback_data": f"ptapprove_half:{pid}"},
                {"text": "2\u00d7 Shares", "callback_data": f"ptapprove_2x:{pid}"},
            ],
            [
                {"text": "\u2139\ufe0f More Info", "callback_data": f"ptinfo:{pid}"},
            ],
        ]
    elif alert_type == "STOP_CROSSED":
        rows = [[
            {"text": "\u274c Reject", "callback_data": f"ptreject:{pid}"},
            {"text": "\u2139\ufe0f More Info", "callback_data": f"ptinfo:{pid}"},
        ]]

    # URL button — only when Tailscale FQDN is configured (HTTPS, no port)
    tailscale_host = os.environ.get("TAILSCALE_HOSTNAME", "").strip()
    if tailscale_host and rows:
        rows.append([
            {"text": "\U0001f4ca Open in Dashboard",
             "url": f"https://{tailscale_host}/v2/paper-proposals?id={pid}"},
        ])

    keyboard = {"inline_keyboard": rows} if rows else None
    return msg, keyboard


def send_proposal_alert(proposal, alert_type, current_price):
    """Send alert to dedicated decisions group or fallback standard chats."""
    import urllib.request
    token = _token()
    if not token:
        log.error("No TELEGRAM_BOT_TOKEN")
        return

    msg, keyboard = format_proposal_alert(proposal, alert_type, current_price)
    targets = _chat_targets()
    if not targets:
        log.error("No Telegram chat targets configured")
        return

    for chat_id in targets:
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
        }
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)

        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            if result.get("ok"):
                msg_id = result.get("result", {}).get("message_id")
                if msg_id:
                    _store_proposal_message_link(proposal.get("id"), chat_id, msg_id)
            else:
                log.error(f"send_proposal_alert failed chat={chat_id} resp={result}")
        except Exception:
            log.exception(f"send_proposal_alert exception chat={chat_id}")


def _store_proposal_message_link(proposal_id, chat_id, message_id):
    """Persist (chat_id, message_id) → proposal_id for reply resolution."""
    if not proposal_id:
        return
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO telegram_proposal_messages
                (proposal_id, chat_id, message_id, sent_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (chat_id, message_id) DO NOTHING""",
            (int(proposal_id), str(chat_id), int(message_id)),
        )
        conn.commit()
        conn.close()
    except Exception:
        log.exception("Failed to store proposal message link")


def maybe_send_threshold_alert(proposal_id, alert_type, current_price):
    """Send alert with 30-min cooldown per alert_type per proposal; max 5 total."""
    from db_adapter import _get_conn
    import psycopg2.extras

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM paper_trade_proposals WHERE id=%s", (proposal_id,))
    p = cur.fetchone()
    if not p or p["status"] != "PENDING":
        conn.close()
        return

    if (p.get("alert_count") or 0) >= 5:
        conn.close()
        return  # auto-expiry will catch via OVER_ALERTED

    if p.get("last_alert_at"):
        last = p["last_alert_at"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - last).total_seconds()
        if secs < 1800 and p.get("last_alert_type") == alert_type:
            conn.close()
            return  # 30-min cooldown for same alert_type

    send_proposal_alert(dict(p), alert_type, current_price)

    cur.execute(
        """UPDATE paper_trade_proposals
        SET alert_count = COALESCE(alert_count,0) + 1,
            last_alert_at = NOW(),
            last_alert_type = %s
        WHERE id = %s""",
        (alert_type, proposal_id),
    )
    conn.commit()
    conn.close()


def build_proposal_info(pid):
    """Extended context posted as a reply — pure text, no URL."""
    from db_adapter import _get_conn
    import psycopg2.extras

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM paper_trade_proposals WHERE id=%s", (pid,))
    p = cur.fetchone()
    conn.close()

    if not p:
        return f"Proposal #{pid} not found"

    entry = float(p.get("proposed_entry") or 0)
    stop = float(p.get("proposed_stop") or 0)
    target = float(p.get("proposed_target1") or 0)
    shares = int(p.get("proposed_shares") or 0)
    risk = abs(entry - stop) * shares if entry and stop and shares else 0

    lines = [
        f"*Proposal #{p['id']}* — `{p.get('strategy_id', '?')}`",
        f"*{p['symbol']}* | Status: `{p['status']}`",
        "",
        f"Entry: ${entry:.2f}",
        f"Stop:  ${stop:.2f}",
        f"Target: ${target:.2f}",
        f"Shares: {shares:,}",
        f"Risk:   ${risk:,.2f}",
        "",
    ]

    if p.get("catalyst"):
        lines.append(f"Catalyst: {str(p['catalyst'])[:200]}")
    if p.get("critic_verdict"):
        lines.append(f"Critic: {p['critic_verdict']}")
    if p.get("risk_gate_result"):
        lines.append(f"Risk gate: {p['risk_gate_result']}")
    lines.append(f"Created: {p.get('created_at', '?')}")
    if p.get("expires_at"):
        lines.append(f"Expires: {p['expires_at']}")
    if p.get("approval_blocked_reason"):
        lines.append(f"Blocked: {p['approval_blocked_reason']}")

    return "\n".join(lines)
