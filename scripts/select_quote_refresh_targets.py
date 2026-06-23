#!/usr/bin/env python3
"""select_quote_refresh_targets.py — Select symbols needing quote refresh.

Read-only. No actual quote fetch. No DB writes.

Usage:
    .venv/bin/python scripts/select_quote_refresh_targets.py --mode all --verbose
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
    p = argparse.ArgumentParser(description="Select quote refresh targets (read-only)")
    p.add_argument("--mode", choices=["pending", "incubator", "broker", "all"], default="all")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    targets = []

    # Pending proposals
    if args.mode in ("pending", "all"):
        rows = _db_query("""
            SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.status,
                   mqs.provider as last_provider, mqs.created_at as last_checked,
                   mqs.is_execution_eligible
            FROM paper_trade_proposals ptp
            LEFT JOIN LATERAL (
                SELECT provider, created_at, is_execution_eligible
                FROM market_quote_snapshots WHERE symbol = ptp.symbol
                ORDER BY created_at DESC LIMIT 1
            ) mqs ON true
            WHERE ptp.status = 'PENDING'
            ORDER BY mqs.created_at ASC NULLS FIRST
            LIMIT %s
        """, [args.limit]) or []

        for r in rows:
            age = None
            if r.get("last_checked"):
                try:
                    lc = r["last_checked"]
                    if hasattr(lc, 'tzinfo') and lc.tzinfo is None:
                        lc = lc.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - lc).total_seconds()
                except Exception:
                    pass

            targets.append({
                "symbol": r["symbol"], "source": "paper_proposal",
                "proposal_id": r["id"], "strategy_id": r.get("strategy_id"),
                "last_provider": r.get("last_provider"),
                "last_checked_age_seconds": round(age) if age else None,
                "is_execution_eligible": r.get("is_execution_eligible"),
                "reason": "pending_proposal_needs_fresh_quote",
                "priority": 1,
            })

    # Live broker queue (APPROVED_FOR_PAPER_TEST at Schwab/Fidelity)
    if args.mode in ("broker", "all"):
        try:
            from broker_queue_hygiene import fetch_broker_queue_rows
            brows = fetch_broker_queue_rows()[: args.limit]
            for r in brows:
                age = None
                if r.get("updated_at"):
                    try:
                        ua = r["updated_at"]
                        if hasattr(ua, "tzinfo") and ua.tzinfo is None:
                            ua = ua.replace(tzinfo=timezone.utc)
                        age = (datetime.now(timezone.utc) - ua).total_seconds()
                    except Exception:
                        pass
                targets.append({
                    "symbol": r["symbol"],
                    "source": "broker_queue",
                    "proposal_id": r.get("id"),
                    "strategy_id": r.get("strategy_id"),
                    "last_checked_age_seconds": round(age) if age else None,
                    "reason": "broker_queue_needs_fresh_quote",
                    "priority": 0,
                })
        except Exception:
            pass

    # Incubator candidates — use family-specific min_score thresholds (MAP-5D)
    if args.mode in ("incubator", "all"):
        try:
            from promoter_family_threshold_policy import get_family_thresholds
        except ImportError:
            get_family_thresholds = None

        rows = _db_query("""
            SELECT iu.symbol, iu.strategy_id, iu.latest_score,
                   mqs.provider as last_provider, mqs.created_at as last_checked
            FROM incubator_universe iu
            LEFT JOIN LATERAL (
                SELECT provider, created_at FROM market_quote_snapshots
                WHERE symbol = iu.symbol ORDER BY created_at DESC LIMIT 1
            ) mqs ON true
            WHERE iu.status = 'ACTIVE' AND iu.latest_score >= 5
            AND iu.promoted_to_proposal_at IS NULL
            ORDER BY iu.latest_score DESC, mqs.created_at ASC NULLS FIRST
            LIMIT %s
        """, [args.limit * 3]) or []  # fetch more, filter by family threshold

        # Filter by family-specific min_score
        if get_family_thresholds:
            filtered = []
            for r in rows:
                th = get_family_thresholds(r.get("strategy_id", ""))
                min_score = th.get("min_score", 38)
                if (r.get("latest_score") or 0) >= min_score:
                    filtered.append(r)
            rows = filtered[:args.limit]
        else:
            # Fallback: use old threshold
            rows = [r for r in rows if (r.get("latest_score") or 0) >= 38][:args.limit]

        for r in rows:
            age = None
            if r.get("last_checked"):
                try:
                    lc = r["last_checked"]
                    if hasattr(lc, 'tzinfo') and lc.tzinfo is None:
                        lc = lc.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - lc).total_seconds()
                except Exception:
                    pass

            targets.append({
                "symbol": r["symbol"], "source": "incubator_candidate",
                "strategy_id": r.get("strategy_id"), "score": r.get("latest_score"),
                "last_provider": r.get("last_provider"),
                "last_checked_age_seconds": round(age) if age else None,
                "reason": "incubator_ready_needs_quote",
                "priority": 2,
            })

    # Deduplicate by symbol (keep highest priority)
    seen = set()
    deduped = []
    for t in sorted(targets, key=lambda x: x["priority"]):
        if t["symbol"] not in seen:
            seen.add(t["symbol"])
            deduped.append(t)
    targets = deduped[:args.limit]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode, "limit": args.limit,
        "total_targets": len(targets),
        "pending_count": len([t for t in targets if t["source"] == "paper_proposal"]),
        "incubator_count": len([t for t in targets if t["source"] == "incubator_candidate"]),
        "targets": targets,
    }

    if args.verbose:
        print(f"Quote Refresh Targets ({args.mode}) — {len(targets)} symbols")
        for t in targets[:20]:
            age = f"{t['last_checked_age_seconds']}s" if t.get("last_checked_age_seconds") else "never"
            prov = t.get('last_provider') or '?'
            print(f"  [{t['priority']}] {t['symbol']:8s} {t['source']:20s} provider={prov:8s} age={age}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Quote Refresh Targets ({args.mode})\n",
              f"Total: {len(targets)} | Pending: {report['pending_count']} | Incubator: {report['incubator_count']}\n"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
