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

# Agnostic status labels — simulation or live destination; never paper-only framing.
STATUS_LABELS = {
    "APPROVED_FOR_PAPER_TEST": "Approved · route-eligible",
    "APPROVED": "Approved · route-eligible",
    "PENDING": "Pending review",
    "MODIFIED": "Modified · pending re-review",
    "BROKER_SUBMITTED": "Routed to broker",
    "EXPIRED": "Expired",
    "REJECTED": "Rejected",
    "CANCELLED": "Cancelled",
}


def friendly_status(status) -> str:
    """Operator-facing proposal status label (avoids the misleading raw 'PAPER_TEST' enum)."""
    return STATUS_LABELS.get(str(status or "").upper(), str(status or "?"))


def _shadow_publish(msg: str, *, producer: str, subject_key: str, severity: str = "info") -> None:
    try:
        root = str(PROJECT_ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
        from scripts.lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="ops",
            producer=producer, subject_key=subject_key,
            retention_class="operational", severity=severity,
            sanitized_body=msg[:500], short_summary=msg[:120],
        ))
    except Exception:
        pass


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
                # Modify SIZE presets (override_payload) + custom Size / Risk via force-reply
                {"text": "\U0001f4cf \u00bd\u00d7", "callback_data": f"ptapprove_half:{pid}"},
                {"text": "\U0001f4cf 2\u00d7", "callback_data": f"ptapprove_2x:{pid}"},
                {"text": "\u270f\ufe0f Size", "callback_data": f"ptmodify_size:{pid}"},
                {"text": "\U0001f3af Risk", "callback_data": f"ptmodify_risk:{pid}"},
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

    # URL buttons via canonical builder (survives Markdown body failures).
    try:
        from notification_url_builder import build_dashboard_url, build_proposal_url
        prop_url = build_proposal_url(pid)
        policy_url = build_dashboard_url("/v3/automation", {"account": "alpaca_paper"})
        if prop_url and rows is not None:
            rows.append([
                {"text": "\U0001f50e Review trade", "url": prop_url},
                {"text": "⚙️ Policy", "url": policy_url},
            ])
    except Exception:
        tailscale_host = os.environ.get("TAILSCALE_HOSTNAME", "").strip()
        if tailscale_host and rows:
            rows.append([
                {"text": "\U0001f50e Review trade",
                 "url": f"https://{tailscale_host}/v3/trading?tab=Proposals&proposal={pid}"},
            ])

    keyboard = {"inline_keyboard": rows} if rows else None
    return msg, keyboard


def send_proposal_alert(proposal, alert_type, current_price):
    """Send alert via telegram_alert chokepoint with inline keyboard restored."""
    msg, keyboard = format_proposal_alert(proposal, alert_type, current_price)
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg, reply_markup=keyboard))
        if not ok:
            log.info(f"send_proposal_alert not accepted for {proposal.get('symbol', '?')} ({alert_type})")
        _shadow_publish(
            msg, producer="proposal_alerter",
            subject_key=f"proposal:{proposal.get('id', '?')}",
            severity="info",
        )
    except Exception:
        log.exception(f"send_proposal_alert exception for {proposal.get('symbol', '?')}")

    # Email notification
    try:
        from email_notifier import notify_proposal
        entry = float(proposal.get("proposed_entry") or proposal.get("entry_price") or 0)
        stop = float(proposal.get("proposed_stop") or proposal.get("stop_price") or 0)
        target = float(proposal.get("proposed_target1") or proposal.get("target_price") or 0)
        shares = int(proposal.get("proposed_shares") or proposal.get("shares") or 0)
        notify_proposal(proposal.get("symbol", "?"), proposal.get("strategy_id", "?"),
                        entry, stop, target, shares, proposal.get("id", 0))
    except Exception:
        pass


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
        f"*{p['symbol']}* | Status: {friendly_status(p.get('status'))}",
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


# ── Stop-triggered decision alerts ──────────────────────────────────────────

