#!/usr/bin/env python3
"""hermes_scalp_exit_intelligence.py — Exit Intelligence Agent (Phase 3).

Monitors open scalps vs Street consensus and profit extension. Writes exit_suggestions.json
and queues material actions to pending_approvals.json (Telegram HITL).

  python3 scripts/hermes_scalp_exit_intelligence.py [--once] [--interval 60]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.momentum_scalp_swarm_state import now_iso, read_json, write_json, append_audit  # noqa: E402

EXTENDED_ABOVE_PCT = 10.0
EXTENDED_BELOW_PCT = -15.0
HIGH_PROFIT_R = 2.0


def _enqueue_suggestion(sug: dict) -> None:
    pending = read_json("pending_approvals.json", {"approvals": []}) or {"approvals": []}
    items = list(pending.get("approvals") or [])
    key = (sug.get("symbol"), sug.get("action"), sug.get("suggestion_type"))
    if any((a.get("symbol"), a.get("action"), a.get("suggestion_type")) == key and a.get("status") == "pending" for a in items):
        return
    items.append({
        "id": f"exit_{sug['symbol']}_{int(time.time())}",
        "status": "pending",
        "target": "exit_intelligence",
        "action": sug.get("action", "suggest_exit"),
        "suggestion_type": sug.get("suggestion_type"),
        "symbol": sug["symbol"],
        "reason": sug.get("reason"),
        "policy_section": sug.get("policy_section", "§4 Exit Intelligence"),
        "requires_approval": True,
        "created_at": now_iso(),
        "payload": {k: v for k, v in sug.items() if k not in ("symbol", "action", "reason")},
    })
    write_json("pending_approvals.json", {"schema_version": "1.0", "updated_at": now_iso(), "approvals": items[-50:]})


def _analyze_position(pos: dict, consensus: dict | None) -> dict | None:
    sym = str(pos.get("symbol") or "").upper()
    if not sym:
        return None
    price = pos.get("price") or pos.get("current_price")
    entry = pos.get("entry") or pos.get("entry_price")
    direction = str(pos.get("side") or pos.get("direction") or "long").lower()
    current_r = pos.get("current_R") or pos.get("current_r")
    stop = pos.get("stop") or pos.get("planned_stop")

    try:
        price_f = float(price) if price is not None else None
        entry_f = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        return None

    cons = consensus or {}
    mean = cons.get("target_mean")
    out: dict = {
        "symbol": sym,
        "direction": direction,
        "price": price_f,
        "current_r": current_r,
        "consensus_mean": mean,
        "has_street": bool(mean),
    }

    if mean and price_f:
        from lib.stop_consensus_check import price_vs_consensus_pct, check_stop_over_consensus

        pct = price_vs_consensus_pct(price_f, mean)
        out["price_vs_consensus_pct"] = pct
        is_long = direction != "short"
        if is_long and pct is not None and pct >= EXTENDED_ABOVE_PCT and (current_r is None or float(current_r) >= HIGH_PROFIT_R):
            out.update({
                "suggestion_type": "partial_profit_extended_above_street",
                "action": "suggest_partial_exit",
                "severity": "amber",
                "reason": f"{sym} price +{pct}% above Street μ ${mean} at +{current_r}R — consider partial profit / advisory trail tighten",
                "policy_section": "§4 Exit Intelligence + MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL",
            })
            return out
        if not is_long and pct is not None and pct <= -EXTENDED_ABOVE_PCT and (current_r is None or float(current_r) >= HIGH_PROFIT_R):
            out.update({
                "suggestion_type": "partial_profit_extended_below_street",
                "action": "suggest_partial_exit",
                "severity": "amber",
                "reason": f"{sym} short price {pct}% below Street μ ${mean} at +{current_r}R — consider cover partial",
                "policy_section": "§4 Exit Intelligence",
            })
            return out
        if is_long and pct is not None and pct <= EXTENDED_BELOW_PCT and current_r is not None and float(current_r) >= HIGH_PROFIT_R:
            out.update({
                "suggestion_type": "profit_below_street_review",
                "action": "suggest_trail_review",
                "severity": "yellow",
                "reason": f"{sym} +{current_r}R profit but price {pct}% below Street μ — trail may be too tight",
                "policy_section": "§4 Exit Intelligence",
            })
            return out

        if stop is not None:
            conflict = check_stop_over_consensus(sym, float(stop), price_f, cons)
            if conflict:
                out.update({
                    "suggestion_type": "stop_over_consensus",
                    "action": "suggest_stop_review",
                    "severity": "red",
                    "reason": f"{sym} protective stop ${stop} above Street μ ${mean} (+{conflict.get('consensus_gap_pct')}%)",
                    "policy_section": "stop_over_consensus_monitor",
                    "consensus_gap_pct": conflict.get("consensus_gap_pct"),
                })
                return out

    if current_r is not None and float(current_r) >= 2.5 and not mean:
        out.update({
            "suggestion_type": "high_profit_no_street",
            "action": "suggest_partial_exit",
            "severity": "yellow",
            "reason": f"{sym} at +{current_r}R with no Street coverage — consider partial profit per policy",
            "policy_section": "§4 Exit Intelligence",
        })
        return out

    return None


def tick() -> dict:
    from lib.stop_consensus_check import load_consensus_targets

    open_data = read_json("open_scalps.json", {}) or {}
    positions = open_data.get("scalps") or []
    consensus_map = load_consensus_targets(PROJECT_ROOT)

    suggestions = []
    for pos in positions:
        sym = str(pos.get("symbol") or "").upper()
        sug = _analyze_position(pos, consensus_map.get(sym))
        if sug:
            suggestions.append(sug)
            if sug.get("action") in ("suggest_partial_exit", "suggest_stop_review"):
                _enqueue_suggestion(sug)
            append_audit({
                "agent": "exit_intelligence",
                "action": "suggestion",
                "symbol": sym,
                "type": sug.get("suggestion_type"),
                "severity": sug.get("severity"),
            })

    payload = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "suggestions": suggestions,
        "open_positions_scanned": len(positions),
        "street_coverage": sum(1 for p in positions if consensus_map.get(str(p.get("symbol", "")).upper())),
        "policy_ref": "MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md §4",
    }
    write_json("exit_suggestions.json", payload)

    return {
        "scanned": len(positions),
        "suggestions": len(suggestions),
        "enqueued": sum(1 for s in suggestions if s.get("action") in ("suggest_partial_exit", "suggest_stop_review")),
        "street_coverage": payload["street_coverage"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    if args.once:
        print(json.dumps(tick(), indent=2))
        return
    print("[exit_intelligence] starting loop", flush=True)
    while True:
        try:
            out = tick()
            print(f"[exit_intelligence] {now_iso()} scanned={out['scanned']} suggestions={out['suggestions']}", flush=True)
        except Exception as e:
            print(f"[exit_intelligence] error: {e}", flush=True)
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    main()