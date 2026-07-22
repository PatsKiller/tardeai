#!/usr/bin/env python3
"""watch_decision_scheduler.py — V5 server-owned refresh cadence (Section 4).

The browser NEVER schedules. This runs from cron (every 15 min, 07:40–16:30
ET weekdays), reads config/watch_decision_refresh_policy.yaml, classifies the
governed population into P0–P3, and enqueues LOCAL_QUANT rebuilds for symbols
whose live packet is past its tier's full-packet ceiling OR input-invalidated.
STANDARD_BLIND is enqueued only when the packet's last model pass is older than
the tier's blind ceiling AND inputs materially changed. PREMIUM is never
scheduled — operator-only by construction (the orchestrator refuses it without
an enabled registry provider + explicit confirmation).

    --dry-run   full plan + call/cost estimates, NO enqueue (required first run)
    --run       sweep stale jobs, then enqueue due work (bounded per pass)

Population: symbols with a live decision packet + starred symbols (the batch
generator's top-50-by-rank population remains the nightly wide pass).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_decision_refresh as wdr  # noqa: E402


def _now():
    return datetime.now(timezone.utc)


def build_plan(conn) -> dict:
    import packet_invalidation as pi
    pol = wdr.load_policy()
    tiers = pol.get("tiers") or {}
    limits = pol.get("limits") or {}
    cap = int(limits.get("max_symbols_per_scheduler_pass", 40))
    cur = conn.cursor()
    cur.execute("""SELECT symbol, generated_at, model_review_mode FROM decision_packets
                   WHERE superseded_by IS NULL""")
    packets = {r[0].upper(): {"generated_at": r[1], "mode": r[2]} for r in cur.fetchall()}
    cur.execute("SELECT upper(symbol) FROM operator_starred_symbols")
    starred = {r[0] for r in cur.fetchall()}
    population = sorted(set(packets) | starred)

    cur.execute("""SELECT DISTINCT symbol FROM watch_decision_refresh_jobs
                   WHERE state IN ('QUEUED','RUNNING')""")
    in_flight = {r[0] for r in cur.fetchall()}

    plan = {"local": [], "blind": [], "skipped_in_flight": [], "not_due": []}
    now = _now()
    for sym in population:
        if sym in in_flight:
            plan["skipped_in_flight"].append(sym)
            continue
        tier = wdr.classify_priority(sym, conn)
        tcfg = tiers.get(tier) or {}
        pk = packets.get(sym)
        local_ceiling = tcfg.get("full_local_packet_max_minutes")
        blind_ceiling = tcfg.get("standard_blind_max_minutes")
        if not pk:
            plan["local"].append({"symbol": sym, "tier": tier, "why": "PACKET_ABSENT"})
            continue
        age_min = (now - pk["generated_at"]).total_seconds() / 60
        due_local = local_ceiling and age_min > float(local_ceiling)
        if not due_local:
            # invalidation-driven due-ness (cheap check only when inside the ceiling)
            try:
                snap = pi.build_current_input_snapshot(sym, conn)
                cur.execute("""SELECT packet FROM decision_packets
                               WHERE upper(symbol)=%s AND superseded_by IS NULL""", (sym,))
                cmpr = pi.compare_packet_inputs(cur.fetchone()[0], snap)
                if not cmpr.get("inputs_match"):
                    due_local = True
            except Exception:
                conn.rollback()
        if due_local:
            plan["local"].append({"symbol": sym, "tier": tier,
                                  "why": f"age {age_min:.0f}m > ceiling {local_ceiling}m"
                                  if local_ceiling and age_min > float(local_ceiling) else "inputs changed"})
            # blind rides along only when the model pass is ALSO past its ceiling
            if blind_ceiling and float(blind_ceiling) > 0 and pk["mode"] in ("BLIND", "SINGLE_LANE"):
                if age_min > float(blind_ceiling):
                    plan["blind"].append({"symbol": sym, "tier": tier})
        else:
            plan["not_due"].append(sym)

    plan["local"] = plan["local"][:cap]
    blind_syms = {b["symbol"] for b in plan["blind"]}
    plan["blind"] = [b for b in plan["blind"] if b["symbol"] in {x["symbol"] for x in plan["local"]} and b["symbol"] in blind_syms]
    lane_budget = int(limits.get("max_blind_lane_calls_per_hour", 60))
    plan["blind"] = plan["blind"][: max(0, lane_budget // 2)]
    plan["estimates"] = {
        "local_symbols": len(plan["local"]),
        "blind_symbols": len(plan["blind"]),
        "lane_calls": 2 * len(plan["blind"]),
        "paid_cost_usd": 0,
        "est_wall_minutes": round(len(plan["local"]) * 1.5 / max(1, int(limits.get("worker_concurrency", 2))), 1),
        "population": len(population), "in_flight": len(plan["skipped_in_flight"]),
        "not_due": len(plan["not_due"]), "policy_version": wdr.policy_version(),
    }
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    conn = wdr._conn()
    if a.dry_run or not a.run:
        plan = build_plan(conn)
        print(json.dumps({"dry_run": True, **plan["estimates"],
                          "local": plan["local"], "blind": plan["blind"],
                          "deferred_in_flight": plan["skipped_in_flight"]},
                         indent=2, default=str))
        return
    swept = wdr.sweep_stale()
    plan = build_plan(conn)
    out = {"swept": len(swept.get("swept", [])), **plan["estimates"], "runs": []}
    blind_syms = {b["symbol"] for b in plan["blind"]}
    local_syms = [x["symbol"] for x in plan["local"] if x["symbol"] not in blind_syms]
    if local_syms:
        r = wdr.enqueue_run(local_syms, scope="AFFECTED_DIMENSIONS", analysis_tier="LOCAL_QUANT",
                            requested_by="scheduler", reason="policy_cadence")
        out["runs"].append({"tier": "LOCAL_QUANT", "run_id": r.get("run_id"), "queued": r.get("queued")})
    if blind_syms:
        r = wdr.enqueue_run(sorted(blind_syms), scope="AFFECTED_DIMENSIONS", analysis_tier="STANDARD_BLIND",
                            requested_by="scheduler", reason="policy_blind_cadence")
        out["runs"].append({"tier": "STANDARD_BLIND", "run_id": r.get("run_id"), "queued": r.get("queued")})
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
