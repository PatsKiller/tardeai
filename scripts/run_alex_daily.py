#!/usr/bin/env python3
"""run_alex_daily.py — Smart Alex automation with daily/weekly/monthly modes.

Daily (4-5 AM): Full portfolio scan + tax + agent + intel summary
Weekly (Sunday): Strategy review, income gap, rebalancing, Roth note
Monthly (1st): Deep tax reconciliation, Roth ladder refresh, full review

Usage:
    python3 scripts/run_alex_daily.py --daily [--telegram]
    python3 scripts/run_alex_daily.py --weekly [--telegram]
    python3 scripts/run_alex_daily.py --monthly [--telegram]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _save_report(report_type: str, title: str, content: str, provider: str = "", cost: float = 0):
    """Store a weekly/monthly report in DB for the AI Analyst page."""
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("""INSERT INTO ai_reports (report_type, title, content, provider, cost)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (report_type, title, content, provider, cost))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[alex-auto] Report save error: {e}")


def _send_tg(msg: str) -> bool:
    try:
        from telegram_alert import send_telegram
        return send_telegram(msg)
    except Exception as e:
        print(f"[alex-auto] Telegram error: {e}")
        return False


def _load_portfolio_summary() -> dict:
    """Load portfolio totals, income, and top movers from state files."""
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    totals = {"value": 0, "income": 0, "day_change": 0, "positions": 0}
    try:
        holdings = json.loads((state_dir / "holdings.json").read_text())
        pt = holdings.get("portfolio_totals", {})
        totals["value"] = pt.get("total_value", 0)
        totals["day_change"] = pt.get("day_change", 0)
        totals["day_change_pct"] = pt.get("day_change_pct", 0)
        totals["positions"] = len(holdings.get("holdings", []))
    except Exception:
        pass
    try:
        div_cal = json.loads((state_dir / "dividend_calendar.json").read_text())
        totals["income"] = div_cal.get("total_annual", 0)
    except Exception:
        pass
    return totals


def _get_tax_summary() -> dict:
    """Load tax context for alerts."""
    try:
        from alex_retirement_advisor import get_tax_context
        return get_tax_context(2026)
    except Exception:
        return {}


def _get_agent_summary() -> str:
    """Get agent activity summary for alerts."""
    try:
        import psycopg2, psycopg2.extras
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT agent, count(*) as cnt,
                       count(CASE WHEN recommendation IN ('BUY','ADD') THEN 1 END) as buys,
                       count(CASE WHEN recommendation IN ('SELL','TRIM') THEN 1 END) as sells
                       FROM watchlist_agent_results
                       WHERE created_at > NOW() - INTERVAL '7 days'
                       GROUP BY agent ORDER BY cnt DESC""")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return ""
        lines = []
        for r in rows:
            name = r["agent"].replace("_agent", "").title()
            lines.append(f"  {name}: {r['cnt']} analyses ({r['buys']} buy, {r['sells']} sell)")
        return "\n".join(lines)
    except Exception:
        return ""


def _get_escalations() -> list:
    """Check for agent conflicts or escalations."""
    try:
        import psycopg2, psycopg2.extras
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT symbol, intent FROM agent_handoffs
                       WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '1 day'
                       ORDER BY created_at DESC LIMIT 3""")
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _get_intel_highlights() -> str:
    """Get top intelligence items for the day."""
    try:
        from intel_query import get_intel_for_agent
        items = get_intel_for_agent("Alex", min_quality=50, days=2, limit=3)
        if not items:
            return ""
        lines = []
        for item in items[:3]:
            src = item.get("source_type", "?")[0].upper()
            title = (item.get("title") or "")[:45]
            q = item.get("quality_score", 0)
            lines.append(f"  [{src}] Q:{q} {title}")
        return "\n".join(lines)
    except Exception:
        return ""


def _text_progress_bar(value: float, max_val: float, width: int = 15) -> str:
    """Create a text-based progress bar: [▓▓▓▓▓░░░░░] 45%"""
    pct = min(1.0, max(0, value / max_val)) if max_val > 0 else 0
    filled = int(pct * width)
    empty = width - filled
    bar = "\u2593" * filled + "\u2591" * empty
    return f"[{bar}] {pct*100:.0f}%"


