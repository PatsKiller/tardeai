#!/usr/bin/env python3
"""hermes_scalp_orchestrator.py — Hermes Orchestrator (Supervisor) for momentum scalp swarm.

Routes tasks between specialist agents, enforces 4-layer stop policy gates, manages
Telegram human-in-the-loop approvals (OpenClaw), and maintains audit logs.

Paper phase (4.4→4.5): all material actions require operator approval.

  python3 scripts/hermes_scalp_orchestrator.py [--once] [--interval 60]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.momentum_scalp_swarm_state import (  # noqa: E402
    now_iso, read_json, write_json, append_audit, state_health,
)


POLICY_DOC = "docs/MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md"


def _policy_gate_heat() -> tuple[bool, str]:
    heat = read_json("portfolio_heat.json", {}) or {}
    if heat.get("kill_switch_active"):
        return False, "§7 portfolio heat kill switch — pause new entries"
    if heat.get("pause_new_entries"):
        return False, "§3 L4 #2 portfolio heat > 3.5% — pause new entries"
    pct = float(heat.get("aggregate_open_risk_pct") or 0)
    if pct >= 4.5:
        return False, "§7 heat ≥ 4.5% — hard kill"
    return True, "heat ok"


def _policy_gate_breakeven(symbol: str, direction: str, proposed_stop: float, entry: float) -> tuple[bool, str]:
    """Reject stops that would violate mandatory Layer 2 breakeven rule."""
    scalp = None
    for s in (read_json("open_scalps.json", {}) or {}).get("scalps") or []:
        if str(s.get("symbol", "")).upper() == symbol.upper():
            scalp = s
            break
    if not scalp:
        return True, "no open scalp"
    be_secured = scalp.get("breakeven_secured") or scalp.get("breakeven_moved")
    unrealized_r = float(scalp.get("unrealized_r") or 0)
    trigger_r = float(scalp.get("breakeven_trigger_r") or 1.2)
    if unrealized_r >= trigger_r and not be_secured:
        # Must move to breakeven — reject any stop that leaves risk on table
        is_long = direction.lower() != "short"
        if is_long and proposed_stop < entry:
            return False, f"§3 L2 mandatory breakeven — long stop {proposed_stop} below entry {entry}"
        if not is_long and proposed_stop > entry:
            return False, f"§3 L2 mandatory breakeven — short stop {proposed_stop} above entry {entry}"
    return True, "breakeven ok"


def _route_pending_approvals() -> list[dict]:
    """Surface pending material actions for Telegram/OpenClaw review."""
    pending = read_json("pending_approvals.json", {"approvals": []}) or {"approvals": []}
    return list(pending.get("approvals") or [])


def _enqueue_approval(action: dict) -> None:
    pending = read_json("pending_approvals.json", {"approvals": []}) or {"approvals": []}
    items = list(pending.get("approvals") or [])
    action = {**action, "id": action.get("id") or f"apr_{int(time.time())}", "status": "pending", "created_at": now_iso()}
    items.append(action)
    write_json("pending_approvals.json", {"schema_version": "1.0", "updated_at": now_iso(), "approvals": items[-50:]})
    append_audit({"agent": "orchestrator", "action": "enqueue_approval", **action})


def tick() -> dict:
    ok_heat, heat_msg = _policy_gate_heat()
    stoplight = read_json("stoplight_status.json", {}) or {}
    red_count = sum(1 for p in (stoplight.get("positions") or []) if (p.get("stoplight") or "").lower() == "red")
    amber_count = sum(1 for p in (stoplight.get("positions") or []) if (p.get("stoplight") or "").lower() in ("amber", "yellow"))

    routes = []
    if not ok_heat:
        routes.append({"target": "entry_validation", "action": "block_new_entries", "reason": heat_msg})

    # Phase 2: route qualified signals → Entry Validation
    qs = read_json("qualified_signals.json", {}) or {}
    pending_val = [s for s in (qs.get("signals") or []) if s.get("status") == "pending_validation" and s.get("policy_compliant")]
    if ok_heat and pending_val:
        routes.append({
            "target": "entry_validation",
            "action": "validate_batch",
            "symbols": [s["symbol"] for s in pending_val[:5]],
            "count": len(pending_val),
            "requires_approval": False,
        })
    for pos in stoplight.get("positions") or []:
        if pos.get("regime_shift_detected"):
            routes.append({
                "target": "stop_adjustment",
                "action": "propose_tighten",
                "symbol": pos.get("symbol"),
                "reason": "§3 L4 #1 regime shift Trending→Ranging — 0.5× ATR tighten",
                "requires_approval": True,
            })
        for sug in pos.get("policy_suggestions") or []:
            if isinstance(sug, str) and "breakeven" in sug.lower():
                routes.append({
                    "target": "stop_adjustment",
                    "action": "propose_breakeven",
                    "symbol": pos.get("symbol"),
                    "reason": f"§3 L2 mandatory breakeven — {sug}",
                    "requires_approval": True,
                })

    # Phase 3: log exit suggestions (Exit Intelligence agent already enqueues approvals)
    exit_data = read_json("exit_suggestions.json", {}) or {}
    for sug in (exit_data.get("suggestions") or [])[:5]:
        if sug.get("action") in ("suggest_partial_exit", "suggest_stop_review"):
            routes.append({
                "target": "exit_intelligence",
                "action": sug.get("action"),
                "symbol": sug.get("symbol"),
                "reason": sug.get("reason"),
                "requires_approval": False,
            })

    for route in routes:
        if route.get("requires_approval"):
            _enqueue_approval(route)

    append_audit({
        "agent": "orchestrator",
        "action": "tick",
        "heat_ok": ok_heat,
        "heat_msg": heat_msg,
        "red_positions": red_count,
        "amber_positions": amber_count,
        "routes": len(routes),
    })

    return {
        "heat_ok": ok_heat,
        "heat_msg": heat_msg,
        "routes": routes,
        "pending_approvals": len(_route_pending_approvals()),
        "state_health": state_health(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.once:
        out = tick()
        print(json.dumps(out, indent=2, default=str))
        return

    print(f"[orchestrator] starting loop interval={args.interval}s policy={POLICY_DOC}", flush=True)
    while True:
        try:
            out = tick()
            print(f"[orchestrator] {now_iso()} heat_ok={out['heat_ok']} routes={len(out['routes'])} pending={out['pending_approvals']}", flush=True)
        except Exception as e:
            print(f"[orchestrator] error: {e}", flush=True)
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    main()