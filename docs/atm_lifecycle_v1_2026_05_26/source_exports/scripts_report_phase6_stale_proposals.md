# Source Export: scripts/report_phase6_stale_proposals.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_phase6_stale_proposals.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c2fb6180154dc6f555210e3154893324028ebeafa0c16fab6bb26c5f88703ca4` |
| **File Size** | 4043 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_phase6_stale_proposals.py — Summarize stale proposal state.

Usage:
    .venv/bin/python scripts/report_phase6_stale_proposals.py --since-days 7 --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since-days", type=int, default=7)
    p.add_argument("--symbol", type=str)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Pending proposals with freshness classification
    sys.path.insert(0, str(PROJ / "scripts"))
    from phase6_proposal_staleness_policy import classify_proposal_staleness, TERMINAL_STATUSES
    terminal_list = ",".join(f"'{s}'" for s in TERMINAL_STATUSES)
    cur.execute(f"""
        SELECT id, symbol, strategy_id, status, created_at, expires_at, proposal_timeframe_class
        FROM paper_trade_proposals WHERE status NOT IN ({terminal_list})
        ORDER BY created_at DESC LIMIT %s
    """, [args.limit])
    cols = [d[0] for d in cur.description]
    proposals = [dict(zip(cols, r)) for r in cur.fetchall()]

    fresh, stale, expired, requires_refresh = 0, 0, 0, 0
    by_strategy = {}
    details = []
    now = datetime.now(timezone.utc)
    for prop in proposals:
        c = classify_proposal_staleness(prop, now)
        if c["fresh"]: fresh += 1
        elif c["expired"]: expired += 1
        elif c["stale"]: stale += 1
        if c["requires_refresh"]: requires_refresh += 1
        strat = prop.get("strategy_id", "unknown")
        by_strategy.setdefault(strat, {"fresh": 0, "stale": 0, "expired": 0})
        by_strategy[strat][c["status"] if c["status"] in ("fresh", "stale", "expired") else "stale"] += 1
        details.append({"id": prop["id"], "symbol": prop["symbol"], "strategy": strat,
                        "status": c["status"], "age_min": c["age_minutes"], "reason": c["reason"][:80]})

    # Sweep audit
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM paper_proposal_stale_sweep_audit WHERE created_at >= NOW() - INTERVAL '%s days'" % args.since_days)
    sweep_row = cur.fetchone()
    conn.close()

    report = {"date": now.isoformat(), "pending_total": len(proposals),
              "fresh": fresh, "stale": stale, "expired": expired,
              "requires_refresh": requires_refresh, "by_strategy": by_strategy,
              "sweep_audits": sweep_row[0], "last_sweep": str(sweep_row[1]) if sweep_row[1] else None,
              "details": details}

    if args.verbose:
        print(f"Stale Proposal Report (last {args.since_days} days)")
        print(f"  Pending: {len(proposals)}, Fresh: {fresh}, Stale: {stale}, Expired: {expired}")
        print(f"  Sweep audits: {sweep_row[0]}, Last sweep: {sweep_row[1]}")
        for d in details[:20]:
            print(f"    #{d['id']} {d['symbol']} [{d['status']}] {d['reason'][:60]}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Stale Proposal Summary", f"\n**Pending:** {len(proposals)} | **Fresh:** {fresh} | **Stale:** {stale} | **Expired:** {expired}",
              f"\n**Sweep audits:** {sweep_row[0]} | **Last sweep:** {sweep_row[1]}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