def _format_alert_line(alert: dict) -> str:
    """Format a single alert as a scannable emoji line."""
    sym = alert.get("symbol", "?")
    trigger = alert.get("trigger", "")
    t_lower = trigger.lower()
    if "daily move" in t_lower or "significant" in t_lower:
        pct = trigger.split(":")[-1].strip() if ":" in trigger else trigger
        return f"\U0001F534 *{sym}*: {pct}" if "-" in pct else f"\U0001F7E2 *{sym}*: +{pct}"
    elif "rsi" in t_lower:
        emoji = "\U0001F534" if "overbought" in t_lower else "\U0001F7E2"
        return f"{emoji} *{sym}*: {trigger}"
    elif "sma" in t_lower or "crossing" in t_lower or "ma" in t_lower:
        pct = trigger.split("SMA20:")[-1].rstrip(")").strip() if "SMA20:" in trigger else ""
        return f"\U0001F535 *{sym}*: SMA20 cross ({pct})" if pct else f"\U0001F535 *{sym}*: {trigger}"
    return f"\u26A0\uFE0F *{sym}*: {trigger}"


def run_daily(send_telegram: bool = False):
    """Full daily scan with portfolio, tax, agent, and intel context."""
    print(f"[alex-daily] {datetime.now().isoformat()} — Starting daily scan")

    from alex_retirement_advisor import scan_portfolio_for_alerts
    alerts = scan_portfolio_for_alerts(send_telegram=False)
    pf = _load_portfolio_summary()
    tax = _get_tax_summary()

    if send_telegram:
        date_str = datetime.now().strftime('%b %d')
        divider = "\u2501" * 24
        income_target = 55000
        income_pct = int(pf["income"] / income_target * 100) if income_target else 0
        day_emoji = "\U0001F7E2" if (pf.get("day_change", 0)) >= 0 else "\U0001F534"

        lines = [
            f"\U0001F4CA *Alex Daily Brief \u2014 {date_str}*",
            divider,
            "",
            f"{day_emoji} *Portfolio:* ${pf['value']/1e6:.2f}M ({'+' if pf.get('day_change',0) >= 0 else ''}${pf.get('day_change',0):,.0f} today)",
            f"\U0001F4B0 *Income:* ${pf['income']:,.0f}/yr {_text_progress_bar(pf['income'], income_target)}",
            f"\U0001F3AF *Gap:* ${income_target - pf['income']:,.0f} remaining to ${income_target:,} target",
        ]

        # Tax status
        if tax and not tax.get("error"):
            bracket = tax.get("current_bracket", 12)
            room = tax.get("bracket_room_22pct", 0)
            roth_ytd = tax.get("roth_conversions_ytd", 0)
            lines.append(f"\U0001F3E6 *Tax:* {bracket}% bracket | Room: ${room:,.0f} | Roth YTD: ${roth_ytd:,.0f}")

        # Alerts section
        if alerts:
            lines.append("")
            lines.append(f"\u26A1 *{len(alerts)} Alert(s):*")
            for a in alerts[:6]:
                lines.append(_format_alert_line(a))

        # Escalations
        escalations = _get_escalations()
        if escalations:
            lines.append("")
            lines.append("\U0001F6A8 *Escalations:*")
            for e in escalations:
                lines.append(f"  {e['symbol']}: {e['intent'][:50]}")

        # Agent activity (last 7 days)
        agent_sum = _get_agent_summary()
        if agent_sum:
            lines.append("")
            lines.append("\U0001F916 *Agent Activity (7d):*")
            lines.append(agent_sum)

        # Intel highlights
        intel = _get_intel_highlights()
        if intel:
            lines.append("")
            lines.append("\U0001F4F0 *Intel:*")
            lines.append(intel)

        lines.append("")
        lines.append(divider)
        lines.append(f"\U0001F517 http://ms01-openclaw:7777/v2/")
        _send_tg("\n".join(lines))

    elif not alerts and send_telegram:
        # No alerts — still send brief status
        pf = _load_portfolio_summary()
        _send_tg(f"\u2705 *Alex Daily \u2014 {datetime.now().strftime('%b %d')}*\nNo alerts. Portfolio: ${pf['value']/1e6:.2f}M. All quiet.")

    print(f"[alex-daily] Done: {len(alerts)} alerts")
    return {"mode": "daily", "alerts": len(alerts)}


