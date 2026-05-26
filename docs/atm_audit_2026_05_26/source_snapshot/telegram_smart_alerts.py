#!/usr/bin/env python3
"""telegram_smart_alerts.py — Proactive Telegram alerts based on new intelligence data.

New alert types that leverage the unified intelligence pipeline:
1. Roth conversion reminder (when bracket room is running low or optimal timing)
2. Income milestone (when annual income crosses thresholds)
3. Agent conflict (when agents disagree on a position)
4. Intel spike (when a high-quality article arrives about a held position)
5. Stop proximity (when a position approaches its stop-loss)
6. Medicare countdown (monthly reminder as Dec 2026 approaches)

Usage:
    python3 scripts/telegram_smart_alerts.py --check-all [--telegram]
    python3 scripts/telegram_smart_alerts.py --roth-reminder [--telegram]
    python3 scripts/telegram_smart_alerts.py --income-check [--telegram]
"""
import json, sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _send_tg(msg: str) -> bool:
    try:
        from telegram_alert import send_telegram
        return send_telegram(msg)
    except Exception as e:
        print(f"[smart-alert] Telegram error: {e}")
        return False


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def check_roth_reminder(send: bool = False) -> dict:
    """Alert if Roth conversion room is running low or good timing to convert."""
    from alex_retirement_advisor import get_tax_context
    tax = get_tax_context(2026)
    if tax.get("error"):
        return {"alert": False, "reason": "no tax data"}

    room = tax.get("bracket_room_22pct", 0)
    roth_ytd = tax.get("roth_conversions_ytd", 0)
    target = 51000
    remaining = target - roth_ytd

    alerts = []
    if remaining > 0 and room > remaining:
        # Good time to convert — room available
        month = datetime.now().month
        if month >= 10:  # Q4 reminder
            alerts.append(f"\U0001F4A1 *Roth Conversion Reminder*\n\nOnly {12 - month} month(s) left in 2026.\nConverted: ${roth_ytd:,.0f} of ${target:,.0f} target.\nRemaining: ${remaining:,.0f}\nBracket room available: ${room:,.0f}\n\n_Consider scheduling remaining conversions before Dec 31._")
        elif month == 6 or month == 7:  # Mid-year check
            alerts.append(f"\U0001F4A1 *Roth Mid-Year Check*\n\nConversions YTD: ${roth_ytd:,.0f} of ${target:,.0f} ({int(roth_ytd/target*100)}%)\nBracket room: ${room:,.0f}\n\nYou're {'on track' if roth_ytd >= target * 0.4 else 'behind pace'}.")

    if room < 10000 and room > 0:
        alerts.append(f"\u26A0\uFE0F *Low Bracket Room*\n\nOnly ${room:,.0f} remaining before 22% bracket.\nAny additional income/conversions will be taxed at 22%.")

    result = {"alert": len(alerts) > 0, "count": len(alerts)}
    if alerts and send:
        for a in alerts:
            _send_tg(a)
        result["sent"] = True
    if alerts:
        print(f"[smart-alert] Roth reminder: {len(alerts)} alert(s)")
    return result


def check_income_milestone(send: bool = False) -> dict:
    """Alert when income crosses key thresholds."""
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    try:
        div_cal = json.loads((state_dir / "dividend_calendar.json").read_text())
        income = div_cal.get("total_annual", 0)
    except Exception:
        return {"alert": False}

    milestones = [
        (10000, "\U0001F389 *Income Milestone: $10K/yr!*"),
        (15000, "\U0001F389 *Income Milestone: $15K/yr!*"),
        (20000, "\U0001F389 *Income Milestone: $20K/yr!*"),
        (25000, "\U0001F389 *Income Milestone: $25K/yr!*"),
        (37500, "\U0001F3C6 *Minimum Income Target Reached: $37.5K/yr!*"),
        (55000, "\U0001F3C6 *Target Income Reached: $55K/yr!*"),
    ]

    # Check which milestone we just crossed (within $500 of threshold)
    alerts = []
    for threshold, msg in milestones:
        if threshold - 500 <= income <= threshold + 500:
            full_msg = f"{msg}\n\nCurrent annual income: ${income:,.0f}\nTarget: $55,000/yr\nProgress: {int(income/55000*100)}%"
            alerts.append(full_msg)
            break

    result = {"alert": len(alerts) > 0, "income": income}
    if alerts and send:
        _send_tg(alerts[0])
        result["sent"] = True
    return result


