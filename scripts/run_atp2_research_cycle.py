#!/usr/bin/env python3
"""
run_atp2_research_cycle.py
ATP-2 Research Cycle Runner

Queries existing DB data for each ATP-2 cadence cycle and produces a
research readiness report. No external API calls, no trades, no orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn

TODAY = datetime.now().strftime("%Y-%m-%d")
NOW = datetime.now()


def _q(sql: str, params=None) -> list[dict]:
    """Execute a query and return list of dicts."""
    conn = _get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            return [dict(r) for r in rows]
    except Exception as e:
        conn.rollback()
        print(f"  [research-cycle] SQL error: {e}")
        return []


def cycle_eod(verbose: bool = False) -> dict:
    """EOD cycle: summarize today's paper trades and proposals."""
    open_trades = _q(
        "SELECT id, symbol, strategy_id, entry_price, status, created_at "
        "FROM paper_trades WHERE status = 'open' ORDER BY created_at DESC"
    )
    closed_today = _q(
        "SELECT id, symbol, strategy_id, pnl, pnl_pct, exit_reason, closed_at "
        "FROM paper_trades WHERE closed_at::date = %s ORDER BY closed_at DESC",
        (TODAY,)
    )
    pending_proposals = _q(
        "SELECT id, symbol, strategy_id, status, created_at, proposed_entry, proposed_stop "
        "FROM paper_trade_proposals WHERE status IN ('PENDING', 'pending') "
        "ORDER BY created_at DESC"
    )
    stale_proposals = [
        p for p in pending_proposals
        if p.get("created_at") and (NOW - p["created_at"].replace(tzinfo=None)).total_seconds() > 86400
    ]

    return {
        "cycle": "eod",
        "summary": "End-of-day paper trade and proposal summary",
        "open_trade_count": len(open_trades),
        "closed_today_count": len(closed_today),
        "pending_proposal_count": len(pending_proposals),
        "stale_proposal_count": len(stale_proposals),
        "total_pnl_today": round(sum(float(t.get("pnl") or 0) for t in closed_today), 2),
        "open_trades": [{"id": t["id"], "symbol": t["symbol"], "strategy": t["strategy_id"]} for t in open_trades[:20]],
        "closed_today": [
            {"id": t["id"], "symbol": t["symbol"], "pnl": float(t.get("pnl") or 0),
             "exit_reason": t.get("exit_reason")}
            for t in closed_today[:20]
        ],
        "stale_proposals": [{"id": p["id"], "symbol": p["symbol"],
                             "age_hours": round((NOW - p["created_at"].replace(tzinfo=None)).total_seconds() / 3600, 1)}
                            for p in stale_proposals[:20]],
    }


def cycle_evening(verbose: bool = False) -> dict:
    """Evening cycle: afterhours candidate readiness."""
    candidates = _q(
        "SELECT symbol, readiness_status, top_strategy, top_strategy_score, "
        "catalog_status, quote_status, session "
        "FROM afterhours_candidate_snapshot "
        "WHERE run_date = (SELECT MAX(run_date) FROM afterhours_candidate_snapshot) "
        "ORDER BY top_strategy_score DESC NULLS LAST"
    )
    by_status: dict[str, int] = {}
    for c in candidates:
        st = c.get("readiness_status") or "unknown"
        by_status[st] = by_status.get(st, 0) + 1

    return {
        "cycle": "evening",
        "summary": "Afterhours candidate readiness snapshot",
        "total_candidates": len(candidates),
        "by_readiness_status": by_status,
        "top_candidates": [
            {"symbol": c["symbol"], "readiness": c.get("readiness_status"),
             "strategy": c.get("top_strategy"), "score": c.get("top_strategy_score")}
            for c in candidates[:20]
        ],
    }