def run_weekly(send_telegram: bool = False):
    """Strategy review + income gap + suggestions + agent summary."""
    print(f"[alex-weekly] {datetime.now().isoformat()} — Starting weekly review")

    from alex_retirement_advisor import get_tax_context
    from llm_router import get_llm_response

    tax = get_tax_context(2026)
    bracket_room = tax.get("bracket_room_22pct", 0) if not tax.get("error") else 0
    pf = _load_portfolio_summary()
    income_target = 55000

    prompt = f"""/no_think You are Alex, a certified retirement planner. Provide a concise weekly portfolio review.

PORTFOLIO: ${pf['value']/1e6:.2f}M across 4 accounts. Income: ${pf['income']:,.0f}/yr vs ${income_target:,} target (gap ${income_target - pf['income']:,.0f}).
Income generators: 9.2% allocation (target 25-40%). Core compounders: 42%.
22 actionable recommendations exist. 6 blocked by safety rules.
Roth conversions YTD: ${tax.get('roth_conversions_ytd', 35000):,.0f}. Bracket room: ${bracket_room:,.0f}.
Medicare: December 2026. Medicaid consideration: NY limit $20,124/yr.

Provide:
1. Week's key observations (2-3 bullets)
2. Income gap progress assessment
3. Top rebalancing priority
4. One Roth conversion timing note (considering IRMAA + Medicaid tradeoff)
5. One risk watch item
Keep it under 250 words. Warm, professional tone."""

    result = get_llm_response("agent_narrative", prompt, max_tokens=500)
    review = result.get("response", "Weekly review unavailable") if result.get("success") else "Weekly review failed"

    if send_telegram:
        provider = result.get("provider", "?")
        divider = "\u2501" * 24
        income_pct = int(pf["income"] / income_target * 100) if income_target else 0

        msg_lines = [
            f"\U0001F4CB *Alex Weekly Review \u2014 {datetime.now().strftime('%b %d')}*",
            divider,
            "",
            f"\U0001F4CA Portfolio: ${pf['value']/1e6:.2f}M",
            f"\U0001F4B0 Income: ${pf['income']:,.0f}/yr {_text_progress_bar(pf['income'], income_target)}",
            f"\U0001F3E6 Tax: {tax.get('current_bracket', 12)}% | Room: ${bracket_room:,.0f} | Roth: ${tax.get('roth_conversions_ytd', 35000):,.0f}",
            "",
            divider,
            "",
            review[:1800],
            "",
            divider,
        ]

        # Agent summary
        agent_sum = _get_agent_summary()
        if agent_sum:
            msg_lines.append("")
            msg_lines.append("\U0001F916 *Agent Activity:*")
            msg_lines.append(agent_sum)

        msg_lines.append(f"\n_via {provider} \u2022 http://ms01-openclaw:7777/v2/ai-analyst_")
        _send_tg("\n".join(msg_lines))

    # YAML threshold analysis — propose changes if patterns found
    try:
        import psycopg2 as _pg
        _pw = ""
        for _line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if _line.startswith("DB_PASSWORD="): _pw = _line.split("=", 1)[1].strip()
        _conn = _pg.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=_pw)
        proposals = analyze_indicator_thresholds(_conn)
        if proposals:
            propose_yaml_changes(_conn, proposals)
            _send_tg(
                f"[ALEX WEEKLY] Indicator threshold analysis: "
                f"{len(proposals)} YAML change proposal(s) submitted. "
                f"Use 'tasks' command to review."
            )
        _conn.close()
    except Exception as e:
        print(f"[alex-weekly] Threshold analysis error: {e}")

    # Save to DB for AI Analyst page
    _save_report("weekly", f"Weekly Review — {datetime.now().strftime('%b %d, %Y')}",
                 review, provider=result.get("provider", ""), cost=result.get("cost_estimate", 0))

    print(f"[alex-weekly] Done via {result.get('provider', '?')}")
    return {"mode": "weekly", "provider": result.get("provider")}


