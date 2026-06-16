#!/usr/bin/env python3
"""report_operator_command_surface.py — Report what needs operator attention right now.

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


HEALTH_FILE = PROJ / "data" / "portfolios" / "state" / "system_health_alert.json"

PAGE_DESTINATIONS = {
    "pending_proposals": "/v3/trading",
    "open_trades": "/v3/journal",
    "watchpool_candidates": "/v3/trading",
    "system_health": "/v3/risk",
}


def main():
    p = argparse.ArgumentParser(description="Operator command surface (read-only)")
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
        "p0_immediate": [],
        "p1_digest": [],
        "p2_dashboard": {},
        "p3_log": {},
        "page_destinations": PAGE_DESTINATIONS,
    }

    # --- Pending proposals (P0 if any) ---
    try:
        pending = _q(conn, "SELECT id, symbol, strategy_id, created_at FROM paper_trade_proposals WHERE status = 'pending' ORDER BY created_at DESC")
        if pending:
            for row in pending:
                report["p0_immediate"].append({
                    "type": "pending_proposal",
                    "symbol": row.get("symbol"),
                    "strategy": row.get("strategy_id"),
                    "created_at": str(row.get("created_at")),
                    "page": PAGE_DESTINATIONS["pending_proposals"],
                })
        report["p2_dashboard"]["pending_proposals_count"] = len(pending)
    except Exception as e:
        report["p2_dashboard"]["pending_proposals_error"] = str(e)

    # --- Open paper trades (P1 digest) ---
    try:
        open_trades = _q(conn, "SELECT id, symbol, strategy_id, entry_date, entry_price FROM paper_trades WHERE status = 'open' ORDER BY entry_date DESC")
        for row in open_trades:
            report["p1_digest"].append({
                "type": "open_trade",
                "symbol": row.get("symbol"),
                "strategy": row.get("strategy_id"),
                "entry_date": str(row.get("entry_date")),
                "entry_price": str(row.get("entry_price")),
                "page": PAGE_DESTINATIONS["open_trades"],
            })
        report["p2_dashboard"]["open_trades_count"] = len(open_trades)
    except Exception as e:
        report["p2_dashboard"]["open_trades_error"] = str(e)

    # --- Watchpool active candidates (P2 dashboard) ---
    try:
        watchpool = _q(conn, """
            SELECT symbol, strategy_id, current_status, updated_at
            FROM strategy_watchpool
            WHERE current_status NOT IN ('expired', 'failed')
            ORDER BY updated_at DESC
        """)
        report["p2_dashboard"]["watchpool_active_count"] = len(watchpool)
        report["p2_dashboard"]["watchpool_symbols"] = [r["symbol"] for r in watchpool[:20]]
    except Exception as e:
        report["p2_dashboard"]["watchpool_error"] = str(e)

    # --- System health (P0 if alert, else P3) ---
    try:
        if HEALTH_FILE.exists():
            health = json.loads(HEALTH_FILE.read_text())
            status = health.get("status", "unknown")
            if status in ("red", "critical"):
                report["p0_immediate"].append({
                    "type": "system_health",
                    "status": status,
                    "detail": health.get("message", ""),
                    "page": PAGE_DESTINATIONS["system_health"],
                })
            else:
                report["p3_log"]["system_health_status"] = status
                report["p3_log"]["system_health_message"] = health.get("message", "")
        else:
            report["p3_log"]["system_health_file"] = "not found"
    except Exception as e:
        report["p3_log"]["system_health_error"] = str(e)

    # --- Log-level counts (P3) ---
    log_dir = PROJ / "logs"
    try:
        log_files = list(log_dir.glob("*.log")) if log_dir.exists() else []
        report["p3_log"]["log_file_count"] = len(log_files)
    except Exception:
        report["p3_log"]["log_file_count"] = 0

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

    p0c = len(report["p0_immediate"])
    p1c = len(report["p1_digest"])
    print(f"P0 items: {p0c}  |  P1 digest: {p1c}  |  Watchpool active: {report['p2_dashboard'].get('watchpool_active_count', '?')}")


def _to_md(r):
    lines = [
        f"# Operator Command Surface",
        f"Generated: {r['generated_at']}\n",
        f"## P0 — Immediate Attention ({len(r['p0_immediate'])} items)",
    ]
    if r["p0_immediate"]:
        for item in r["p0_immediate"]:
            lines.append(f"- **{item['type']}** {item.get('symbol', '')} — page: `{item.get('page', '')}`")
    else:
        lines.append("- None")

    lines.append(f"\n## P1 — Digest ({len(r['p1_digest'])} items)")
    if r["p1_digest"]:
        for item in r["p1_digest"][:10]:
            lines.append(f"- {item['type']}: {item.get('symbol', '')} ({item.get('strategy', '')})")
        if len(r["p1_digest"]) > 10:
            lines.append(f"- ... and {len(r['p1_digest']) - 10} more")
    else:
        lines.append("- None")

    lines.append(f"\n## P2 — Dashboard Counts")
    for k, v in r["p2_dashboard"].items():
        lines.append(f"- {k}: {v}")

    lines.append(f"\n## P3 — Log / Background")
    for k, v in r["p3_log"].items():
        lines.append(f"- {k}: {v}")

    lines.append(f"\n## Page Destinations")
    for k, v in r["page_destinations"].items():
        lines.append(f"- {k} -> `{v}`")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
