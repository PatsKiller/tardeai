# Source Export: scripts/report_shadow_source_health.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_shadow_source_health.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `e27dcec68d63bf31f83568b23011e1197a7b2dc299124842618320a3fa8599e2` |
| **File Size** | 6492 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_shadow_source_health.py — Shadow source health across all strategy families.

Read-only. No proposals, trades, or orders.
"""
import argparse, json, sys, yaml
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def main():
    p = argparse.ArgumentParser(description="Shadow source health report")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Load candidate sources registry
    reg_path = PROJ / "config" / "candidate_sources.yaml"
    reg = yaml.safe_load(reg_path.read_text()) if reg_path.exists() else {"sources": {}}
    sources = reg.get("sources", {})

    # Build strategy→source mapping
    strat_sources = {}
    for src_id, src in sources.items():
        for s in src.get("strategies", []):
            strat_sources.setdefault(s, []).append({
                "source_id": src_id,
                "source_type": src.get("source_type", "?"),
                "status": src.get("status", "?"),
                "provider": src.get("provider", "configured"),
            })

    # Get incubator counts
    cur.execute("SELECT strategy_id, COUNT(*) as cnt, MAX(last_seen_at) as latest FROM incubator_universe GROUP BY strategy_id")
    incubator = {r["strategy_id"]: r for r in cur.fetchall()}

    # Get classifier counts
    cur.execute("SELECT strategy_type, COUNT(*) as cnt FROM ticker_strategy_classifications WHERE active=true GROUP BY strategy_type")
    classifiers = {r["strategy_type"]: r["cnt"] for r in cur.fetchall()}

    # Get proposal counts (30d)
    cur.execute("SELECT strategy_id, COUNT(*) as cnt FROM paper_trade_proposals WHERE created_at > NOW() - INTERVAL '30 days' GROUP BY strategy_id")
    proposals = {r["strategy_id"]: r["cnt"] for r in cur.fetchall()}

    # Get finviz screener counts
    cur.execute("SELECT strategy_type, COUNT(*) as cnt, MAX(last_run) as latest FROM finviz_screeners WHERE active=true GROUP BY strategy_type")
    screeners = {r["strategy_type"]: {"count": r["cnt"], "latest": str(r["latest"])[:10]} for r in cur.fetchall()}

    conn.close()

    # All strategies from YAML
    all_strats = sorted([f.stem for f in (PROJ / "config" / "strategies").glob("*.yaml")
                          if f.stem not in ("recommendation_schema", "strategy_schema", "shared_risk_rules")])

    results = []
    for sid in all_strats:
        src_list = strat_sources.get(sid, [])
        inc = incubator.get(sid, {})
        cls_count = classifiers.get(sid, 0)
        prop_count = proposals.get(sid, 0)
        scr = screeners.get(sid, {})

        inc_count = inc.get("cnt", 0)
        inc_latest = str(inc.get("latest", ""))[:10]
        scr_count = scr.get("count", 0)
        scr_latest = scr.get("latest", "never")

        # Determine health
        if prop_count > 0 and inc_count > 5:
            health = "HEALTHY"
        elif inc_count > 5 and prop_count == 0:
            health = "NEEDS_PROMOTER_THRESHOLD_REVIEW"
        elif inc_count > 0 and inc_count <= 5:
            health = "LOW_CANDIDATE_VOLUME"
        elif cls_count > 0 and inc_count == 0:
            health = "CLASSIFIED_NOT_INCUBATED"
        elif scr_count > 0 and cls_count == 0:
            health = "SCREENER_NOT_CLASSIFYING"
        elif len(src_list) > 0 and all(s.get("status") == "SHADOW" for s in src_list):
            health = "SHADOW_ONLY"
        elif len(src_list) > 0 and any("NOT_CONFIGURED" in str(s.get("provider", "")) for s in src_list):
            health = "PROVIDER_MISSING"
        elif len(src_list) == 0:
            health = "NO_SOURCE_MAPPED"
        else:
            health = "CONFIGURED_NOT_PRODUCING"

        results.append({
            "strategy_id": sid,
            "source_count": len(src_list),
            "source_types": list(set(s["source_type"] for s in src_list)),
            "source_statuses": list(set(s["status"] for s in src_list)),
            "finviz_screeners": scr_count,
            "finviz_latest": scr_latest,
            "classified_symbols": cls_count,
            "incubator_symbols": inc_count,
            "incubator_latest": inc_latest,
            "proposals_30d": prop_count,
            "health": health,
        })

    # Summary
    healthy = sum(1 for r in results if r["health"] == "HEALTHY")
    needs_review = sum(1 for r in results if "REVIEW" in r["health"])
    missing = sum(1 for r in results if "MISSING" in r["health"] or "NO_SOURCE" in r["health"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_strategies": len(results),
        "healthy": healthy,
        "needs_review": needs_review,
        "missing_provider": missing,
        "strategies": results,
    }

    if args.verbose:
        print(f"Shadow Source Health: {healthy}/{len(results)} healthy")
        print(f"{'Strategy':30s} {'Srcs':>4s} {'Scr':>3s} {'Cls':>5s} {'Inc':>5s} {'Prop':>4s} {'Health':>30s}")
        for r in results:
            print(f"  {r['strategy_id']:28s} {r['source_count']:4d} {r['finviz_screeners']:3d} "
                  f"{r['classified_symbols']:5d} {r['incubator_symbols']:5d} {r['proposals_30d']:4d} {r['health']:>30s}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Shadow Source Health Report\n",
              f"**{healthy}/{len(results)} strategies healthy**\n",
              f"| Strategy | Sources | Screeners | Classified | Incubator | Proposals 30d | Health |",
              f"|----------|---------|-----------|------------|-----------|---------------|--------|"]
        for r in results:
            md.append(f"| {r['strategy_id']} | {r['source_count']} | {r['finviz_screeners']} | "
                      f"{r['classified_symbols']} | {r['incubator_symbols']} | {r['proposals_30d']} | {r['health']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
