#!/usr/bin/env python3
"""generate_daily_intelligence_report.py — DB-backed daily intelligence digest.

Reads from DB (not JSON) to produce:
- Decision safety summary
- Human review required list
- Alert escalations
- Income goal progress
- Layer allocation status
- Unresolved conflicts
- Stale analyses

Usage:
    python3 scripts/generate_daily_intelligence_report.py [--telegram] [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def generate_report() -> dict:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Decision safety counts
    cur.execute("SELECT decision_safety, COUNT(*) as cnt FROM watchlist_final_synthesis GROUP BY decision_safety")
    safety_counts = {r["decision_safety"]: r["cnt"] for r in cur.fetchall()}

    # Human review required
    cur.execute("""
        SELECT fs.symbol, fs.recommendation, fs.decision_safety, fs.safety_reasons
        FROM watchlist_final_synthesis fs
        WHERE fs.human_review_required = true
        ORDER BY fs.updated_at DESC LIMIT 10
    """)
    human_reviews = [dict(r) for r in cur.fetchall()]

    # Unsafe decisions
    cur.execute("""
        SELECT symbol, recommendation, decision_safety, safety_overrides
        FROM watchlist_final_synthesis
        WHERE decision_safety = 'unsafe'
        ORDER BY updated_at DESC LIMIT 10
    """)
    unsafe = [dict(r) for r in cur.fetchall()]

    # Recent alerts (last 24h)
    cur.execute("""
        SELECT alert_type, symbol, severity, data_quality_status, created_at
        FROM alert_events WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC LIMIT 20
    """)
    recent_alerts = [dict(r) for r in cur.fetchall()]

    # Income progress
    cur.execute("SELECT * FROM income_projection_history ORDER BY snapshot_date DESC LIMIT 1")
    income_proj = cur.fetchone()

    # Layer allocation
    cur.execute("""
        SELECT pl.layer_id, pl.layer_name, pl.target_min_pct, pl.target_max_pct
        FROM portfolio_layers pl ORDER BY pl.target_min_pct DESC
    """)
    layers = cur.fetchall()

    # Stale analyses
    cur.execute("""
        SELECT symbol, analysis_stage, updated_at
        FROM watchlist_analysis_maturity
        WHERE updated_at < NOW() - INTERVAL '7 days'
        AND analysis_stage NOT IN ('raw_data_only', 'strategy_card_ready')
        ORDER BY updated_at LIMIT 10
    """)
    stale = [dict(r) for r in cur.fetchall()]

    # Agent conflicts
    cur.execute("""
        SELECT symbol, conflicts_detected
        FROM watchlist_final_synthesis
        WHERE conflicts_detected IS NOT NULL AND conflicts_detected != '[]'::jsonb
        ORDER BY updated_at DESC LIMIT 10
    """)
    conflicts = [dict(r) for r in cur.fetchall()]

    # Data quality issues
    cur.execute("""
        SELECT COUNT(*) as cnt FROM alert_events
        WHERE data_quality_status NOT IN ('valid', 'unknown')
        AND created_at > NOW() - INTERVAL '7 days'
    """)
    dq_count = cur.fetchone()["cnt"]

    # Hermes research feed (daily-report wiring gate 2026-06-07): surface what the Hermes research fleet
    # produced + notable findings so the operator sees Hermes intelligence in the daily digest.
    hermes_feed = {"research_24h": 0, "top_findings": []}
    try:
        cur.execute("SELECT count(*) cnt FROM hermes_research_intelligence WHERE created_at > NOW() - INTERVAL '24 hours'")
        hermes_feed["research_24h"] = cur.fetchone()["cnt"]
        cur.execute("""SELECT topic, left(summary,140) summary FROM hermes_research_intelligence
                       WHERE summary IS NOT NULL AND (topic ILIKE '%%weak%%' OR topic ILIKE '%%challenge%%'
                             OR research_type='deep_research_local')
                       ORDER BY created_at DESC LIMIT 5""")
        hermes_feed["top_findings"] = [{"topic": (r["topic"] or "")[:60], "summary": r["summary"]} for r in cur.fetchall()]
    except Exception:
        pass

    conn.close()

    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "decision_safety": safety_counts,
        "human_reviews_required": len(human_reviews),
        "human_review_symbols": [r["symbol"] for r in human_reviews],
        "unsafe_decisions": len(unsafe),
        "unsafe_symbols": [{
            "symbol": r["symbol"],
            "recommendation": r["recommendation"],
            "overrides": r.get("safety_overrides") or {},
        } for r in unsafe],
        "alerts_24h": len(recent_alerts),
        "alert_types": {},
        "income": {
            "current": float(income_proj.get("total_annual_income", 0) or 0) if income_proj else 0,
            "forward": float(income_proj.get("forward_annual_income", 0) or 0) if income_proj else 0,
            "target_pct": float(income_proj.get("target_goal_pct", 0) or 0) if income_proj else 0,
            "gap": float(income_proj.get("income_gap_to_target", 0) or 0) if income_proj else 0,
        },
        "stale_analyses": len(stale),
        "stale_symbols": [r["symbol"] for r in stale],
        "unresolved_conflicts": len(conflicts),
        "data_quality_issues_7d": dq_count,
        "hermes_research": hermes_feed,
    }

    # Count alert types
    for a in recent_alerts:
        t = a.get("alert_type", "unknown")
        report["alert_types"][t] = report["alert_types"].get(t, 0) + 1

    return report


def format_telegram(report: dict) -> str:
    lines = [
        f"*Daily Intelligence Report — {report['date']}*",
        "",
        f"*Decision Safety*",
        f"  Safe: {report['decision_safety'].get('safe', 0)} | Unsafe: {report['decision_safety'].get('unsafe', 0)} | Blocked: {report['decision_safety'].get('blocked', 0)}",
        f"  Human reviews needed: {report['human_reviews_required']}",
    ]
    if report["human_review_symbols"]:
        lines.append(f"  Symbols: {', '.join(report['human_review_symbols'][:5])}")

    lines += [
        "",
        f"*Income Progress*",
        f"  Current: ${report['income']['current']:,.0f}/yr ({report['income']['target_pct']:.0f}% of target)",
        f"  Gap: ${report['income']['gap']:,.0f}",
        "",
        f"*Alerts (24h)*: {report['alerts_24h']}",
    ]
    if report["alert_types"]:
        lines.append(f"  Types: {', '.join(f'{k}:{v}' for k, v in report['alert_types'].items())}")

    lines += [
        f"  Data quality issues (7d): {report['data_quality_issues_7d']}",
        f"  Stale analyses: {report['stale_analyses']}",
        f"  Unresolved conflicts: {report['unresolved_conflicts']}",
    ]

    hr = report.get("hermes_research", {})
    if hr:
        lines.append(f"\n*Hermes research (24h)*: {hr.get('research_24h', 0)} findings")
        for f in (hr.get("top_findings") or [])[:3]:
            lines.append(f"  • {f['topic']}: {f['summary']}")

    return "\n".join(lines)


if __name__ == "__main__":
    report = generate_report()

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_telegram(report))

    if "--telegram" in sys.argv:
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from telegram_alert import send_telegram
            send_telegram(format_telegram(report))
            print("\n[report] Sent to Telegram")
        except Exception as e:
            print(f"\n[report] Telegram failed: {e}")
