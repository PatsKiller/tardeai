#!/usr/bin/env python3
"""backfill_proposal_route_audit.py — Backfill missing route audit evidence.

Default: dry-run. Requires --apply to write.
Does NOT change proposal strategy_id. Does NOT create trades/orders.

Usage:
    .venv/bin/python scripts/backfill_proposal_route_audit.py --dry-run --verbose
    .venv/bin/python scripts/backfill_proposal_route_audit.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

BACKFILL_SOURCE = "SP-2B-backfill"


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
    p = argparse.ArgumentParser(description="Backfill proposal route audit (default: dry-run)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--proposal-id", type=int)
    p.add_argument("--symbol", type=str)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Find proposals missing route audit
    where = "WHERE ptp.created_at > %s"
    params = [since]
    if args.proposal_id:
        where += " AND ptp.id = %s"
        params.append(args.proposal_id)
    if args.symbol:
        where += " AND ptp.symbol = %s"
        params.append(args.symbol)

    proposals = _db_query(f"""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id,
               ptp.primary_strategy_id, ptp.setup_stack
        FROM paper_trade_proposals ptp
        LEFT JOIN strategy_setup_matches ssm ON ssm.proposal_id = ptp.id
        {where}
        GROUP BY ptp.id, ptp.symbol, ptp.strategy_id, ptp.primary_strategy_id, ptp.setup_stack
        HAVING count(ssm.id) = 0
        ORDER BY ptp.created_at DESC
    """, params) or []

    if args.verbose:
        print(f"Route Audit Backfill ({'DRY RUN' if args.dry_run else 'APPLY'}) — {len(proposals)} proposals missing audit")

    # Load YAML configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception:
        configs = {}

    if not configs:
        print("ERROR: Could not load strategy configs")
        sys.exit(1)

    # Load router
    try:
        from multi_setup_router import route_symbol, store_setup_matches
    except ImportError:
        print("ERROR: Could not import multi_setup_router")
        sys.exit(1)

    results = []
    applied = 0
    mismatches = 0
    skipped = 0

    for pr in proposals:
        pid = pr["id"]
        sym = pr["symbol"]
        orig_sid = pr.get("strategy_id") or ""

        # Get ticker characteristics from latest scan
        scan = _db_query("""
            SELECT price, rvol, float_m, gap_pct, change_pct, score, decision,
                   catalyst, catalyst_verified, catalyst_confidence,
                   sector, industry
            FROM trade_ai_scans WHERE symbol = %s
            ORDER BY scanned_at DESC LIMIT 1
        """, [sym], fetch="one")

        if not scan or not scan.get("price"):
            skipped += 1
            results.append({"proposal_id": pid, "symbol": sym, "status": "skipped", "reason": "insufficient_scan_data"})
            if args.verbose:
                print(f"  SKIP {sym} (id={pid}): no scan data")
            continue

        # Build signal-like dict for router
        signal = {
            "symbol": sym,
            "price": float(scan.get("price") or 0),
            "rvol": float(scan.get("rvol") or 0),
            "float_m": float(scan.get("float_m") or 0),
            "gap_pct": float(scan.get("gap_pct") or 0),
            "change_pct": float(scan.get("change_pct") or 0),
            "score": int(scan.get("score") or 0),
            "decision": scan.get("decision") or "WAIT",
            "catalyst": scan.get("catalyst"),
            "catalyst_verified": scan.get("catalyst_verified"),
            "catalyst_confidence": scan.get("catalyst_confidence"),
            "sector": scan.get("sector"),
            "industry": scan.get("industry"),
        }

        # Route
        try:
            route_result = route_symbol(sym, signal, configs)
        except Exception as e:
            skipped += 1
            results.append({"proposal_id": pid, "symbol": sym, "status": "error", "reason": str(e)})
            continue

        matches = route_result.get("setup_stack", [])
        backfill_primary = route_result.get("primary_strategy_id")
        mismatch = backfill_primary and backfill_primary != orig_sid

        if mismatch:
            mismatches += 1

        result = {
            "proposal_id": pid,
            "symbol": sym,
            "original_strategy_id": orig_sid,
            "backfill_primary": backfill_primary,
            "mismatch": mismatch,
            "match_count": len(matches),
            "status": "dry_run" if args.dry_run else "applied",
        }
        results.append(result)

        if args.verbose:
            flag = " *** MISMATCH" if mismatch else ""
            print(f"  {sym} (id={pid}): orig={orig_sid}, backfill={backfill_primary}, matches={len(matches)}{flag}")

        # Apply
        if not args.dry_run and matches:
            try:
                from db_adapter import _get_conn
                conn = _get_conn()
                if conn:
                    config_hashes = {sid: cfg.get("_config_hash", "") for sid, cfg in configs.items()}
                    store_setup_matches(conn, sym, pid, BACKFILL_SOURCE, matches, config_hashes)
                    conn.close()
                    applied += 1
                    result["status"] = "applied"
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "apply",
        "total_missing": len(proposals),
        "processed": len(results),
        "applied": applied,
        "skipped": skipped,
        "mismatches": mismatches,
        "backfill_source": BACKFILL_SOURCE,
        "results": results[:100],
    }

    if args.verbose:
        print(f"\nSummary: {len(proposals)} missing, {applied} applied, {skipped} skipped, {mismatches} mismatches")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Route Audit Backfill Report ({'DRY RUN' if args.dry_run else 'APPLIED'})",
              f"\nMissing: {len(proposals)} | Applied: {applied} | Skipped: {skipped} | Mismatches: {mismatches}\n"]
        if mismatches:
            md.append("## Mismatches (original vs backfill primary)\n")
            for r in results:
                if r.get("mismatch"):
                    md.append(f"- {r['symbol']}: orig={r['original_strategy_id']} vs backfill={r['backfill_primary']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