def analyze_indicator_thresholds(conn) -> list:
    """Weekly analysis: find indicator thresholds producing bad entries.

    Reads trade_backtest_results — looks for patterns where:
    - RSI at entry > current entry_max and outcome Grade D/F
    - Left too much on table (exit too early)

    Returns list of proposals for YAML parameter changes.
    """
    proposals = []

    try:
        import yaml
        config = yaml.safe_load(open(str(PROJECT_ROOT / 'config' / 'indicator_strategies.yaml')))
        rsi_entry_max = config['strategies']['rsi']['entry_max']

        cur = conn.cursor()

        # Pattern 1: High RSI entries performing poorly
        cur.execute("""
            SELECT COUNT(*) as trade_count,
                   AVG(entry_rsi) as avg_entry_rsi,
                   AVG(actual_pnl_pct) as avg_pnl_pct
            FROM trade_backtest_results
            WHERE entry_grade IN ('D', 'F')
            AND entry_rsi > %s
            AND computed_at > NOW() - INTERVAL '90 days'
            AND data_quality = 'good'
        """, [rsi_entry_max - 5])
        row = cur.fetchone()

        if row and row[0] and int(row[0]) >= 5:
            trade_count = int(row[0])
            avg_rsi = float(row[1]) if row[1] else 0
            avg_pnl = float(row[2]) if row[2] else 0

            proposals.append({
                'parameter': 'rsi.entry_max',
                'current_value': rsi_entry_max,
                'proposed_value': max(45, rsi_entry_max - 3),
                'evidence': (
                    f"{trade_count} Grade D/F entries with RSI>{rsi_entry_max - 5} in last 90 days. "
                    f"Avg entry RSI: {avg_rsi:.1f}. Avg P&L: {avg_pnl:+.1f}%. "
                    f"Tightening RSI entry_max from {rsi_entry_max} to "
                    f"{max(45, rsi_entry_max - 3)} may filter weakest setups."
                ),
                'trade_count': trade_count,
                'avg_grade': 'D/F',
                'confidence': min(0.9, 0.5 + (trade_count / 20)),
            })

        # Pattern 2: Early exits leaving money on table
        cur.execute("""
            SELECT COUNT(*), AVG(left_on_table_20d)
            FROM trade_backtest_results
            WHERE exit_grade IN ('D', 'F')
            AND left_on_table_20d > 15
            AND computed_at > NOW() - INTERVAL '90 days'
            AND data_quality = 'good'
        """)
        row = cur.fetchone()
        if row and row[0] and int(row[0]) >= 5:
            atr_target = config['strategies'].get('atr', {}).get('target_multiple_scalp', 1.5)
            proposals.append({
                'parameter': 'atr.target_multiple_scalp',
                'current_value': atr_target,
                'proposed_value': 2.0,
                'evidence': (
                    f"{int(row[0])} Grade D/F exits with avg {float(row[1]):.0f}% left on table (20d). "
                    f"Increasing ATR target multiple from {atr_target}x to 2.0x may capture more upside."
                ),
                'trade_count': int(row[0]),
                'avg_grade': 'D/F',
                'confidence': 0.6,
            })

    except Exception as e:
        print(f"[alex-weekly] Indicator threshold analysis failed: {e}")

    return proposals


def propose_yaml_changes(conn, proposals: list):
    """Submit YAML parameter change proposals to john_decision_queue.

    Each proposal becomes one pending task for John to approve/reject.
    """
    if not proposals:
        return

    cur = conn.cursor()
    for p in proposals:
        # Check if similar proposal already pending
        cur.execute("""
            SELECT id FROM john_decision_queue
            WHERE category = 'yaml_parameter_change'
            AND title LIKE %s
            AND status = 'pending_john'
            LIMIT 1
        """, [f"%{p['parameter']}%"])

        if cur.fetchone():
            continue  # Already has pending proposal for this parameter

        provenance = {
            'parameter': p['parameter'],
            'current_value': p['current_value'],
            'proposed_value': p['proposed_value'],
            'evidence': p['evidence'],
            'trade_count': p['trade_count'],
            'confidence': p['confidence'],
            'yaml_file': 'config/indicator_strategies.yaml',
        }

        cur.execute("""
            INSERT INTO john_decision_queue
                (category, title, description, priority, status, provenance, created_at)
            VALUES (
                'yaml_parameter_change',
                %s,
                %s,
                'normal',
                'pending_john',
                %s::jsonb,
                NOW()
            )
        """, [
            f"[YAML TUNING] {p['parameter']}: {p['current_value']} -> {p['proposed_value']}",
            (
                f"Confidence: {p['confidence']:.0%}. {p['trade_count']} trades analyzed.\n\n"
                f"{p['evidence']}"
            ),
            json.dumps(provenance)
        ])

    conn.commit()
    print(f"[alex-weekly] {len(proposals)} YAML proposals submitted to john_decision_queue")