def format_stop_alert(data):
    """Format a rich stop-triggered decision alert. Returns (msg, keyboard)."""
    sym = data["symbol"]
    acct = (data.get("account") or "").replace("schwab_", "").replace("_", " ").title()
    current = data["current_price"]
    stop = data["stop_price"]
    mv = data.get("market_value") or 0
    cb = data.get("cost_basis") or 0
    shares = data.get("shares") or 0
    rsi = data.get("rsi")
    day_chg = data.get("day_change_pct") or 0
    pct_below = data.get("pct_below_stop") or 0
    pnl = data.get("current_pnl_dollars")
    pnl_pct = data.get("current_pnl_pct")
    stop_pnl = data.get("stop_pnl_dollars")
    regime = (data.get("regime_label") or "unknown").upper().replace("_", " ")
    regime_conf = int((data.get("regime_confidence") or 0) * 100)
    trend = (data.get("trend_state") or "unknown").upper()
    heat = data.get("portfolio_heat_pct") or 0
    n_triggered = data.get("portfolio_triggered_count") or 0
    triggered_syms = ", ".join(data.get("triggered_symbols", []))
    tax_note = data.get("tax_note", "")
    sector_note = data.get("sector_note", "")
    holding = data.get("holding_period", "unknown")
    acquired = data.get("acquired_date", "?")

    pnl_icon = "\U0001f534" if (pnl or 0) < 0 else "\U0001f7e2"
    below_str = f"{abs(pct_below):.1f}% below stop" if pct_below < 0 else f"{abs(pct_below):.1f}% above stop"
    hold_label = "\u26a1 SHORT-TERM" if holding == "short" else "\U0001f4c5 LONG-TERM"

    lines = [
        "\U0001f6d1 *STOP TRIGGERED — DECISION REQUIRED*",
        "",
        f"*{sym}* \u2014 `{acct}`",
        f"Now ${current:.2f}  |  Stop ${stop:.2f}  |  {below_str}",
    ]
    if rsi:
        lines.append(f"Today: {'+' if day_chg >= 0 else ''}{day_chg:.1f}%  |  RSI: {rsi:.0f}")
    else:
        lines.append(f"Today: {'+' if day_chg >= 0 else ''}{day_chg:.1f}%")

    lines += [
        "",
        "*\U0001f4b0 YOUR POSITION*",
        f"Invested: ${cb:,.0f}  |  {shares:.2f} shares @ {hold_label}",
        f"Current value: ${mv:,.0f}  |  Acquired: {acquired}",
        "",
        "*\U0001f4ca EXIT P&L*",
    ]
    if pnl is not None:
        lines.append(f"{pnl_icon} Exit NOW @ ${current:.2f}:  {'+' if pnl >= 0 else ''}${pnl:,.0f}  ({'+' if (pnl_pct or 0) >= 0 else ''}{pnl_pct:.1f}%)")
    if stop_pnl is not None:
        sp_icon = "\U0001f534" if stop_pnl < 0 else "\U0001f7e2"
        lines.append(f"{sp_icon} Exit at stop ${stop:.2f}:  {'+' if stop_pnl >= 0 else ''}${stop_pnl:,.0f}")
    if tax_note:
        lines.append(f"\u26a0\ufe0f Tax: _{tax_note}_")

    lines += [
        "",
        "*\U0001f321\ufe0f MARKET CONDITIONS*",
        f"Regime: {regime} ({regime_conf}%)  |  Trend: {trend}",
        f"Portfolio heat: {heat:.1f}%  |  Stops triggered: {n_triggered}",
    ]
    if triggered_syms:
        lines.append(f"Triggered: `{triggered_syms}`")
    if sector_note:
        lines += ["", f"\U0001f4cc _{sector_note}_"]
    lines += ["", f"Reply: `/stopexit {sym}` to honor  |  `/stophold {sym}` to override"]

    msg = "\n".join(lines)

    rows = [
        [
            {"text": "\U0001f534 Honor Stop (Exit)", "callback_data": f"stopexit:{sym}"},
            {"text": "\u23f8\ufe0f Override (Hold)", "callback_data": f"stophold:{sym}"},
        ],
        [
            {"text": "\u23f0 Postpone 30m", "callback_data": f"stopdelay:{sym}:30"},
            {"text": "\u23f0 Postpone 2h", "callback_data": f"stopdelay:{sym}:120"},
        ],
        [
            {"text": "\u2191 Tighten Stop", "callback_data": f"stoptighten:{sym}"},
            {"text": "\u2193 Loosen Stop 5%", "callback_data": f"stoploosen:{sym}:5"},
        ],
        [
            {"text": "\u2139\ufe0f More Context", "callback_data": f"stopinfo:{sym}"},
        ],
    ]
    try:
        from notification_url_builder import build_dashboard_url
        rows.append([{"text": "\U0001f4ca Open in Dashboard", "url": build_dashboard_url("/v3/risk")}])
    except Exception:
        tailscale_host = os.environ.get("TAILSCALE_HOSTNAME", "").strip()
        if tailscale_host:
            rows.append([{"text": "\U0001f4ca Open in Dashboard",
                          "url": f"https://{tailscale_host}/v3/risk"}])

    return msg, {"inline_keyboard": rows}


def send_stop_alert(symbol, account=""):
    """Assemble and send a rich stop-triggered decision alert via send_telegram."""
    try:
        from stop_alert_assembler import assemble_stop_alert_data
        data = assemble_stop_alert_data(symbol, account)
    except Exception as e:
        log.exception(f"stop_alert assembly failed for {symbol}")
        data = None

    if not data:
        try:
            from telegram_alert import send_telegram
            fail_msg = f"\U0001f6a8 STOP TRIGGERED: {symbol} \u2014 data assembly failed, check /v3/risk"
            send_telegram(fail_msg)
            _shadow_publish(
                fail_msg, producer="proposal_alerter",
                subject_key=f"stop:{symbol}", severity="critical",
            )
        except Exception:
            pass
        return

    msg, keyboard = format_stop_alert(data)
    try:
        from telegram_alert import send_telegram
        send_telegram(msg, reply_markup=keyboard)
        _shadow_publish(
            msg, producer="proposal_alerter",
            subject_key=f"stop:{symbol}", severity="critical",
        )
    except Exception:
        log.exception(f"send_stop_alert failed for {symbol}")

    # Email notification
    try:
        from email_notifier import notify_stop_triggered
        notify_stop_triggered(
            symbol, data.get("current_price", 0), data.get("stop_price", 0),
            data.get("current_pnl_dollars", 0), data.get("current_pnl_pct", 0),
            data.get("regime_label", ""), data.get("portfolio_triggered_count", 0))
    except Exception:
        pass
