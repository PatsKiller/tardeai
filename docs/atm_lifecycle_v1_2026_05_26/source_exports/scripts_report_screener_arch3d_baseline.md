# Source Export: scripts/report_screener_arch3d_baseline.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_screener_arch3d_baseline.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `795dbf3bb697ada62322d370745b8bde2d3343a5f3b3789c3621d34949f48f3e` |
| **File Size** | 6175 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_screener_arch3d_baseline.py — Verify system readiness for falloff lifecycle apply.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from incubator_falloff_lifecycle_policy import classify_source_membership_state, classify_falloff_action


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def main():
    p = argparse.ArgumentParser(description="ARCH-3D baseline (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    # Catalog
    catalog_total = _q(conn, "SELECT count(*) as c FROM incubator_universe", fetch="one")
    catalog_active = _q(conn, "SELECT count(*) as c FROM incubator_universe WHERE status='ACTIVE'", fetch="one")

    # Memberships
    mem_total = _q(conn, "SELECT count(*) as c FROM screener_symbol_membership", fetch="one")
    mem_by_status = _q(conn, "SELECT membership_status, count(*) as c FROM screener_symbol_membership GROUP BY membership_status ORDER BY c DESC")
    mem_status = {r["membership_status"]: int(r["c"]) for r in mem_by_status}

    # History events
    by_event = _q(conn, "SELECT event_type, count(*) as c FROM screener_symbol_membership_history GROUP BY event_type ORDER BY c DESC")
    event_counts = {r["event_type"]: int(r["c"]) for r in by_event}

    dropped_all = _q(conn, """
        SELECT count(DISTINCT symbol) as c FROM screener_symbol_membership
        WHERE membership_status IN ('dropped','stale','expired')
        AND symbol NOT IN (SELECT symbol FROM screener_symbol_membership WHERE membership_status = 'present')
    """, fetch="one")

    # Incubator falloff analysis
    candidates = _q(conn, """
        SELECT iu.symbol, iu.strategy_id, iu.status, iu.first_seen_at, iu.last_seen_at,
               EXTRACT(DAY FROM NOW() - iu.first_seen_at)::int as days_active
        FROM incubator_universe iu WHERE iu.status = 'ACTIVE' ORDER BY iu.symbol
    """)

    actions = {"keep_active": 0, "retain_by_ttl": 0, "expire": 0, "retain_no_data": 0, "review": 0}
    source_missing = 0
    for cand in candidates:
        memberships = _q(conn, """
            SELECT symbol, screener_id, membership_status, present_this_run,
                   consecutive_missing_count, last_seen_in_screener_at
            FROM screener_symbol_membership WHERE symbol = %s
        """, [cand["symbol"]])
        state = classify_source_membership_state(cand, memberships)
        action = classify_falloff_action(cand, state)
        actions[action["action"]] = actions.get(action["action"], 0) + 1
        if state["state"] in ("dropped_from_all", "stale_all_sources", "no_membership_data"):
            source_missing += 1

    # Protection counts
    open_trades = _q(conn, "SELECT count(DISTINCT symbol) as c FROM paper_trades WHERE status='open'", fetch="one")
    pending_proposals = _q(conn, "SELECT count(DISTINCT symbol) as c FROM paper_trade_proposals WHERE status='pending'", fetch="one")
    watchpool = _q(conn, "SELECT count(*) as c FROM strategy_watchpool WHERE current_status NOT IN ('expired','failed')", fetch="one")

    # Last ingestion
    last_ingestion = _q(conn, "SELECT MAX(scanned_at) as ts FROM trade_ai_scans", fetch="one")
    last_backfill = _q(conn, "SELECT MAX(event_at) as ts FROM screener_symbol_membership_history", fetch="one")

    conn.close()

    safe = (mem_status.get("present", 0) > 0 and
            int(catalog_active.get("c", 0)) > 0 and
            actions["keep_active"] > 0)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cataloged_tickers": int(catalog_total.get("c", 0)),
        "active_in_universe": int(catalog_active.get("c", 0)),
        "total_memberships": int(mem_total.get("c", 0)),
        "present": mem_status.get("present", 0),
        "dropped": mem_status.get("dropped", 0),
        "stale": mem_status.get("stale", 0),
        "expired": mem_status.get("expired", 0),
        "reentered_events": event_counts.get("reentered", 0),
        "dropped_from_all": int(dropped_all.get("c", 0)),
        "active_incubator": int(catalog_active.get("c", 0)),
        "source_missing": source_missing,
        "keep_active": actions["keep_active"],
        "retain_by_ttl": actions["retain_by_ttl"],
        "expire_candidates": actions["expire"],
        "retain_no_data": actions["retain_no_data"],
        "review_candidates": actions["review"],
        "open_trades_protected": int(open_trades.get("c", 0)),
        "pending_proposals_protected": int(pending_proposals.get("c", 0)),
        "watchpool_protected": int(watchpool.get("c", 0)),
        "last_ingestion": str(last_ingestion.get("ts", "")),
        "last_backfill": str(last_backfill.get("ts", "")),
        "falloff_apply_safe": safe,
    }

    if args.verbose:
        print("SCREENER-ARCH-3D Baseline")
        for k, v in report.items():
            if k != "generated_at":
                print(f"  {k}: {v}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = ["# SCREENER-ARCH-3D Baseline\n", "| Metric | Value |", "|--------|-------|"]
        for k, v in report.items():
            if k != "generated_at":
                md.append(f"| {k} | {v} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
