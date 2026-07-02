#!/usr/bin/env python3
"""hermes_scalp_shadow_feeder.py — Feed scalp trade outcomes into candidate_shadow_scores."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def run(apply: bool = False, days: int = 30) -> dict:
    from db_adapter import _get_conn
    from persist_shadow_scores import persist, DDL

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute(
        f"""SELECT pt.symbol, pt.strategy_id, pt.pnl, pt.entry_price, pt.shares,
                   h.composite_score, pt.closed_at
            FROM paper_trades pt
            LEFT JOIN LATERAL (
              SELECT composite_score FROM hermes_score_history h
              WHERE h.symbol = pt.symbol AND h.scored_at <= COALESCE(pt.entry_time, pt.created_at)
              ORDER BY h.scored_at DESC LIMIT 1
            ) h ON true
            WHERE lower(pt.status) = 'closed' AND pt.closed_at > NOW() - INTERVAL '{int(days)} days'
              AND (pt.strategy_id ILIKE '%%scalp%%' OR pt.strategy_id ILIKE '%%momentum%%')
            ORDER BY pt.closed_at DESC LIMIT 200"""
    )
    rows = cur.fetchall()
    written = 0
    ts = datetime.now(timezone.utc).isoformat()
    for sym, strat, pnl, entry, shares, comp, close_t in rows:
        if not sym or entry is None or not shares:
            continue
        ret = float(pnl or 0) / max(float(entry) * float(shares), 1e-9)
        orig = float(comp) if comp is not None else 50.0
        shadow = orig + (10.0 if ret > 0 else -10.0)
        output = {
            "timestamp": (close_t or datetime.now(timezone.utc)).isoformat(),
            "results": [{
                "symbol": sym,
                "strategy": strat or "momentum_scalp",
                "original_score": orig,
                "shadow_score": shadow,
                "delta": shadow - orig,
                "decision": "GO" if ret > 0 else "AVOID",
                "adjustment_count": 1,
                "learning_adjustments": {"scalp_return": ret, "source": "hermes_scalp_shadow_feeder"},
            }],
        }
        if apply:
            written += persist(output, conn=conn)
    if apply:
        conn.commit()
    out = {"ok": True, "apply": apply, "candidates": len(rows), "written": written, "ts": ts}
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    run(apply=args.apply, days=args.days)


if __name__ == "__main__":
    main()