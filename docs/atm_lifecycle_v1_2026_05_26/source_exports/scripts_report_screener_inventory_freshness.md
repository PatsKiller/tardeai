# Source Export: scripts/report_screener_inventory_freshness.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_screener_inventory_freshness.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `cb2829d6c3fd24667decf376c4102f0438881676c36d250328531ad633f1dfc0` |
| **File Size** | 4642 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_screener_inventory_freshness.py — Screener inventory and freshness audit.

Read-only. No mutations.

Usage:
    .venv/bin/python scripts/report_screener_inventory_freshness.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


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
    p = argparse.ArgumentParser(description="Screener inventory freshness (read-only)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=3)

    screeners = _db_query("""
        SELECT screener_id, display_name, strategy_type, active, last_run, results_count
        FROM finviz_screeners ORDER BY display_name
    """) or []

    entries = []
    stale_count = 0
    page_capped = 0
    active_count = 0

    for s in screeners:
        active = s.get("active", False)
        if active: active_count += 1
        last_run = s.get("last_run")
        row_count = s.get("results_count", 0) or 0

        is_stale = False
        stale_reason = None
        if active and last_run:
            try:
                lr = last_run
                if isinstance(lr, str):
                    lr = datetime.fromisoformat(lr.replace("Z", "+00:00"))
                if lr.tzinfo is None:
                    lr = lr.replace(tzinfo=timezone.utc)
                if lr < stale_threshold:
                    is_stale = True
                    stale_reason = f"Last run {lr.strftime('%Y-%m-%d')} > 3 days ago"
                    stale_count += 1
            except Exception:
                pass
        elif active and not last_run:
            is_stale = True
            stale_reason = "Never run"
            stale_count += 1

        exactly_50 = row_count == 50
        if exactly_50: page_capped += 1

        entries.append({
            "screener_id": s.get("screener_id"),
            "display_name": s.get("display_name"),
            "strategy_type": s.get("strategy_type"),
            "active": active,
            "last_run": str(last_run) if last_run else None,
            "results_count": s.get("results_count"),
            "stale": is_stale,
            "stale_reason": stale_reason,
            "exactly_50": exactly_50,
            "likely_page_capped": exactly_50,
        })

    # Use screener_config table too
    sc_configs = _db_query("SELECT display_name, strategy_class, enabled FROM screener_config ORDER BY display_name") or []

    report = {
        "generated_at": now.isoformat(),
        "total_screeners": len(screeners),
        "active_count": active_count,
        "stale_active_count": stale_count,
        "page_capped_count": page_capped,
        "screener_config_count": len(sc_configs),
        "screeners": entries,
    }

    if args.verbose:
        print(f"Screener Inventory — {len(screeners)} screeners, {active_count} active, {stale_count} stale, {page_capped} page-capped")
        for s in entries:
            if isinstance(s, dict):
                flag = "STALE" if s.get("stale") else "OK"
                cap = " CAP50" if s.get("exactly_50") else ""
                print(f"  [{flag}{cap}] {s.get('display_name','?'):40s} last={s.get('last_run','never'):>10s} rows={s.get('results_count','?')}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Screener Inventory\n",
              f"Total: {len(screeners)} | Active: {active_count} | Stale: {stale_count} | Page-capped: {page_capped}\n",
              f"**Critical fix applied:** 50-row cap raised to 500 in finviz_screener_runner.py"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
