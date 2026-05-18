#!/usr/bin/env python3
"""report_proposal_strategy_fit_audit.py — Strategy fit audit for pending proposals.

Read-only. No mutations. No strategy activation.

Usage:
    .venv/bin/python scripts/report_proposal_strategy_fit_audit.py --verbose
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
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
            return None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def audit_proposal_strategy_fit(proposal_id=None, symbol=None):
    """Audit strategy fit for pending proposals. Read-only."""
    where = "WHERE ptp.status = 'PENDING'"
    params = []
    if proposal_id:
        where += " AND ptp.id = %s"
        params.append(proposal_id)
    if symbol:
        where += " AND ptp.symbol = %s"
        params.append(symbol)

    proposals = _db_query(f"""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id,
               ptp.primary_strategy_id, ptp.secondary_strategy_ids,
               ptp.setup_stack, ptp.strategy_config_hash
        FROM paper_trade_proposals ptp
        {where}
        ORDER BY ptp.created_at DESC LIMIT 50
    """, params) or []

    results = []
    for p in proposals:
        pid = p["id"]
        sym = p["symbol"]
        sid = p["strategy_id"]

        # Load strategy YAML metadata
        yaml_desc = None
        yaml_hash = None
        yaml_timeframe = None
        try:
            from strategy_config_loader import load_strategy_config
            cfg = load_strategy_config(sid)
            yaml_desc = cfg.get("purpose")
            yaml_hash = cfg.get("_config_hash")
            yaml_timeframe = cfg.get("timeframe_class")
        except Exception:
            pass

        # Check setup_stack from proposal
        setup_stack = p.get("setup_stack")
        if isinstance(setup_stack, str):
            try:
                setup_stack = json.loads(setup_stack)
            except Exception:
                setup_stack = None

        # Query strategy_setup_matches for this proposal
        matches = _db_query("""
            SELECT strategy_id, match_score, match_status,
                   criteria_met, criteria_failed, disqualifiers_hit,
                   missing_data, is_primary, priority_rank, reason, config_hash
            FROM strategy_setup_matches
            WHERE proposal_id = %s
            ORDER BY match_score DESC
        """, [pid]) or []

        # If no matches found, try by symbol (matches may be stored per-run, not per-proposal)
        if not matches:
            matches = _db_query("""
                SELECT strategy_id, match_score, match_status,
                       criteria_met, criteria_failed, disqualifiers_hit,
                       missing_data, is_primary, priority_rank, reason, config_hash
                FROM strategy_setup_matches
                WHERE symbol = %s
                ORDER BY created_at DESC, match_score DESC
                LIMIT 30
            """, [sym]) or []

        # Parse JSON fields
        for m in matches:
            for field in ("criteria_met", "criteria_failed", "disqualifiers_hit", "missing_data"):
                v = m.get(field)
                if isinstance(v, str):
                    try:
                        m[field] = json.loads(v)
                    except Exception:
                        pass

        # Find selected strategy match
        selected_match = None
        for m in matches:
            if m["strategy_id"] == sid:
                selected_match = m
                break

        # Alternatives
        alternatives = [m for m in matches if m["strategy_id"] != sid and m.get("match_status") != "NO_MATCH"]
        top_alternative = alternatives[0]["strategy_id"] if alternatives else None

        # Strategy fit status
        if selected_match:
            score = selected_match.get("match_score", 0)
            if score >= 60:
                fit_status = "PASS"
            elif score >= 40:
                fit_status = "PARTIAL"
            else:
                fit_status = "FAIL"
        elif not matches:
            fit_status = "MISSING"
        else:
            fit_status = "MISSING"

        # Mismatch warning
        mismatch_warning = None
        if matches and selected_match:
            best = matches[0]
            if best["strategy_id"] != sid and best.get("match_score", 0) > selected_match.get("match_score", 0) + 10:
                mismatch_warning = f"Best match is {best['strategy_id']} (score {best['match_score']}) but assigned {sid} (score {selected_match.get('match_score', '?')})"

        # DB/YAML hash sync
        stored_hash = p.get("strategy_config_hash")
        db_sync = "synced" if stored_hash and yaml_hash and stored_hash == yaml_hash else "unknown" if not stored_hash or not yaml_hash else "out_of_sync"

        results.append({
            "proposal_id": pid,
            "symbol": sym,
            "assigned_strategy_id": sid,
            "primary_strategy_id": p.get("primary_strategy_id"),
            "secondary_strategy_ids": p.get("secondary_strategy_ids"),
            "setup_stack_available": setup_stack is not None and len(setup_stack or []) > 0,
            "strategy_description": yaml_desc,
            "strategy_timeframe_class": yaml_timeframe,
            "yaml_config_hash": yaml_hash,
            "db_config_hash": stored_hash,
            "db_yaml_sync_status": db_sync,
            "fit_status": fit_status,
            "selected_match": {
                "match_score": selected_match.get("match_score") if selected_match else None,
                "match_status": selected_match.get("match_status") if selected_match else None,
                "criteria_met": selected_match.get("criteria_met") if selected_match else [],
                "criteria_failed": selected_match.get("criteria_failed") if selected_match else [],
                "disqualifiers_hit": selected_match.get("disqualifiers_hit") if selected_match else [],
                "reason": selected_match.get("reason") if selected_match else None,
            } if selected_match else None,
            "all_strategy_count": len(matches),
            "evaluated_count": len([m for m in matches if m.get("match_status") != "NO_MATCH"]),
            "passed_count": len([m for m in matches if m.get("match_score", 0) >= 40]),
            "top_alternative": top_alternative,
            "mismatch_warning": mismatch_warning,
            "missing_route_audit": len(matches) == 0,
            "strategy_evaluations": [
                {
                    "strategy_id": m["strategy_id"],
                    "match_score": m.get("match_score"),
                    "match_status": m.get("match_status"),
                    "criteria_met": m.get("criteria_met", []),
                    "criteria_failed": m.get("criteria_failed", []),
                    "disqualifiers_hit": m.get("disqualifiers_hit", []),
                    "is_primary": m.get("is_primary"),
                }
                for m in matches[:10]
            ],
        })

    return results


def main():
    p = argparse.ArgumentParser(description="Proposal strategy fit audit (read-only)")
    p.add_argument("--symbol", type=str)
    p.add_argument("--proposal-id", type=int)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    results = audit_proposal_strategy_fit(args.proposal_id, args.symbol)

    if args.verbose:
        print(f"Strategy Fit Audit — {len(results)} proposals")
        for r in results:
            print(f"\n  {r['symbol']} [{r['assigned_strategy_id']}] — {r['fit_status']}")
            if r.get("selected_match"):
                sm = r["selected_match"]
                print(f"    Score: {sm['match_score']}, Status: {sm['match_status']}")
                if sm.get("criteria_met"):
                    print(f"    Met: {sm['criteria_met']}")
                if sm.get("criteria_failed"):
                    print(f"    Failed: {sm['criteria_failed']}")
            if r.get("mismatch_warning"):
                print(f"    WARNING: {r['mismatch_warning']}")
            if r["missing_route_audit"]:
                print(f"    WARNING: No route audit data found")
            print(f"    Evaluated: {r['evaluated_count']}/{r['all_strategy_count']}, Alternatives: {r['top_alternative'] or 'none'}")
            print(f"    YAML/DB sync: {r['db_yaml_sync_status']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(results, indent=2, default=str))
    if args.output_md:
        md = ["# Strategy Fit Audit", ""]
        for r in results:
            md.append(f"## {r['symbol']} — {r['assigned_strategy_id']} — {r['fit_status']}")
            if r.get("selected_match"):
                sm = r["selected_match"]
                md.append(f"- Score: {sm['match_score']}")
                md.append(f"- Met: {', '.join(sm.get('criteria_met') or ['none'])}")
                md.append(f"- Failed: {', '.join(sm.get('criteria_failed') or ['none'])}")
            if r.get("mismatch_warning"):
                md.append(f"- **WARNING:** {r['mismatch_warning']}")
            if r["missing_route_audit"]:
                md.append(f"- **WARNING:** No route audit data")
            md.append(f"- Evaluated: {r['evaluated_count']}, Alternatives: {r['top_alternative'] or 'none'}")
            md.append("")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
