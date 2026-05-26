#!/usr/bin/env python3
"""report_operator_telegram_noise_audit.py — Audit Telegram alert noise over last 14 days.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


# Known noise patterns — messages that are typically non-actionable
NOISE_PATTERNS = [
    {"label": "WAIT/AVOID in Trade AI messages", "sql_fragment": "action_taken ILIKE '%WAIT%' OR action_taken ILIKE '%AVOID%'"},
    {"label": "STOP repeats", "sql_fragment": "action_taken ILIKE '%STOP%'"},
    {"label": "Iris audit notifications", "sql_fragment": "alert_type ILIKE '%iris%' OR alert_type ILIKE '%audit%'"},
    {"label": "Cron success pings", "sql_fragment": "alert_type ILIKE '%cron%' AND (action_taken ILIKE '%success%' OR action_taken ILIKE '%ok%' OR action_taken IS NULL)"},
]


def main():
    p = argparse.ArgumentParser(description="Telegram noise audit (read-only)")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 14,
        "total_alerts": 0,
        "by_type": {},
        "by_tier": {},
        "by_action": {},
        "noise_estimates": [],
        "estimated_actionable": 0,
        "estimated_non_actionable": 0,
        "top_spam_categories": [],
        "recommended_routing": [],
    }

    try:
        # Total alerts
        total = _q(conn, "SELECT count(*) AS c FROM alert_dispatch_log WHERE created_at > NOW() - INTERVAL '14 days'", fetch="one")
        report["total_alerts"] = int(total.get("c", 0))

        # By type, tier, action
        by_type = _q(conn, "SELECT alert_type, count(*) AS c FROM alert_dispatch_log WHERE created_at > NOW() - INTERVAL '14 days' GROUP BY alert_type ORDER BY c DESC")
        report["by_type"] = {r["alert_type"]: int(r["c"]) for r in by_type}

        by_tier = _q(conn, "SELECT tier, count(*) AS c FROM alert_dispatch_log WHERE created_at > NOW() - INTERVAL '14 days' GROUP BY tier ORDER BY c DESC")
        report["by_tier"] = {str(r["tier"]): int(r["c"]) for r in by_tier}

        by_action = _q(conn, "SELECT action_taken, count(*) AS c FROM alert_dispatch_log WHERE created_at > NOW() - INTERVAL '14 days' GROUP BY action_taken ORDER BY c DESC")
        report["by_action"] = {str(r["action_taken"]): int(r["c"]) for r in by_action}

        # Full grouped breakdown
        full = _q(conn, """
            SELECT alert_type, tier, action_taken, count(*) AS c
            FROM alert_dispatch_log
            WHERE created_at > NOW() - INTERVAL '14 days'
            GROUP BY alert_type, tier, action_taken
            ORDER BY c DESC
        """)

        # Noise estimates
        total_noise = 0
        for pat in NOISE_PATTERNS:
            try:
                noise_q = f"SELECT count(*) AS c FROM alert_dispatch_log WHERE created_at > NOW() - INTERVAL '14 days' AND ({pat['sql_fragment']})"
                noise_count = int(_q(conn, noise_q, fetch="one").get("c", 0))
            except Exception:
                noise_count = 0
            report["noise_estimates"].append({"pattern": pat["label"], "count": noise_count})
            total_noise += noise_count

        report["estimated_non_actionable"] = total_noise
        report["estimated_actionable"] = max(0, report["total_alerts"] - total_noise)

        # Top spam: types with highest count that are likely noise
        sorted_types = sorted(report["by_type"].items(), key=lambda x: x[1], reverse=True)
        report["top_spam_categories"] = [{"alert_type": t, "count": c} for t, c in sorted_types[:5]]

        # Recommended routing
        report["recommended_routing"] = [
            {"category": "WAIT/AVOID signals", "recommendation": "Suppress from Telegram, log-only"},
            {"category": "Cron success pings", "recommendation": "Suppress from Telegram, dashboard badge only"},
            {"category": "STOP repeats", "recommendation": "Deduplicate — send once per symbol per 24h"},
            {"category": "Iris audit", "recommendation": "Daily digest instead of per-event"},
            {"category": "Actionable alerts (P0/P1)", "recommendation": "Keep real-time Telegram delivery"},
        ]

    except Exception as e:
        report["error"] = str(e)
        if args.verbose:
            import traceback; traceback.print_exc()

    # Output
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        md = _to_md(report)
        Path(args.output_md).write_text(md)
        print(f"MD written to {args.output_md}")

    if args.verbose:
        print(json.dumps(report, indent=2, default=str))

    print(f"Total alerts (14d): {report['total_alerts']}  |  Actionable est: {report['estimated_actionable']}  |  Noise est: {report['estimated_non_actionable']}")


def _to_md(r):
    lines = [
        f"# Telegram Noise Audit",
        f"Generated: {r['generated_at']}  |  Window: {r['window_days']} days\n",
        f"## Summary",
        f"- Total alerts: **{r['total_alerts']}**",
        f"- Estimated actionable: **{r['estimated_actionable']}**",
        f"- Estimated non-actionable (noise): **{r['estimated_non_actionable']}**\n",
        f"## By Alert Type",
    ]
    for t, c in sorted(r["by_type"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {t} | {c} |")
    lines.append(f"\n## By Tier")
    for t, c in sorted(r["by_tier"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {t} | {c} |")
    lines.append(f"\n## By Action Taken")
    for t, c in sorted(r["by_action"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {t} | {c} |")
    lines.append(f"\n## Noise Estimates")
    for n in r["noise_estimates"]:
        lines.append(f"- {n['pattern']}: **{n['count']}**")
    lines.append(f"\n## Top Spam Categories")
    for s in r["top_spam_categories"]:
        lines.append(f"- {s['alert_type']}: {s['count']}")
    lines.append(f"\n## Recommended Routing")
    for rec in r["recommended_routing"]:
        lines.append(f"- **{rec['category']}**: {rec['recommendation']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