def run_monthly(send_telegram: bool = False):
    """Deep reconciliation — tax, Roth ladder, allocation, Medicaid, full review."""
    print(f"[alex-monthly] {datetime.now().isoformat()} — Starting monthly review")

    from alex_retirement_advisor import roth_conversion_analysis, get_tax_context
    from llm_router import get_llm_response

    # Roth ladder refresh
    roth = roth_conversion_analysis()
    tax = get_tax_context(2026)
    pf = _load_portfolio_summary()
    income_target = 55000

    # Full monthly summary
    prompt = f"""/no_think You are Alex, a certified retirement planner. Provide a monthly portfolio reconciliation.

PORTFOLIO: ${pf['value']/1e6:.2f}M. Income: ${pf['income']:,.0f}/yr vs ${income_target:,} target. Gap: ${income_target - pf['income']:,.0f}.
Tax: AGI ${tax.get('agi', 49342):,.0f}, bracket {tax.get('current_bracket', 22)}%, Roth YTD ${tax.get('roth_conversions_ytd', 35000):,.0f}, room ${tax.get('bracket_room_22pct', 0):,.0f}.
Medicare: December 2026. NY Medicaid income limit: $20,124/yr (conversions push above).
22 actionable recommendations. Income generators at 9.2% (target 25-40%).
Business loss carryforward: $4,392.

Provide monthly report:
1. Income progress vs target (are we on track?)
2. Allocation drift assessment
3. Tax optimization status (Roth conversions, bracket management, IRMAA impact)
4. Medicaid planning note (should we slow conversions?)
5. Top 3 recommended actions for next month
6. Risk watch items
Keep under 350 words. Include specific numbers. Address Medicaid vs Roth tradeoff."""

    result = get_llm_response("cio_synthesis", prompt, max_tokens=700, high_impact=True)
    review = result.get("response", "Monthly review unavailable") if result.get("success") else "Monthly review failed"

    if send_telegram:
        provider = result.get("provider", "?")
        bracket = tax.get("current_bracket", 22)
        room = tax.get("bracket_room_22pct", 0)
        roth_ytd = tax.get("roth_conversions_ytd", 35000)
        agi = tax.get("agi", 49342)
        divider = "\u2501" * 24
        income_pct = int(pf["income"] / income_target * 100) if income_target else 0

        msg_lines = [
            f"\U0001F4CA *Alex Monthly Review \u2014 {datetime.now().strftime('%B %Y')}*",
            divider,
            "",
            f"\U0001F4B0 *Portfolio Summary:*",
            f"  Value: ${pf['value']/1e6:.2f}M",
            f"  Income: ${pf['income']:,.0f}/yr {_text_progress_bar(pf['income'], income_target)}",
            f"  Gap to target: ${income_target - pf['income']:,.0f}",
            "",
            f"\U0001F3E6 *Tax & Conversion:*",
            f"  AGI: ${agi:,.0f} | Bracket: {bracket}%",
            f"  Roth YTD: ${roth_ytd:,.0f} {_text_progress_bar(roth_ytd, 51000)}",
            f"  22% room: ${room:,.0f}",
            f"  Biz loss: $4,392 (extra capacity)",
            "",
            f"\U0001F3E5 *Medicare/Medicaid:*",
            f"  Medicare: Dec 2026 (IRMAA 2yr lookback)",
            f"  Medicaid limit: $20,124/yr",
            f"  Current MAGI: ${agi:,.0f} \u2014 {'ABOVE' if agi > 20124 else 'BELOW'} Medicaid limit",
            "",
            divider,
            "",
            review[:2000],
            "",
            divider,
        ]

        # Intel highlights
        intel = _get_intel_highlights()
        if intel:
            msg_lines.append("")
            msg_lines.append("\U0001F4F0 *Recent Intel:*")
            msg_lines.append(intel)

        msg_lines.append(f"\n_via {provider} \u2022 http://ms01-openclaw:7777/v2/retirement_")
        _send_tg("\n".join(msg_lines))

    # Save to DB for AI Analyst page
    _save_report("monthly", f"Monthly Review — {datetime.now().strftime('%B %Y')}",
                 review, provider=result.get("provider", ""), cost=result.get("cost_estimate", 0))

    print(f"[alex-monthly] Done via {result.get('provider', '?')}")
    return {"mode": "monthly", "provider": result.get("provider")}


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    if "--daily" in sys.argv:
        run_daily(send_telegram=tg)
    elif "--weekly" in sys.argv:
        run_weekly(send_telegram=tg)
    elif "--monthly" in sys.argv:
        run_monthly(send_telegram=tg)
    else:
        print("Usage: --daily|--weekly|--monthly [--telegram]")