def cycle_overnight(verbose: bool = False) -> dict:
    """Overnight cycle: identify data gaps and lesson patterns."""
    cutoff = (NOW - timedelta(hours=24)).isoformat()
    # Symbols with no recent scan
    all_symbols = _q(
        "SELECT DISTINCT symbol FROM trade_ai_scans "
        "WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')"
    )
    recent_symbols = _q(
        "SELECT DISTINCT symbol FROM trade_ai_scans WHERE scanned_at >= %s",
        (cutoff,)
    )
    recent_set = {r["symbol"] for r in recent_symbols}
    stale_symbols = [s["symbol"] for s in all_symbols if s["symbol"] not in recent_set]

    # Lesson patterns
    lessons = _q(
        "SELECT lesson_category, repeated_pattern_key, pattern_count, "
        "strategy_id, symbol, improved_lesson "
        "FROM trade_lesson_memory "
        "ORDER BY pattern_count DESC LIMIT 30"
    )

    return {
        "cycle": "overnight",
        "summary": "Data freshness gaps and lesson memory patterns",
        "total_tracked_symbols": len(all_symbols),
        "symbols_with_fresh_data": len(recent_symbols),
        "symbols_stale_gt_24h": len(stale_symbols),
        "stale_symbol_list": sorted(stale_symbols)[:50],
        "lesson_patterns": [
            {"category": l.get("lesson_category"), "pattern_key": l.get("repeated_pattern_key"),
             "count": l.get("pattern_count"), "strategy": l.get("strategy_id"),
             "lesson": (l.get("improved_lesson") or "")[:120]}
            for l in lessons[:15]
        ],
    }


def cycle_premarket_4am(verbose: bool = False) -> dict:
    """Premarket 4am: scan data for gap/rvol movers."""
    scans = _q(
        "SELECT symbol, score, grade, decision, rvol, price, change_pct, gap_pct, "
        "catalyst, scanned_at "
        "FROM trade_ai_scans "
        "WHERE run_date = (SELECT MAX(run_date) FROM trade_ai_scans) "
        "ORDER BY score DESC LIMIT 100"
    )
    high_gap = [s for s in scans if s.get("gap_pct") and abs(float(s["gap_pct"])) > 3]
    high_rvol = [s for s in scans if s.get("rvol") and float(s["rvol"]) > 2.0]

    return {
        "cycle": "premarket_4am",
        "summary": "Pre-market scan data: gap and rvol movers",
        "total_scanned": len(scans),
        "high_gap_count": len(high_gap),
        "high_rvol_count": len(high_rvol),
        "top_movers_by_gap": [
            {"symbol": s["symbol"], "gap_pct": float(s.get("gap_pct") or 0),
             "rvol": float(s.get("rvol") or 0), "score": s.get("score"),
             "catalyst": (s.get("catalyst") or "")[:80]}
            for s in sorted(high_gap, key=lambda x: abs(float(x.get("gap_pct") or 0)), reverse=True)[:15]
        ],
        "top_movers_by_rvol": [
            {"symbol": s["symbol"], "rvol": float(s.get("rvol") or 0),
             "change_pct": float(s.get("change_pct") or 0), "score": s.get("score")}
            for s in sorted(high_rvol, key=lambda x: float(x.get("rvol") or 0), reverse=True)[:15]
        ],
    }


def cycle_premarket_7am(verbose: bool = False) -> dict:
    """Premarket 7am: strategy fit audit matches + afterhours readiness."""
    fits = _q(
        "SELECT u.symbol, u.strategy_id, u.match_strength, u.normalized_score, "
        "u.recommendation, u.top_match_for_symbol "
        "FROM universe_strategy_fit_audit u "
        "WHERE u.audit_run_id = (SELECT MAX(audit_run_id) FROM universe_strategy_fit_audit) "
        "AND u.match_strength IN ('STRONG', 'MODERATE') "
        "AND u.top_match_for_symbol = true "
        "ORDER BY u.normalized_score DESC LIMIT 50"
    )
    # Cross-reference with afterhours readiness
    fit_symbols = [f["symbol"] for f in fits]
    readiness = {}
    if fit_symbols:
        placeholders = ",".join(["%s"] * len(fit_symbols))
        rows = _q(
            f"SELECT symbol, readiness_status, top_strategy_score "
            f"FROM afterhours_candidate_snapshot "
            f"WHERE run_date = (SELECT MAX(run_date) FROM afterhours_candidate_snapshot) "
            f"AND symbol IN ({placeholders})",
            tuple(fit_symbols)
        )
        readiness = {r["symbol"]: r for r in rows}

    priorities = []
    for f in fits:
        sym = f["symbol"]
        r = readiness.get(sym, {})
        priorities.append({
            "symbol": sym,
            "strategy": f["strategy_id"],
            "match_strength": f["match_strength"],
            "fit_score": f.get("normalized_score"),
            "readiness": r.get("readiness_status", "no_snapshot"),
            "ah_score": r.get("top_strategy_score"),
        })

    return {
        "cycle": "premarket_7am",
        "summary": "Due diligence priorities from strategy fit + afterhours readiness",
        "strong_moderate_fits": len(fits),
        "with_readiness_snapshot": len(readiness),
        "priorities": priorities[:30],
    }


