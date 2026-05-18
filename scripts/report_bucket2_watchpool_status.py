#!/usr/bin/env python3
"""report_bucket2_watchpool_status.py — Bucket 2 watchpool visibility.

Read-only. No promotion. No proposal creation.

Usage:
    .venv/bin/python scripts/report_bucket2_watchpool_status.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
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


def _json_clean(v):
    if v is None: return None
    if isinstance(v, (int, float, str, bool)): return v
    return str(v)


def main():
    p = argparse.ArgumentParser(description="Bucket 2 watchpool status (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    rows = _db_query("""
        SELECT sw.symbol, sw.strategy_id, sw.current_status, sw.bucket,
               sw.entered_at, sw.expires_at, sw.evaluation_count,
               sw.last_evaluated_at, sw.triggered_proposal_id, sw.failed_reason,
               sw.entry_snapshot
        FROM strategy_watchpool sw
        ORDER BY sw.strategy_id, sw.entered_at DESC
    """) or []

    now = datetime.now(timezone.utc)
    tickers = []
    by_strategy = {}
    by_status = {}

    for r in rows:
        sid = r.get("strategy_id", "")
        status = r.get("current_status", "UNKNOWN")
        by_strategy[sid] = by_strategy.get(sid, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

        days_remaining = None
        if r.get("expires_at"):
            try:
                exp = r["expires_at"]
                if isinstance(exp, str):
                    from datetime import datetime as _dt
                    exp = _dt.fromisoformat(exp.replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                days_remaining = max(0, (exp - now).days)
            except Exception:
                pass

        snap = r.get("entry_snapshot") or {}
        if isinstance(snap, str):
            try: snap = json.loads(snap)
            except: snap = {}

        tickers.append({
            "symbol": r["symbol"], "strategy_id": sid,
            "status": status, "bucket": r.get("bucket"),
            "entered_at": _json_clean(r.get("entered_at")),
            "expires_at": _json_clean(r.get("expires_at")),
            "days_remaining": days_remaining,
            "evaluation_count": r.get("evaluation_count", 0),
            "triggered_proposal_id": r.get("triggered_proposal_id"),
            "score": snap.get("score"), "rvol": snap.get("rvol"),
            "price": snap.get("price"),
        })

    report = {
        "generated_at": now.isoformat(),
        "total_watchpool": len(rows),
        "by_strategy": by_strategy,
        "by_status": by_status,
        "tickers": tickers,
    }

    if args.verbose:
        print(f"Bucket 2 Watchpool — {len(rows)} tickers")
        for sid, cnt in sorted(by_strategy.items()):
            print(f"  {sid}: {cnt}")
        for t in tickers[:20]:
            exp = f"{t['days_remaining']}d left" if t['days_remaining'] is not None else "?"
            print(f"  {t['symbol']:8s} {t['strategy_id']:25s} {t['status']:10s} evals={t['evaluation_count']} {exp}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Bucket 2 Watchpool Status\n", f"Total: {len(rows)}\n",
              "| Symbol | Strategy | Status | Days Left | Evals |",
              "|--------|----------|--------|-----------|-------|"]
        for t in tickers:
            md.append(f"| {t['symbol']} | {t['strategy_id']} | {t['status']} | {t['days_remaining'] or '?'} | {t['evaluation_count']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
