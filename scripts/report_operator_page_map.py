#!/usr/bin/env python3
"""report_operator_page_map.py — Map all operator-facing pages/tabs and their purposes.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

PAGES = [
    {
        "route": "/v3/trading",
        "menu_tab": "Trading > Approvals",
        "purpose": "Review and approve/reject pending paper trade proposals from Maria/Steph agents",
        "alert_categories": ["pending_proposal", "proposal_expired", "approval_required"],
    },
    {
        "route": "/v3/journal",
        "menu_tab": "Journal > Paper Journal",
        "purpose": "View open and recently closed paper trades, P&L, hold durations",
        "alert_categories": ["trade_opened", "trade_closed", "stop_triggered", "target_hit"],
    },
    {
        "route": "/v3/journal",
        "menu_tab": "Journal > Paper Outcomes",
        "purpose": "Analyze historical paper trade outcomes, win rates, strategy performance",
        "alert_categories": ["outcome_scored", "lesson_generated"],
    },
    {
        "route": "/v3/journal",
        "menu_tab": "Journal > Journal Reports",
        "purpose": "Aggregated journal analytics — strategy comparison, time-based patterns",
        "alert_categories": ["journal_report_ready"],
    },
    {
        "route": "/v3/system",
        "menu_tab": "System > Paper Governance",
        "purpose": "Governance rules, risk gates, system facts, agent calibration status",
        "alert_categories": ["governance_violation", "risk_gate_blocked", "calibration_drift"],
    },
    {
        "route": "/v3/trading",
        "menu_tab": "TradeAI Scanner",
        "purpose": "Live screener candidates, watchpool status, AI analyst signals",
        "alert_categories": ["watchpool_add", "watchpool_promote", "screener_alert"],
    },
    {
        "route": "/v3/risk",
        "menu_tab": "Risk",
        "purpose": "Portfolio risk metrics, exposure, drawdown, system health alerts",
        "alert_categories": ["risk_breach", "drawdown_warning", "system_health"],
    },
    {
        "route": "/v3/risk",
        "menu_tab": "Recovery",
        "purpose": "Recovery plans for stopped-out or failed trades, re-entry conditions",
        "alert_categories": ["recovery_candidate", "recovery_triggered"],
    },
    {
        "route": "/v3/intelligence",
        "menu_tab": "Intelligence Sources",
        "purpose": "Manage data sources — news feeds, social, transcript discovery, Aegis ingestion",
        "alert_categories": ["source_stale", "ingestion_failure", "transcript_new"],
    },
]


def main():
    p = argparse.ArgumentParser(description="Operator page map (read-only)")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(PAGES),
        "pages": PAGES,
        "alert_category_index": {},
    }

    # Build reverse index: alert_category -> [routes]
    for page in PAGES:
        for cat in page["alert_categories"]:
            report["alert_category_index"].setdefault(cat, []).append(page["route"])

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

    print(f"Total operator pages: {report['total_pages']}  |  Alert categories mapped: {len(report['alert_category_index'])}")


def _to_md(r):
    lines = [
        f"# Operator Page Map",
        f"Generated: {r['generated_at']}\n",
        f"## Pages ({r['total_pages']} total)\n",
        "| Route | Menu Tab | Purpose | Alert Categories |",
        "|-------|----------|---------|------------------|",
    ]
    for pg in r["pages"]:
        cats = ", ".join(pg["alert_categories"])
        lines.append(f"| `{pg['route']}` | {pg['menu_tab']} | {pg['purpose']} | {cats} |")

    lines.append(f"\n## Alert Category Index\n")
    for cat, routes in sorted(r["alert_category_index"].items()):
        lines.append(f"- **{cat}** -> {', '.join(f'`{r}`' for r in routes)}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
