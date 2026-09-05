#!/usr/bin/env python3
"""
eod_open_trade_alert.py — End-of-day Telegram alert for open paper trades.

Sends: entry, current, P&L, R-multiple, stop distance, target distance,
trailing stop advice per trade. Cron: 16:05 ET Mon-Fri.
"""
import os, sys, json, logging, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
except ImportError:
    pass

from db_adapter import get_connection

log = logging.getLogger(__name__)


def _fmt_signed_money(n: float) -> str:
    """Always show the sign. Never abs() a loss and then omit the minus."""
    n = float(n or 0)
    sign = "+" if n >= 0 else "-"
    return f"{sign}${abs(n):.2f}"


def _fmt_signed_pct(n: float) -> str:
    n = float(n or 0)
    return f"{n:+.1f}%"


def _fmt_signed_r(n: float) -> str:
    n = float(n or 0)
    return f"{n:+.2f}R"


def _fmt_abs(n: float) -> str:
    return f"{abs(float(n or 0)):.0f}"

def get_open_trades() -> list:
    conn = get_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, strategy_id, shares,
                   entry_price, current_price, stop_loss, target_1,
                   unrealized_pnl, r_multiple, created_at::date
            FROM paper_trades WHERE status = 'open'
            ORDER BY created_at DESC
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        # Trail recommendations
        cur.execute("""
            SELECT strategy_id,
                   MODE() WITHIN GROUP (ORDER BY recommendation) as rec,
                   ROUND(AVG(high_water_pct_gain)::numeric, 1) as max_pot,
                   ROUND(AVG(CASE WHEN optimal_trail_pct IS NOT NULL
                                 THEN optimal_trail_pnl - fixed_pnl_pct ELSE 0
                            END)::numeric, 1) as improvement,
                   ROUND(AVG(optimal_trail_pct)::numeric, 0) as optimal_pct
            FROM trailing_stop_analysis GROUP BY strategy_id
        """)
        trail_map = {}
        for r in cur.fetchall():
            trail_map[r[0]] = {'rec': r[1], 'max_pot': float(r[2] or 0),
                               'improvement': float(r[3] or 0), 'optimal_pct': float(r[4] or 5)}
        return rows, trail_map
    except Exception as e:
        log.error(f"Query failed: {e}")
        return [], {}


def format_message(rows, trail_map) -> str:
    today = datetime.date.today().strftime('%Y-%m-%d')
    now = datetime.datetime.now().strftime('%H:%M ET')

    if not rows:
        return (f"EOD TRADE REPORT - {today} {now}\n\n"
                "No open paper trades at market close.")

    total_pnl = 0
    lines = [
        f"EOD OPEN TRADE REPORT - {today}",
        f"Market close - {now} - {len(rows)} position{'s' if len(rows) != 1 else ''}",
        "",
    ]

    for t in rows:
        entry = float(t['entry_price'] or 0)
        cur = float(t['current_price'] or entry)
        stop_raw = t.get('stop_loss')
        tgt_raw = t.get('target_1')
        stop = float(stop_raw or 0)
        tgt = float(tgt_raw or 0)
        shares = int(t['shares'] or 0)
        pnl = float(t['unrealized_pnl'] or 0)
        total_pnl += pnl
        pnl_pct = round((cur - entry) / entry * 100, 2) if entry else 0
        has_stop = stop_raw not in (None, "", 0, 0.0)
        has_tgt = tgt_raw not in (None, "", 0, 0.0)
        risk = abs(entry - stop) if entry and has_stop else 1
        r_m = round((cur - entry) / risk, 2) if risk else 0
        dist_stop = round((stop - cur) / cur * 100, 1) if cur and has_stop else 0
        dist_stop_usd = round((stop - cur) * shares, 2) if has_stop else 0
        dist_tgt = round((tgt - cur) / cur * 100, 1) if cur and has_tgt else 0
        dist_tgt_usd = round((tgt - cur) * shares, 2) if has_tgt else 0

        strat = (t.get('strategy_id') or 'unknown').replace('_', ' ')
        optionish = bool(t.get('asset_type') == 'option' or t.get('option_type')
                         or str(t.get('symbol') or '').rstrip().endswith(('C', 'P'))
                         and any(ch.isdigit() for ch in str(t.get('symbol') or '')))

        tr = trail_map.get(t.get('strategy_id'), {})
        rec = tr.get('rec', 'keep_fixed') or 'keep_fixed'
        if rec.startswith('use_trail'):
            trail_msg = f"Consider {float(tr.get('optimal_pct', 5)):.0f}% trail (+{float(tr.get('improvement', 0)):.1f}% vs fixed)"
        else:
            trail_msg = f"Keep fixed stop (avg max potential +{float(tr.get('max_pot', 0)):.1f}%)"

        kind = "option" if optionish else f"{shares}sh"
        lines += [
            f"{'UP' if pnl >= 0 else 'DOWN'} {t['symbol']} - {strat} - {kind}",
            f"  Entry: ${entry:.2f} -> Current: ${cur:.3f}",
            f"  P&L: {_fmt_signed_money(pnl)} ({_fmt_signed_pct(pnl_pct)}) | R: {_fmt_signed_r(r_m)}",
        ]
        if has_stop:
            lines.append(
                f"  Stop: ${stop:.2f} ({_fmt_signed_pct(dist_stop)}) max loss: ${_fmt_abs(dist_stop_usd)}"
            )
        else:
            lines.append("  Stop: not set")
        if has_tgt:
            lines.append(
                f"  Target: ${tgt:.2f} ({_fmt_signed_pct(dist_tgt)}) if hit: {_fmt_signed_money(dist_tgt_usd)}"
            )
        else:
            lines.append("  Target: not set")
        lines += [
            f"  Trail: {trail_msg}",
            "",
        ]

    if len(rows) > 1:
        lines.append(f"Total unrealized P&L: {_fmt_signed_money(total_pnl)}")
        lines.append("")

    lines.append("Alpaca paper mode | Simulated positions")
    return '\n'.join(lines)


def send_eod_alert():
    rows, trail_map = get_open_trades()
    message = format_message(rows, trail_map)
    log.info(f"Sending EOD alert: {len(rows)} open trades")

    # Route through the central Telegram chokepoint so the report is FQDN-normalized AND
    # persisted to telegram_outbox for the v3 Reports portal. bypass_router: scheduled report.
    from telegram_alert import send_telegram
    ok = bool(send_telegram(message, bypass_router=True))
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="ops",
            producer="eod_open_trade_alert", subject_key="ops:eod_open_trades",
            retention_class="operational", severity="info",
            sanitized_body=message[:500], short_summary=message[:120],
        ))
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass
    log.info("  Sent" if ok else "  Send failed")
    return ok


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    send_eod_alert()
