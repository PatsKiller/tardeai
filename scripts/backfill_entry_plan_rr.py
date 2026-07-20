#!/usr/bin/env python3
"""backfill_entry_plan_rr.py — recompute stored risk_reward from stored levels.

WHY
---
Until 2026-07-20 the planner stored whatever risk_reward the model emitted. The
prompt asked for (target-limit)/(limit-stop); nothing verified the answer. BETA
was planned twice with different levels and the model returned 1.5 both times —
true values 2.8 and 1.9. It was not calculating.

Measured across watchlist_entry_plans: 2,972 of 5,209 rows with usable levels
(57%) store an R:R not derivable from their own levels. 770 of those are
OVERSTATED — the trade reads better than its own numbers support — and that is
the direction that matters, because an operator scanning for R:R >= 2 was being
shown trades that do not clear the bar.

WHAT THIS DOES
--------------
Recomputes risk_reward from limit/stop/target, which are the model's own chosen
levels and are NOT altered. Only the derived figure changes.

Rows where limit <= stop cannot produce a meaningful R:R (non-positive or
inverted risk). Those get NULL rather than a number nobody can reproduce — the
same rule the live planner now applies.

The original value is preserved on the plan JSON as risk_reward_model_claimed,
so this is auditable and the scale of the drift stays visible after the fact.

SAFETY
------
- --dry-run is the DEFAULT. --apply is required to write.
- Idempotent: rows already carrying risk_reward_source='backfilled_from_levels'
  are skipped, so a re-run cannot double-stamp or overwrite the audit trail.
- Single transaction, committed once, so a failure part-way leaves nothing half
  written.
- Advisory data only. Touches no proposal, no order, no execution state.

USAGE
    .venv/bin/python scripts/backfill_entry_plan_rr.py            # dry run
    .venv/bin/python scripts/backfill_entry_plan_rr.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SOURCE_TAG = "backfilled_from_levels"


def _compute(limit, stop, target):
    """(value, reason). None value means the levels cannot produce an R:R."""
    if limit is None or stop is None or target is None:
        return None, "missing_levels"
    limit, stop, target = float(limit), float(stop), float(target)
    risk = limit - stop
    if risk <= 0:
        return None, "inverted_or_zero_risk"
    return round((target - limit) / risk, 1), "recomputed"


def run(apply: bool = False) -> dict:
    from db_adapter import _get_conn

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT id, symbol, limit_price, stop_price, target_price,
                          risk_reward, plan
                   FROM watchlist_entry_plans
                   ORDER BY id""")
    rows = cur.fetchall()

    stats = {"scanned": 0, "already_backfilled": 0, "unchanged": 0,
             "corrected": 0, "nulled": 0, "overstated": 0, "understated": 0,
             "max_error": 0.0}
    updates = []
    samples = []

    for pid, sym, lim, stop, tgt, stored, plan in rows:
        stats["scanned"] += 1
        plan = plan if isinstance(plan, dict) else (json.loads(plan) if plan else {})

        if plan.get("risk_reward_source") == SOURCE_TAG:
            stats["already_backfilled"] += 1
            continue

        value, reason = _compute(lim, stop, tgt)

        if value is None:
            if stored is None:
                stats["unchanged"] += 1
                continue
            stats["nulled"] += 1
            new_plan = dict(plan)
            new_plan["risk_reward_model_claimed"] = float(stored)
            new_plan["risk_reward_source"] = SOURCE_TAG
            new_plan["risk_reward_void_reason"] = reason
            updates.append((None, json.dumps(new_plan, default=str), pid))
            if len(samples) < 8:
                samples.append(f"  {sym:6s} id={pid} stored={stored} -> NULL ({reason})")
            continue

        # EXACT equality against the computed one-decimal value. Two weaker
        # comparisons were tried first and both left rows behind:
        #
        #   abs(stored - value) < 0.1   — `abs(10.8 - 10.9)` is 0.09999999999999964
        #                                 in binary float, so 171 rows off by a
        #                                 full decimal place counted as equal.
        #   round(stored, 1) == value   — `round(1.25, 1)` is 1.2 under banker's
        #                                 rounding, so a stored 1.25 matched a
        #                                 computed 1.2 and the model's two-decimal
        #                                 number survived (true value 1.1667).
        #
        # The invariant worth holding is simple: stored R:R IS the computed value,
        # to the digit. Anything else needs a rule about how close is close
        # enough, and every such rule leaked.
        if stored is not None and float(stored) == value:
            stats["unchanged"] += 1
            continue

        err = abs(float(stored) - value) if stored is not None else 0.0
        stats["max_error"] = max(stats["max_error"], round(err, 2))
        if stored is not None:
            if float(stored) > value:
                stats["overstated"] += 1
            else:
                stats["understated"] += 1
        stats["corrected"] += 1

        new_plan = dict(plan)
        if stored is not None:
            new_plan["risk_reward_model_claimed"] = float(stored)
        new_plan["risk_reward_source"] = SOURCE_TAG
        updates.append((value, json.dumps(new_plan, default=str), pid))
        if len(samples) < 8:
            samples.append(f"  {sym:6s} id={pid} stored={stored} -> {value}  "
                           f"(L{lim} S{stop} T{tgt})")

    print(f"scanned {stats['scanned']} plans")
    for line in samples:
        print(line)
    print(f"\n  already backfilled : {stats['already_backfilled']}")
    print(f"  unchanged (correct): {stats['unchanged']}")
    print(f"  corrected          : {stats['corrected']}"
          f"   (overstated {stats['overstated']} · understated {stats['understated']})")
    print(f"  voided to NULL     : {stats['nulled']}")
    print(f"  largest error found: {stats['max_error']}")

    if not apply:
        print(f"\nDRY RUN — nothing written. {len(updates)} rows would change. "
              f"Re-run with --apply to commit.")
        return {"ok": True, "dry_run": True, "would_change": len(updates), **stats}

    # One transaction: a failure part-way leaves nothing half written.
    cur.executemany(
        "UPDATE watchlist_entry_plans SET risk_reward = %s, plan = %s::jsonb WHERE id = %s",
        updates)
    conn.commit()
    print(f"\nAPPLIED — {len(updates)} rows updated in one transaction.")
    return {"ok": True, "dry_run": False, "changed": len(updates), **stats}


def main():
    ap = argparse.ArgumentParser(description="Recompute entry-plan risk_reward from stored levels")
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = run(apply=args.apply)
    if args.json:
        print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
