# Source Export: scripts/report_proposal_source_attribution.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_proposal_source_attribution.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `aa63240be89f480ee001025302564e4d0c321d138a7be1245f56da3e02823fa1` |
| **File Size** | 3764 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_proposal_source_attribution.py — Proposal source attribution audit.

Read-only. No mutation.

Usage:
    .venv/bin/python scripts/report_proposal_source_attribution.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

ALLOWED_SOURCES = {"auto_proposal_generator", "incubator_promoter", "system", "telegram_manual",
                   "operator_manual", "strategy_watchpool", "paper_trade_logger", "manual"}
BLOCKED_SOURCES = {"daily_momentum_scalp", "tradeai_daily_scalp", "external_scalp", "unknown_external"}


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Proposal source attribution (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    by_source = _db_query("""
        SELECT proposed_by, discovery_source, count(*) as c
        FROM paper_trade_proposals WHERE created_at > %s
        GROUP BY proposed_by, discovery_source ORDER BY c DESC
    """, [since]) or []

    sources = []
    leakage = False
    for r in by_source:
        src = r.get("proposed_by") or "unknown"
        disc = r.get("discovery_source") or "unknown"
        classification = "allowed" if src in ALLOWED_SOURCES else "blocked" if src in BLOCKED_SOURCES else "review_required"
        if classification == "blocked":
            leakage = True
        sources.append({
            "proposed_by": src, "discovery_source": disc,
            "count": r["c"], "classification": classification,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_proposals": sum(s["count"] for s in sources),
        "sources": sources,
        "leakage_found": leakage,
        "allowed_sources": sorted(ALLOWED_SOURCES),
        "blocked_sources": sorted(BLOCKED_SOURCES),
    }

    if args.verbose:
        print(f"Proposal Source Attribution — {report['total_proposals']} proposals")
        for s in sources:
            flag = "OK" if s["classification"] == "allowed" else "BLOCKED" if s["classification"] == "blocked" else "REVIEW"
            print(f"  [{flag}] proposed_by={s['proposed_by']}, discovery={s['discovery_source']}: {s['count']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Proposal Source Attribution\n",
              f"Total: {report['total_proposals']} | Leakage: {'YES' if leakage else 'No'}\n",
              "| Source | Discovery | Count | Status |", "|--------|-----------|-------|--------|"]
        for s in sources:
            md.append(f"| {s['proposed_by']} | {s['discovery_source']} | {s['count']} | {s['classification']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