def check_agent_conflicts(send: bool = False) -> dict:
    """Alert when agents disagree significantly on a position."""
    try:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find symbols with both BUY and SELL from different agents (last 7 days)
        cur.execute("""
            WITH recent AS (
                SELECT DISTINCT ON (symbol, agent)
                    symbol, agent, recommendation, confidence
                FROM watchlist_agent_results
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY symbol, agent, created_at DESC
            )
            SELECT symbol,
                   array_agg(agent || ':' || recommendation) as recs
            FROM recent
            GROUP BY symbol
            HAVING bool_or(recommendation IN ('BUY','ADD'))
               AND bool_or(recommendation IN ('SELL','TRIM'))
        """)
        conflicts = cur.fetchall()
        conn.close()

        alerts = []
        for c in conflicts[:3]:
            recs_str = ", ".join(c["recs"])
            alerts.append(f"\u26A0\uFE0F *Agent Conflict: {c['symbol']}*\n\nAgents disagree:\n{recs_str}\n\n_Review at /v2/watchlist?symbol={c['symbol']}_")

        result = {"alert": len(alerts) > 0, "conflicts": len(conflicts)}
        if alerts and send:
            for a in alerts:
                _send_tg(a)
            result["sent"] = True
        if conflicts:
            print(f"[smart-alert] {len(conflicts)} agent conflict(s)")
        return result
    except Exception as e:
        return {"alert": False, "error": str(e)}


def check_stop_proximity(send: bool = False) -> dict:
    """Alert when positions are within 3% of their stop-loss."""
    try:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT symbol, stop_price, latest_price,
                   ((latest_price - stop_price) / latest_price * 100) as distance_pct
            FROM watchlist_strategy_cards
            WHERE stop_price IS NOT NULL AND stop_price > 0 AND latest_price > 0
              AND ((latest_price - stop_price) / latest_price * 100) < 3
            ORDER BY ((latest_price - stop_price) / latest_price * 100) ASC
            LIMIT 5
        """)
        close_stops = cur.fetchall()
        conn.close()

        alerts = []
        if close_stops:
            lines = ["\U0001F6A8 *Stop Proximity Alert*\n"]
            for s in close_stops:
                dist = float(s["distance_pct"])
                emoji = "\U0001F534" if dist < 1.5 else "\U0001F7E1"
                lines.append(f"{emoji} *{s['symbol']}*: {dist:.1f}% from stop (${float(s['stop_price']):.2f})")
            lines.append(f"\n_Review at /v2/risk_")
            alerts.append("\n".join(lines))

        result = {"alert": len(alerts) > 0, "count": len(close_stops)}
        if alerts and send:
            _send_tg(alerts[0])
            result["sent"] = True
        if close_stops:
            print(f"[smart-alert] {len(close_stops)} position(s) near stop")
        return result
    except Exception as e:
        return {"alert": False, "error": str(e)}


def check_medicare_countdown(send: bool = False) -> dict:
    """Monthly reminder about Medicare approaching."""
    medicare_date = date(2026, 12, 1)
    today = date.today()
    days_left = (medicare_date - today).days

    if days_left <= 0:
        return {"alert": False, "reason": "already passed"}

    # Only alert on 1st of each month
    if today.day != 1 and "--force" not in sys.argv:
        return {"alert": False, "reason": "not 1st of month"}

    months_left = days_left // 30
    msg = (
        f"\U0001F3E5 *Medicare Countdown: {days_left} days*\n\n"
        f"Medicare Part A+B starts: December 2026\n"
        f"Months remaining: ~{months_left}\n\n"
        f"*IRMAA Note:* 2024 income determines 2026 premiums.\n"
        f"*Medicaid Note:* If pursuing NY Medicaid ($20,124/yr limit), plan conversions carefully.\n\n"
        f"_Review at /v2/retirement_"
    )

    result = {"alert": True, "days_left": days_left}
    if send:
        _send_tg(msg)
        result["sent"] = True
    print(f"[smart-alert] Medicare countdown: {days_left} days")
    return result


def check_all(send: bool = False) -> dict:
    """Run all smart alert checks."""
    results = {}
    results["roth"] = check_roth_reminder(send)
    results["income"] = check_income_milestone(send)
    results["conflicts"] = check_agent_conflicts(send)
    results["stops"] = check_stop_proximity(send)
    results["medicare"] = check_medicare_countdown(send)

    total_alerts = sum(1 for r in results.values() if r.get("alert"))
    print(f"[smart-alert] Check complete: {total_alerts} alert type(s) fired")
    return results


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    if "--check-all" in sys.argv:
        check_all(send=tg)
    elif "--roth-reminder" in sys.argv:
        check_roth_reminder(send=tg)
    elif "--income-check" in sys.argv:
        check_income_milestone(send=tg)
    elif "--conflicts" in sys.argv:
        check_agent_conflicts(send=tg)
    elif "--stops" in sys.argv:
        check_stop_proximity(send=tg)
    elif "--medicare" in sys.argv:
        check_medicare_countdown(send=tg)
    else:
        print("Usage: --check-all | --roth-reminder | --income-check | --conflicts | --stops | --medicare")
        print("  Add --telegram to send alerts")
        print("  Add --force to bypass date checks")
