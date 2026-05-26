#!/usr/bin/env python3
"""report_strategy_watch_horizon.py — Candidate/proposal watch maturity report.

Read-only. No mutations.

Usage:
    .venv/bin/python scripts/report_strategy_watch_horizon.py --verbose --since-days 30
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from strategy_watch_horizon_policy import classify_candidate_watch_state, get_default_watch_horizon


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


def _json_clean(v):
    if v is None: return None
    if isinstance(v, (int, float, str, bool)): return v
    try: return str(v)
    except: return None


def main():
    p = argparse.ArgumentParser(description="Strategy watch horizon report (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Get incubator + proposal candidates
    rows = _db_query("""
        SELECT iu.symbol, iu.strategy_id, iu.latest_score, iu.status,
               iu.first_seen_at, iu.last_seen_at, iu.promoted_to_proposal_at,
               iu.sector, iu.industry, iu.source_first_seen as scan_source,
               iu.catalyst_verified, iu.rvol_latest as rvol, iu.days_active
        FROM incubator_universe iu
        WHERE iu.last_seen_at > %s OR iu.first_seen_at > %s
        ORDER BY iu.strategy_id, iu.latest_score DESC
    """, [since, since]) or []

    # Also get pending proposals
    proposals = _db_query("""
        SELECT symbol, strategy_id, status, created_at,
               catalyst_verified, risk_gate_result
        FROM paper_trade_proposals
        WHERE created_at > %s
        ORDER BY strategy_id, created_at DESC
    """, [since]) or []

    proposal_syms = {r["symbol"] for r in proposals}

    candidates = []
    for r in rows:
        age_days = int(r.get("days_active") or 0)
        if not age_days and r.get("first_seen_at"):
            try:
                fs = r["first_seen_at"]
                if isinstance(fs, str):
                    from datetime import datetime as _dt
                    fs = _dt.fromisoformat(fs.replace("Z", "+00:00"))
                if fs.tzinfo is None:
                    fs = fs.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - fs).days
            except Exception:
                pass

        candidate = {
            "symbol": r["symbol"],
            "strategy_id": r.get("strategy_id") or "",
            "sector": r.get("sector"),
            "industry": r.get("industry"),
            "scan_source": r.get("scan_source"),
            "age_days": age_days,
            "score": r.get("latest_score"),
            "status": r.get("status"),
            "catalyst_verified": r.get("catalyst_verified"),
            "has_proposal": r["symbol"] in proposal_syms,
            "promoted": r.get("promoted_to_proposal_at") is not None,
        }
        ws = classify_candidate_watch_state(candidate, candidate["strategy_id"])
        candidate.update(ws)
        candidates.append(candidate)

    # Aggregate by strategy
    by_strategy = {}
    for c in candidates:
        sid = c["strategy_id"] or "unknown"
        by_strategy.setdefault(sid, {"candidate_count": 0, "states": {}})
        by_strategy[sid]["candidate_count"] += 1
        st = c.get("watch_state", "unknown")
        by_strategy[sid]["states"][st] = by_strategy[sid]["states"].get(st, 0) + 1

    for sid, data in by_strategy.items():
        h = get_default_watch_horizon(sid)
        data["min_watch_days"] = h["min_days"]
        data["max_watch_days"] = h["max_days"]
        data["refresh_freq"] = h["refresh_freq"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": args.since_days,
        "total_candidates": len(candidates),
        "total_proposals": len(proposals),
        "by_strategy": by_strategy,
        "candidates": candidates[:100],  # cap output
    }

    if args.verbose:
        print(f"Watch Horizon Report — {len(candidates)} candidates, {len(proposals)} proposals (last {args.since_days}d)")
        for sid, data in sorted(by_strategy.items()):
            print(f"\n  {sid} ({data['candidate_count']} candidates, {data['min_watch_days']}-{data['max_watch_days']}d horizon)")
            for state, count in sorted(data["states"].items()):
                print(f"    {state}: {count}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Strategy Watch Horizon Report", f"\nPeriod: last {args.since_days} days | {len(candidates)} candidates | {len(proposals)} proposals\n"]
        md.append("| Strategy | Candidates | Horizon | Observing | Maturing | Ready | Expired | Disqualified |")
        md.append("|----------|-----------|---------|-----------|----------|-------|---------|-------------|")
        for sid, data in sorted(by_strategy.items()):
            s = data["states"]
            md.append(f"| {sid} | {data['candidate_count']} | {data['min_watch_days']}-{data['max_watch_days']}d | {s.get('observing',0)+s.get('new_candidate',0)} | {s.get('maturing',0)} | {s.get('ready_for_proposal',0)+s.get('ready_for_review',0)} | {s.get('expired',0)} | {s.get('disqualified',0)} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