def cycle_premarket_9am(verbose: bool = False) -> dict:
    """Premarket 9am: final ranking of ready candidates."""
    candidates = _q(
        "SELECT symbol, readiness_status, top_strategy, top_strategy_score, "
        "quote_status, proposal_candidate_allowed "
        "FROM afterhours_candidate_snapshot "
        "WHERE run_date = (SELECT MAX(run_date) FROM afterhours_candidate_snapshot) "
        "AND readiness_status IN ('ready_for_review', 'proposal_candidate_pending_market_open_check') "
        "ORDER BY top_strategy_score DESC NULLS LAST"
    )

    return {
        "cycle": "premarket_9am",
        "summary": "Final pre-market ranking of ready candidates",
        "ready_count": len(candidates),
        "ranked_candidates": [
            {"symbol": c["symbol"], "strategy": c.get("top_strategy"),
             "score": c.get("top_strategy_score"), "readiness": c.get("readiness_status"),
             "quote_ok": c.get("quote_status"), "proposal_allowed": c.get("proposal_candidate_allowed")}
            for c in candidates[:30]
        ],
    }


def cycle_proposal_revalidation(verbose: bool = False) -> dict:
    """Proposal revalidation: check freshness and validity of pending proposals."""
    proposals = _q(
        "SELECT p.id, p.symbol, p.strategy_id, p.status, p.proposed_entry, "
        "p.proposed_stop, p.created_at, p.expires_at "
        "FROM paper_trade_proposals p "
        "WHERE p.status IN ('PENDING', 'pending') "
        "ORDER BY p.created_at DESC"
    )

    results = []
    for p in proposals:
        sym = p["symbol"]
        created = p.get("created_at")
        age_hours = None
        if created:
            age_hours = round((NOW - created.replace(tzinfo=None)).total_seconds() / 3600, 1)

        # Check quote freshness
        scan = _q(
            "SELECT scanned_at, price, rvol FROM trade_ai_scans "
            "WHERE symbol = %s ORDER BY scanned_at DESC LIMIT 1",
            (sym,)
        )
        quote_age_hours = None
        quote_fresh = False
        if scan:
            scanned_at = scan[0].get("scanned_at")
            if scanned_at:
                quote_age_hours = round((NOW - scanned_at.replace(tzinfo=None)).total_seconds() / 3600, 1)
                quote_fresh = quote_age_hours < 1

        # Classify
        if age_hours is not None and age_hours > 48:
            reval_status = "expired"
        elif age_hours is not None and age_hours > 24:
            reval_status = "stale"
        elif not quote_fresh:
            reval_status = "needs_refresh"
        else:
            reval_status = "still_valid"

        results.append({
            "proposal_id": p["id"],
            "symbol": sym,
            "strategy": p.get("strategy_id"),
            "status": p.get("status"),
            "age_hours": age_hours,
            "quote_age_hours": quote_age_hours,
            "quote_fresh": quote_fresh,
            "revalidation_status": reval_status,
        })

    by_status: dict[str, int] = {}
    for r in results:
        st = r["revalidation_status"]
        by_status[st] = by_status.get(st, 0) + 1

    return {
        "cycle": "proposal_revalidation",
        "summary": "Pending proposal freshness and validity check",
        "total_pending": len(proposals),
        "by_revalidation_status": by_status,
        "proposals": results[:50],
    }


