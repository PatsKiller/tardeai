#!/usr/bin/env python3
"""options_lifecycle_run.py — the lifecycle desk's cron entrypoint.

Order of operations per run (each stage fail-soft per position, loud in output):
  1. intake reconcile      broker truth → canonical mirror (NEW/DRIFTED/VANISHED)
  2. snapshot + decide     fresh quotes → immutable snapshot → policy decision
  3. alerts                assignment review + persistent alert lifecycle
  4. resolve               closed positions release their live alerts
  5. escalate              unacked urgent alerts re-notify (bounded)

Writes data/runtime/options_lifecycle_latest.json for the UI (positions with
latest snapshot economics + decision + live alerts + health).
Advisory only — zero order paths. Usage: options_lifecycle_run.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_model import ensure_tables, open_strategies
from options_lifecycle_engine import (policy, quote_leg, strategy_economics,
                                      persist_snapshot, decide, record_decision,
                                      reduce_decision, defense_posture_for)
from options_lifecycle_alerts import (ensure_alert_tables, process_alerts,
                                      resolve_alerts_for, escalate_unacked,
                                      open_alerts, assignment_review)
from options_lifecycle_intake import reconcile

SNAP = ROOT / "data" / "runtime" / "options_lifecycle_latest.json"


def run(dry: bool = False) -> dict:
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    ensure_tables(cur, conn)
    ensure_alert_tables(cur, conn)
    pol = policy()

    intake = reconcile(dry=dry)
    for v in intake.get("vanished", []):
        resolve_alerts_for(cur, conn, v["strategy_position_id"], reason="legs vanished at broker")

    out_positions = []
    for s in open_strategies(cur):
        try:
            quotes = {l["leg_id"]: quote_leg(l) for l in s["legs"] if l["status"] == "open"}
            eco = strategy_economics(s, quotes)
            if dry:
                findings = assignment_review(s, eco, pol)
                d = reduce_decision(decide(s, eco, pol, defense_posture_for(s["underlying"])),
                                    findings, eco)
                alert = None
            else:
                snap_id, eco = persist_snapshot(cur, conn, s, eco)
                findings = assignment_review(s, eco, pol)
                # v1.1 P1: ONE primary per snapshot — findings fold in via precedence
                d = reduce_decision(decide(s, eco, pol, defense_posture_for(s["underlying"])),
                                    findings, eco)
                did = record_decision(cur, conn, s["strategy_position_id"], snap_id, d, pol)
                alert = process_alerts(cur, conn, s, eco, d, did, pol, notify=True,
                                       findings=findings)
            out_positions.append({
                "strategy_position_id": s["strategy_position_id"], "broker": s["broker"],
                "account_key": s["account_key"], "strategy_type": s["strategy_type"],
                "underlying": s["underlying"], "status": s["status"],
                "data_quality_status": s["data_quality_status"],
                "opened_at": str(s.get("opened_at") or ""),
                "legs": [{k: str(v) if k == "expiration" else v for k, v in l.items()
                          if k in ("occ_symbol", "leg_role", "side", "contracts", "strike",
                                   "expiration", "opening_price", "status")}
                         for l in s["legs"]],
                "economics": {k: eco.get(k) for k in
                              ("dte_nearest", "underlying_price", "strategy_mark", "unrealized_pnl",
                               "pct_max_profit_captured", "max_profit_possible", "mfe", "mae",
                               "giveback", "extrinsic_value", "short_distance_pct", "short_delta",
                               "max_spread_pct", "net", "flags")},
                "decision": d, "alert": alert,
            })
        except Exception as e:
            out_positions.append({"strategy_position_id": s["strategy_position_id"],
                                  "underlying": s["underlying"],
                                  "decision": {"recommendation": "DATA_BLOCKED", "urgency": "amber",
                                               "rationale": f"engine error: {str(e)[:160]} — fail closed"}})

    escalated = [] if dry else escalate_unacked(cur, conn, pol)

    from options_lifecycle_health import health_checks
    health = health_checks(cur)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": pol["policy_version"],
        "intake": intake,
        "positions": out_positions,
        "alerts": [] if dry else [{**a, "created_at": str(a["created_at"]),
                                   "snoozed_until": str(a["snoozed_until"]) if a["snoozed_until"] else None}
                                  for a in open_alerts(cur)],
        "escalated": escalated,
        "health": health,
        "counts": {
            "open_strategies": len(out_positions),
            "action_now": sum(1 for p in out_positions if p["decision"]["urgency"] == "red"),
            "harvest_review": sum(1 for p in out_positions
                                  if p["decision"]["recommendation"].startswith("HARVEST")),
            "data_blocked": sum(1 for p in out_positions
                                if p["decision"]["recommendation"] == "DATA_BLOCKED"),
        },
    }
    if not dry:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(payload, default=str))
    return payload


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    r = run(dry=a.dry_run)
    print(f"[lifecycle] {r['counts']['open_strategies']} strategies · "
          f"{r['counts']['action_now']} red · {r['counts']['harvest_review']} harvest · "
          f"{r['counts']['data_blocked']} blocked · intake new={len(r['intake']['new'])} "
          f"vanished={len(r['intake']['vanished'])} errors={list(r['intake']['errors']) or 'none'}")
