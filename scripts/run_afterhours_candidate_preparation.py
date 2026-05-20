#!/usr/bin/env python3
"""run_afterhours_candidate_preparation.py — Prepare after-hours candidate snapshots.

Evaluates screener universe for after-hours readiness classification.
No trades. No orders.

Usage:
    .venv/bin/python scripts/run_afterhours_candidate_preparation.py --dry-run --verbose
    .venv/bin/python scripts/run_afterhours_candidate_preparation.py --apply --session after_close --verbose
"""
import argparse, json, sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def load_active_symbols(conn, limit=None):
    """Load symbols with membership_status='present'."""
    sql = """
        SELECT DISTINCT symbol
        FROM screener_symbol_membership
        WHERE membership_status = 'present'
        ORDER BY symbol
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _q(conn, sql)


def get_strategy_fit(conn, symbol):
    """Get latest strategy fit audit for symbol (top match only)."""
    row = _q(conn, """
        SELECT audit_run_id, strategy_id, match_strength, normalized_score,
               recommendation, missing_fields, family_gate_status, liquidity_gate_status
        FROM universe_strategy_fit_audit
        WHERE symbol = %s AND top_match_for_symbol = TRUE
        ORDER BY evaluated_at DESC
        LIMIT 1
    """, [symbol], fetch="one")
    return row


def get_quote_freshness(conn, symbol):
    """Check trade_ai_scans for latest scanned_at for symbol."""
    row = _q(conn, """
        SELECT scanned_at
        FROM trade_ai_scans
        WHERE symbol = %s
        ORDER BY scanned_at DESC
        LIMIT 1
    """, [symbol], fetch="one")
    if not row or not row.get("scanned_at"):
        return "missing"
    scanned_at = row["scanned_at"]
    try:
        if hasattr(scanned_at, "timestamp"):
            ts = scanned_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
        else:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(scanned_at)).replace(tzinfo=timezone.utc)).total_seconds()
        return "fresh" if age < 86400 else "stale"
    except Exception:
        return "stale"


def classify_readiness(match_strength, quote_status, missing_fields, liquidity_gate, family_gate):
    """Classify readiness_status based on strategy fit and quote freshness."""
    if match_strength == "STRONG" and quote_status == "fresh":
        return "ready_for_review"
    if match_strength == "STRONG" and quote_status != "fresh":
        return "proposal_candidate_pending_market_open_check"
    if match_strength == "MODERATE":
        return "watchpool_candidate"
    if match_strength in ("MISSING_DATA", "NO_MATCH") and missing_fields:
        return "needs_data"
    if match_strength == "BLOCKED" and liquidity_gate == "FAIL":
        return "blocked_by_liquidity"
    if match_strength == "BLOCKED":
        return "blocked_by_strategy_fit"
    return "no_fit"


def main():
    p = argparse.ArgumentParser(description="After-hours candidate preparation (default: dry-run)")
    p.add_argument("--session", type=str, default="after_close")
    p.add_argument("--date", type=str, default="today")
    p.add_argument("--run-strategy-fit", action="store_true")
    p.add_argument("--prepare-candidates", action="store_true")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False
    dry_run = args.dry_run

    run_date = date.today().isoformat() if args.date == "today" else args.date
    session = args.session
    snapshot_id = f"afterhours_{run_date}_{session}"
    mode = "DRY RUN" if dry_run else "APPLY"

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    # Load active symbols
    symbols = load_active_symbols(conn, args.limit)
    if args.verbose:
        print(f"[{mode}] Session: {session} | Date: {run_date}")
        print(f"  Snapshot ID: {snapshot_id}")
        print(f"  Active symbols loaded: {len(symbols)}")

    # Evaluate each symbol
    candidates = []
    stats = {
        "symbols_considered": len(symbols),
        "strategy_fit_evaluated": 0,
        "ready_for_review": 0,
        "proposal_candidate_pending_market_open_check": 0,
        "watchpool_candidate": 0,
        "needs_data": 0,
        "blocked_by_liquidity": 0,
        "blocked_by_strategy_fit": 0,
        "no_fit": 0,
    }

    for sym_row in symbols:
        symbol = sym_row["symbol"]

        # Get strategy fit
        fit = get_strategy_fit(conn, symbol)
        match_strength = fit.get("match_strength", "") if fit else ""
        normalized_score = fit.get("normalized_score", 0) if fit else 0
        strategy_id = fit.get("strategy_id", "") if fit else ""
        recommendation = fit.get("recommendation", "") if fit else ""
        missing_fields = fit.get("missing_fields", "") if fit else ""
        family_gate = fit.get("family_gate_status", "") if fit else ""
        liquidity_gate = fit.get("liquidity_gate_status", "") if fit else ""

        if fit:
            stats["strategy_fit_evaluated"] += 1

        # Get quote freshness
        quote_status = get_quote_freshness(conn, symbol)

        # Classify readiness
        readiness = classify_readiness(match_strength, quote_status, missing_fields, liquidity_gate, family_gate)
        stats[readiness] = stats.get(readiness, 0) + 1

        # Build blockers
        blockers = []
        if liquidity_gate == "FAIL":
            blockers.append("liquidity_gate")
        if family_gate == "FAIL":
            blockers.append("family_gate")
        if quote_status != "fresh":
            blockers.append(f"quote_{quote_status}")
        if match_strength in ("MISSING_DATA",) and missing_fields:
            blockers.append("missing_data")

        # Next required action
        if readiness == "ready_for_review":
            next_action = "human_review"
        elif readiness == "proposal_candidate_pending_market_open_check":
            next_action = "market_open_quote_check"
        elif readiness == "needs_data":
            next_action = "fill_missing_data"
        elif readiness in ("blocked_by_liquidity", "blocked_by_strategy_fit"):
            next_action = "none_blocked"
        elif readiness == "watchpool_candidate":
            next_action = "monitor_for_upgrade"
        else:
            next_action = "none"

        candidate = {
            "snapshot_id": snapshot_id,
            "run_date": run_date,
            "session": session,
            "symbol": symbol,
            "source_screeners": "screener_symbol_membership",
            "catalog_status": "active",
            "membership_status": "present",
            "strategy_fit_status": match_strength or "not_evaluated",
            "top_strategy": strategy_id,
            "top_strategy_score": normalized_score or 0,
            "quote_status": quote_status,
            "readiness_status": readiness,
            "blockers": json.dumps(blockers) if blockers else None,
            "next_required_action": next_action,
            "proposal_candidate_allowed": False,
            "executable_now": False,
            "human_review_only": True,
        }
        candidates.append(candidate)

    # Sort by score descending for reporting
    candidates.sort(key=lambda c: c["top_strategy_score"] or 0, reverse=True)

    if not dry_run:
        cur = conn.cursor()
        for c in candidates:
            cur.execute("""
                INSERT INTO afterhours_candidate_snapshot
                    (snapshot_id, run_date, session, symbol, source_screeners,
                     catalog_status, membership_status, strategy_fit_status,
                     top_strategy, top_strategy_score, quote_status,
                     readiness_status, blockers, next_required_action,
                     proposal_candidate_allowed, executable_now, human_review_only)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (snapshot_id, symbol) DO UPDATE SET
                    strategy_fit_status = EXCLUDED.strategy_fit_status,
                    top_strategy = EXCLUDED.top_strategy,
                    top_strategy_score = EXCLUDED.top_strategy_score,
                    quote_status = EXCLUDED.quote_status,
                    readiness_status = EXCLUDED.readiness_status,
                    blockers = EXCLUDED.blockers,
                    next_required_action = EXCLUDED.next_required_action,
                    proposal_candidate_allowed = EXCLUDED.proposal_candidate_allowed,
                    executable_now = EXCLUDED.executable_now
            """, [
                c["snapshot_id"], c["run_date"], c["session"], c["symbol"],
                c["source_screeners"], c["catalog_status"], c["membership_status"],
                c["strategy_fit_status"], c["top_strategy"], c["top_strategy_score"],
                c["quote_status"], c["readiness_status"], c["blockers"],
                c["next_required_action"], c["proposal_candidate_allowed"],
                c["executable_now"], c["human_review_only"],
            ])

        # Underfilled reason
        underfilled_reason = None
        if stats["symbols_considered"] < 50:
            underfilled_reason = f"Only {stats['symbols_considered']} symbols in screener universe (< 50 threshold)"

        # Insert run summary
        run_id = snapshot_id
        cur.execute("""
            INSERT INTO afterhours_readiness_run
                (run_id, run_date, session, symbols_considered, strategy_fit_evaluated,
                 ready_for_review, proposal_candidate_pending, needs_data, blocked, no_fit,
                 run_status, underfilled_reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (run_id) DO UPDATE SET
                symbols_considered = EXCLUDED.symbols_considered,
                strategy_fit_evaluated = EXCLUDED.strategy_fit_evaluated,
                ready_for_review = EXCLUDED.ready_for_review,
                proposal_candidate_pending = EXCLUDED.proposal_candidate_pending,
                needs_data = EXCLUDED.needs_data,
                blocked = EXCLUDED.blocked,
                no_fit = EXCLUDED.no_fit,
                run_status = EXCLUDED.run_status,
                underfilled_reason = EXCLUDED.underfilled_reason
        """, [
            run_id, run_date, session,
            stats["symbols_considered"], stats["strategy_fit_evaluated"],
            stats["ready_for_review"],
            stats.get("proposal_candidate_pending_market_open_check", 0),
            stats["needs_data"],
            stats.get("blocked_by_liquidity", 0) + stats.get("blocked_by_strategy_fit", 0),
            stats["no_fit"],
            "completed", underfilled_reason,
        ])
        conn.commit()

    conn.close()

    # Report
    if args.verbose:
        print(f"\n{'='*60}")
        print(f"[{mode}] After-Hours Candidate Preparation Summary")
        print(f"  Symbols considered: {stats['symbols_considered']}")
        print(f"  Strategy fit evaluated: {stats['strategy_fit_evaluated']}")
        print(f"  Readiness breakdown:")
        for key in ("ready_for_review", "proposal_candidate_pending_market_open_check",
                     "watchpool_candidate", "needs_data", "blocked_by_liquidity",
                     "blocked_by_strategy_fit", "no_fit"):
            print(f"    {key}: {stats.get(key, 0)}")
        print(f"\n  Top 25 candidates:")
        for i, c in enumerate(candidates[:25]):
            print(f"    {i+1:2d}. {c['symbol']:6s} -- {c['top_strategy'] or 'none':30s} "
                  f"({c['top_strategy_score']:3d}) [{c['readiness_status']}]")
        if stats["symbols_considered"] < 50:
            print(f"\n  UNDERFILLED: only {stats['symbols_considered']} symbols (< 50)")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot_id,
        "mode": "dry_run" if dry_run else "apply",
        "session": session,
        "run_date": run_date,
        **stats,
        "top_25": [
            {"symbol": c["symbol"], "strategy": c["top_strategy"],
             "score": c["top_strategy_score"], "readiness": c["readiness_status"]}
            for c in candidates[:25]
        ],
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            f"# After-Hours Candidate Preparation {'DRY RUN' if dry_run else 'APPLIED'}\n",
            f"Snapshot: `{snapshot_id}`\n",
            "| Metric | Value |", "|--------|-------|",
            f"| Symbols considered | {stats['symbols_considered']} |",
            f"| Strategy fit evaluated | {stats['strategy_fit_evaluated']} |",
            f"| Ready for review | {stats['ready_for_review']} |",
            f"| Pending market open check | {stats.get('proposal_candidate_pending_market_open_check', 0)} |",
            f"| Watchpool candidate | {stats.get('watchpool_candidate', 0)} |",
            f"| Needs data | {stats['needs_data']} |",
            f"| Blocked (liquidity) | {stats.get('blocked_by_liquidity', 0)} |",
            f"| Blocked (strategy fit) | {stats.get('blocked_by_strategy_fit', 0)} |",
            f"| No fit | {stats['no_fit']} |",
            "",
            "## Top 25 Candidates",
            "| # | Symbol | Strategy | Score | Readiness |",
            "|---|--------|----------|-------|-----------|",
        ]
        for i, c in enumerate(candidates[:25]):
            md.append(f"| {i+1} | {c['symbol']} | {c['top_strategy'] or '-'} | {c['top_strategy_score']} | {c['readiness_status']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