CYCLE_HANDLERS = {
    "eod": cycle_eod,
    "evening": cycle_evening,
    "overnight": cycle_overnight,
    "premarket_4am": cycle_premarket_4am,
    "premarket_7am": cycle_premarket_7am,
    "premarket_9am": cycle_premarket_9am,
    "proposal_revalidation": cycle_proposal_revalidation,
}


def log_cycle_run(cycle: str, result: dict, dry_run: bool) -> None:
    """Attempt to log run to research_cycle_runs if it exists."""
    if dry_run:
        return
    conn = _get_conn()
    if not conn:
        return
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'research_cycle_runs' LIMIT 1"
            )
            if not cur.fetchone():
                conn.commit()
                return
            cur.execute(
                "INSERT INTO research_cycle_runs (cycle, run_date, result, created_at) "
                "VALUES (%s, %s, %s, now())",
                (cycle, TODAY, json.dumps(result, default=str))
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [research-cycle] Could not log run: {e}")


def render_markdown(results: list[dict]) -> str:
    """Render cycle results as markdown."""
    lines = [
        "# ATP-2 Research Cycle Report",
        f"Generated: {NOW.isoformat()}",
        "",
    ]
    for r in results:
        cycle = r.get("cycle", "unknown")
        lines.append(f"## {cycle}")
        lines.append(f"_{r.get('summary', '')}_")
        lines.append("")
        for k, v in r.items():
            if k in ("cycle", "summary"):
                continue
            if isinstance(v, list):
                lines.append(f"**{k}:** {len(v)} items")
                for item in v[:10]:
                    if isinstance(item, dict):
                        parts = [f"{ik}={iv}" for ik, iv in item.items()]
                        lines.append(f"  - {', '.join(parts)}")
                    else:
                        lines.append(f"  - {item}")
                if len(v) > 10:
                    lines.append(f"  - ... and {len(v) - 10} more")
            elif isinstance(v, dict):
                lines.append(f"**{k}:**")
                for dk, dv in v.items():
                    lines.append(f"  - {dk}: {dv}")
            else:
                lines.append(f"**{k}:** {v}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ATP-2 Research Cycle Runner")
    parser.add_argument("--cycle", required=True,
                        choices=list(CYCLE_HANDLERS.keys()) + ["all_dry_run"],
                        help="Which cycle to run")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dry run (default)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply mode: log cycle run to DB if table exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit results (currently advisory)")
    parser.add_argument("--output-json", type=str, help="Write JSON report to file")
    parser.add_argument("--output-md", type=str, help="Write Markdown report to file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply

    if args.cycle == "all_dry_run":
        cycles_to_run = list(CYCLE_HANDLERS.keys())
        dry_run = True
    else:
        cycles_to_run = [args.cycle]

    all_results = []
    for cyc in cycles_to_run:
        print(f"[research-cycle] Running {cyc} ...")
        handler = CYCLE_HANDLERS[cyc]
        result = handler(verbose=args.verbose)
        result["run_mode"] = "dry_run" if dry_run else "apply"
        result["run_at"] = NOW.isoformat()
        all_results.append(result)

        log_cycle_run(cyc, result, dry_run)

        # Console summary
        for k, v in result.items():
            if k in ("cycle", "summary", "run_mode", "run_at"):
                continue
            if isinstance(v, (int, float, str, bool)):
                print(f"  {k}: {v}")
            elif isinstance(v, dict):
                print(f"  {k}: {json.dumps(v)}")
            elif isinstance(v, list):
                print(f"  {k}: {len(v)} items")

    output = {
        "report": "ATP-2 Research Cycle",
        "generated_at": NOW.isoformat(),
        "mode": "dry_run" if dry_run else "apply",
        "cycles_run": cycles_to_run,
        "results": all_results,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(output, indent=2, default=str))
        print(f"[research-cycle] JSON written to {args.output_json}")

    if args.output_md:
        md = render_markdown(all_results)
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        print(f"[research-cycle] Markdown written to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
