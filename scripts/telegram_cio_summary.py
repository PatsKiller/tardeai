#!/usr/bin/env python3
"""telegram_cio_summary.py — Send CIO decision summary to Telegram.

Severity-gated: only sends critical/high decisions and human review items.

Usage:
    python3 scripts/telegram_cio_summary.py [--dry-run] [--json]
"""
import json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def build_summary() -> dict:
    """Build CIO summary for Telegram. Returns message + metadata."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Critical/high decisions
    cur.execute("""
        SELECT symbol, action, priority, decision_safety, rationale
        FROM cio_decisions
        WHERE priority IN ('critical','high') AND status='proposed'
        AND created_at > NOW() - INTERVAL '24 hours'
        ORDER BY CASE priority WHEN 'critical' THEN 1 ELSE 2 END LIMIT 5
    """)
    critical = cur.fetchall()

    # Human review queue
    cur.execute("""
        SELECT symbol, action, rationale
        FROM cio_decisions
        WHERE human_review_required=TRUE AND status='proposed'
        AND created_at > NOW() - INTERVAL '24 hours'
        LIMIT 5
    """)
    reviews = cur.fetchall()

    # Blocked/unsafe
    cur.execute("""
        SELECT symbol, action, decision_safety
        FROM cio_decisions
        WHERE decision_safety IN ('blocked','unsafe') AND status='proposed'
        AND created_at > NOW() - INTERVAL '24 hours'
        LIMIT 3
    """)
    blocked = cur.fetchall()

    # Strategy rotations
    cur.execute("SELECT source_group_id, target_group_id, rotation_amount_pct FROM strategy_rotation_recommendations WHERE status='proposed' AND created_at > NOW() - INTERVAL '24 hours' LIMIT 3")
    rotations = cur.fetchall()

    # Rebalance plans
    cur.execute("SELECT plan_summary FROM rebalance_plans WHERE plan_status='draft' AND generated_at > NOW() - INTERVAL '24 hours' LIMIT 1")
    plan = cur.fetchone()

    conn.close()

    # Build message
    if not critical and not reviews and not blocked:
        return {"send": False, "reason": "No critical items to send"}

    lines = ["*CIO Intelligence Summary*", ""]

    if critical:
        lines.append(f"*Critical/High Decisions ({len(critical)})*")
        for c in critical:
            lines.append(f"  {c['priority'].upper()} {c['symbol'] or 'PORTFOLIO'}: {c['action']} — {c['rationale'][:60]}")
        lines.append("")

    if reviews:
        lines.append(f"*Human Review Required ({len(reviews)})*")
        for r in reviews:
            lines.append(f"  {r['symbol'] or '?'}: {r['action']} — {r['rationale'][:50]}")
        lines.append("")

    if blocked:
        lines.append(f"*Blocked/Unsafe ({len(blocked)})*")
        for b in blocked:
            lines.append(f"  {b['symbol'] or '?'}: {b['action']} ({b['decision_safety']})")
        lines.append("")

    if rotations:
        lines.append(f"*Rotation Proposals ({len(rotations)})*")
        for r in rotations:
            lines.append(f"  {r['source_group_id']} -> {r['target_group_id']} ({r['rotation_amount_pct']:.1f}%)")
        lines.append("")

    if plan:
        lines.append(f"*Rebalance Plan*: {plan['plan_summary'][:80]}")
        lines.append("")

    lines.append("View details: http://server:7777/v2/cio")

    return {
        "send": True,
        "message": "\n".join(lines),
        "critical_count": len(critical),
        "review_count": len(reviews),
        "blocked_count": len(blocked),
    }


if __name__ == "__main__":
    result = build_summary()

    if "--dry-run" in sys.argv or not result["send"]:
        print(f"[telegram-cio] Dry run: send={result['send']}")
        if result.get("message"):
            print(result["message"])
    else:
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from telegram_alert import send_telegram
            send_telegram(result["message"])
            print(f"[telegram-cio] Sent: {result['critical_count']} critical, {result['review_count']} reviews")
        except Exception as e:
            print(f"[telegram-cio] Send failed: {e}")

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
