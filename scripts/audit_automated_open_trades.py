#!/usr/bin/env python3
"""Pre-ATM audit: open tradeai_automated positions — entry/stop/R/trail readiness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from automated_account import LEGACY_AUTOMATED_KEYS
from protection_trail_calculator import compute_trail_percent, r_multiple


def audit(*, fix_planned_stop: bool = False) -> dict:
    from db_adapter import _get_conn
    from market_quote_provider import get_best_quote

    conn = _get_conn()
    cur = conn.cursor()
    keys = tuple(sorted(LEGACY_AUTOMATED_KEYS))
    cur.execute(
        f"""SELECT id, symbol, strategy_id, entry_price, shares, planned_stop, stop_loss,
                   current_stop, stop_order_id, proposal_id, account
            FROM paper_trades
            WHERE status = 'open' AND account IN ({','.join(['%s'] * len(keys))})
            ORDER BY symbol""",
        keys,
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    broker = {}
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        a = AlpacaPaperAdapter()
        if a.enabled:
            broker = {p["symbol"]: p for p in (a.get_positions() or []) if p.get("symbol")}
    except Exception as e:
        broker = {"_error": str(e)}

    if fix_planned_stop:
        cur.execute(
            f"""UPDATE paper_trades SET planned_stop = stop_loss
                WHERE status = 'open' AND account IN ({','.join(['%s'] * len(keys))})
                  AND planned_stop IS NULL AND stop_loss IS NOT NULL
                RETURNING id, symbol""",
            keys,
        )
        fixed = [{"id": r[0], "symbol": r[1]} for r in cur.fetchall()]
        if fixed:
            conn.commit()
    else:
        fixed = []

    flagged = []
    for t in rows:
        sym = t["symbol"]
        entry = float(t["entry_price"] or 0)
        planned = t["planned_stop"]
        stop = t["current_stop"] or t["stop_loss"] or planned
        flags = []
        if entry <= 0:
            flags.append("entry_missing_or_zero")
        if not t["stop_order_id"]:
            flags.append("no_stop_order_id")
        if planned is None:
            flags.append("planned_stop_missing")
        if stop is not None and entry > 0 and float(stop) >= entry:
            flags.append("stop_at_or_above_entry")
        bp = broker.get(sym) if isinstance(broker, dict) else None
        if isinstance(broker, dict) and "_error" not in broker and sym not in broker:
            flags.append("not_in_broker_positions")
        if bp and entry > 0:
            be = float(bp.get("avg_entry_price") or bp.get("avg_entry") or 0)
            if be > 0 and abs(be - entry) / be > 0.02:
                flags.append("db_entry_vs_broker_drift")
        q = get_best_quote(sym) or {}
        px = float(q.get("last_price") or 0)
        r_mult = r_multiple(entry, planned, px, current_stop=stop)
        trail = compute_trail_percent(t["strategy_id"], sym, entry, planned, px, current_stop=stop)
        rec = {
            "trade_id": t["id"],
            "symbol": sym,
            "strategy_id": t["strategy_id"],
            "entry_price": entry,
            "planned_stop": float(planned) if planned is not None else None,
            "current_stop": float(stop) if stop is not None else None,
            "quote": px,
            "r_multiple": r_mult,
            "trail_eligible": trail.get("eligible"),
            "trail_percent": trail.get("trail_percent"),
            "flags": flags,
        }
        if flags:
            flagged.append(rec)

    ph = ",".join(["%s"] * len(keys))
    cur.execute(
        f"""SELECT count(*) FROM paper_protection_adjustment_proposals a
            JOIN paper_trades t ON t.id = a.trade_id
            WHERE a.status = 'PROPOSED' AND t.status = 'open' AND t.account IN ({ph})
              AND a.action = 'CONVERT_TO_TRAILING_STOP'""",
        keys,
    )
    trailing_n = int(cur.fetchone()[0])
    conn.close()

    return {
        "open_automated": len(rows),
        "flagged": flagged,
        "planned_stop_fixed": fixed,
        "trailing_proposals": trailing_n,
        "ready_for_atm": len(flagged) == 0 or all(
            set(f["flags"]) <= {"stop_at_or_above_entry", "planned_stop_missing"} for f in flagged
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-planned-stop", action="store_true")
    args = ap.parse_args()
    print(json.dumps(audit(fix_planned_stop=args.fix_planned_stop), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())