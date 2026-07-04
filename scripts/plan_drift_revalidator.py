#!/usr/bin/env python3
"""plan_drift_revalidator.py — re-plan watchlist entries whose plan no longer fits the tape.

Why: entry plans are validated once and never re-checked. SSTK (audit 2026-07-03) carried a
"validated" plan with limit $13.50 / target $13.20 while the stock traded at $9.80 — the stored
R:R was garbage and the card's levels were decision-hazards. Two defect classes:

  incoherent — target <= limit (levels crossed; usually a partial/stale planner write)
  drifted    — |price − limit| / limit > PLAN_DRIFT_REPLAN_PCT (price left the planned zone)

For each defective plan on a visible symbol (active/researched, Hermes top-N), this queues a
rebuild through the existing planner (`watchlist_entry_planner.run(symbols=[...])`) — same
lanes, same validation, nothing new invented. Guards: plans younger than MIN_PLAN_AGE_H are
left alone (fresh planner output gets a session to settle), batch capped per run.

  python3 scripts/plan_drift_revalidator.py            # dry-run report
  python3 scripts/plan_drift_revalidator.py --apply    # re-plan defective symbols

Cron: daily pre-planner (17:25 ET) so drifted names re-plan in the same evening cycle.
Advisory-only — plans feed the card/proposal layer; nothing here touches orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DRIFT_PCT = float(os.environ.get("PLAN_DRIFT_REPLAN_PCT", "15"))
MIN_PLAN_AGE_H = float(os.environ.get("PLAN_DRIFT_MIN_AGE_H", "20"))


def find_defective(top: int, cap: int) -> list[dict]:
    from db_adapter import _execute
    rows = _execute("""
        WITH latest_plan AS (
            SELECT DISTINCT ON (symbol) symbol, limit_price, target_price, created_at
            FROM watchlist_entry_plans
            ORDER BY symbol, created_at DESC
        ), item AS (
            SELECT DISTINCT ON (symbol) symbol, price, hermes_rank
            FROM watchlist_items
            WHERE status IN ('active','researched') AND hermes_rank IS NOT NULL AND hermes_rank <= %s
            ORDER BY symbol, first_seen_at ASC
        )
        SELECT i.symbol, i.price, i.hermes_rank, p.limit_price, p.target_price, p.created_at,
               (p.target_price IS NOT NULL AND p.limit_price IS NOT NULL
                AND p.target_price <= p.limit_price)                             AS incoherent,
               (i.price IS NOT NULL AND p.limit_price IS NOT NULL AND p.limit_price > 0
                AND abs(i.price - p.limit_price) / p.limit_price * 100 > %s)     AS drifted
        FROM item i
        JOIN latest_plan p ON p.symbol = i.symbol
        WHERE p.created_at < NOW() - (%s || ' hours')::interval
          AND ((p.target_price IS NOT NULL AND p.limit_price IS NOT NULL AND p.target_price <= p.limit_price)
               OR (i.price IS NOT NULL AND p.limit_price IS NOT NULL AND p.limit_price > 0
                   AND abs(i.price - p.limit_price) / p.limit_price * 100 > %s))
        ORDER BY i.hermes_rank
        LIMIT %s""", (top, DRIFT_PCT, str(MIN_PLAN_AGE_H), DRIFT_PCT, cap), fetch="all") or []
    out = []
    for r in rows:
        d = r if isinstance(r, dict) else dict(zip(
            ("symbol", "price", "hermes_rank", "limit_price", "target_price", "created_at", "incoherent", "drifted"), r))
        drift = (abs(float(d["price"]) - float(d["limit_price"])) / float(d["limit_price"]) * 100
                 if d.get("price") and d.get("limit_price") else None)
        out.append({
            "symbol": d["symbol"], "rank": d["hermes_rank"],
            "price": float(d["price"]) if d.get("price") else None,
            "limit": float(d["limit_price"]) if d.get("limit_price") else None,
            "target": float(d["target_price"]) if d.get("target_price") else None,
            "kind": "incoherent" if d.get("incoherent") else "drifted",
            "drift_pct": round(drift, 1) if drift is not None else None,
            "plan_age": str(d.get("created_at"))[:16],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="re-plan defective symbols (default: dry-run report)")
    ap.add_argument("--top", type=int, default=250, help="Hermes-rank scope (default 250)")
    ap.add_argument("--cap", type=int, default=25, help="max symbols re-planned per run (default 25)")
    a = ap.parse_args()

    bad = find_defective(a.top, a.cap)
    print(f"{len(bad)} defective plan(s) (drift > {DRIFT_PCT}% or target <= limit, plan age > {MIN_PLAN_AGE_H}h, "
          f"Hermes top-{a.top}, cap {a.cap})")
    for b in bad:
        print(f"  {b['symbol']:6s} #{b['rank']:<4} {b['kind']:10s} price {b['price']} vs limit {b['limit']} "
              f"(drift {b['drift_pct']}%) target {b['target']} · plan {b['plan_age']}")
    if not bad:
        return 0
    if not a.apply:
        print("dry run — re-run with --apply to rebuild these plans via watchlist_entry_planner")
        return 0

    # Run the planner in SUBPROCESS batches of 5 — one long in-process run dies when the DB
    # connection idles out during LLM calls ("SSL connection has been closed unexpectedly",
    # first --apply 2026-07-03). Fresh process per batch = fresh connection + crash isolation.
    import subprocess
    syms = [b["symbol"] for b in bad]
    py = str(Path(sys.executable))
    planner = str(Path(__file__).resolve().parent / "watchlist_entry_planner.py")
    results = []
    for i in range(0, len(syms), 5):
        batch = syms[i:i + 5]
        try:
            r = subprocess.run([py, planner, "--symbols", ",".join(batch), "--limit", str(len(batch))],
                               capture_output=True, text=True, timeout=900)
            ok = r.returncode == 0
            results.append({"batch": batch, "ok": ok, "tail": (r.stdout or r.stderr)[-160:].strip()})
            print(f"  batch {batch}: {'ok' if ok else f'rc={r.returncode}'}")
        except subprocess.TimeoutExpired:
            results.append({"batch": batch, "ok": False, "tail": "timeout 900s"})
            print(f"  batch {batch}: TIMEOUT")
    print(json.dumps({"replanned_batches": results}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
