#!/usr/bin/env python3
"""hermes_scalp_live_monitor.py — persistent Live Monitor Agent for momentum scalp swarm.

Wraps scalp_stop_monitor.run() + per-symbol regime detection; writes shared state files.
Paper phase: advisory only — no broker writes. Telegram approval via pending_approvals.json.

  python3 scripts/hermes_scalp_live_monitor.py [--once] [--interval 30]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.momentum_scalp_swarm_state import now_iso, write_json, append_audit, read_json  # noqa: E402


def _sync_from_monitor() -> dict:
    from scalp_stop_monitor import run as monitor_run

    return monitor_run()


def _stoplight_level(p: dict) -> str:
    dist = p.get("stop_distance_R")
    if dist is not None and dist < 0.3:
        return "yellow"
    if p.get("regime_shifted"):
        return "amber"
    cur_r = p.get("current_R")
    be_trigger = p.get("dist_to_breakeven_R")
    if cur_r is not None and be_trigger is not None and be_trigger <= 0 and not p.get("breakeven_secured"):
        return "amber"
    return "green"


def _sync_regime(positions: list[dict], market_regime: str | None) -> dict:
    sym_map: dict = {}
    try:
        from lib.momentum_scalp_regime import detect_regime, build_context_from_enrich, _load_state
        enrich_path = PROJECT_ROOT / "data" / "runtime" / "ticker_enrichment_cache.json"
        enrich_all = {}
        if enrich_path.exists():
            enrich_all = json.loads(enrich_path.read_text())
        runtime_state = _load_state(PROJECT_ROOT)
        for p in positions:
            sym = str(p.get("symbol") or "").upper()
            if not sym:
                continue
            ctx = build_context_from_enrich(
                enrich_all.get(sym),
                price=p.get("price"),
                direction=p.get("side", "long"),
            )
            sym_map[sym] = detect_regime(
                sym, ctx,
                entry_regime=p.get("entry_regime"),
                project_root=PROJECT_ROOT,
            )
        sym_map = {**{k: v for k, v in runtime_state.items() if isinstance(v, dict)}, **sym_map}
    except Exception:
        sym_map = read_json("regime_state.json", {}).get("symbols") or {}

    out = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "market_regime": market_regime,
        "symbols": sym_map,
    }
    write_json("regime_state.json", out)
    return out


def tick() -> dict:
    report = _sync_from_monitor()
    positions = report.get("open_scalps") or []
    symbols = list({str(p.get("symbol") or "").upper() for p in positions if p.get("symbol")})
    heat_pct = report.get("portfolio_heat_pct")
    heat_tier = "red" if report.get("heat_kill_active") else "amber" if report.get("heat_tighten_active") else "green"

    heat = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "account_equity": report.get("paper_equity"),
        "aggregate_open_risk_dollars": report.get("open_risk_usd", 0),
        "aggregate_open_risk_pct": heat_pct,
        "open_scalp_count": len(positions),
        "heat_tier": heat_tier,
        "pause_new_entries": bool(report.get("pause_new_entries")),
        "kill_switch_active": bool(report.get("heat_kill_active")),
        "policy_ref": "MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md §3 L4 #2, §7",
    }
    write_json("portfolio_heat.json", heat)

    regime_state = _sync_regime(positions, report.get("current_regime"))

    stoplight = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "positions": [
            {
                "symbol": p.get("symbol"),
                "trade_id": p.get("id"),
                "direction": p.get("side", "long"),
                "stoplight": _stoplight_level(p),
                "distance_to_stop_r": p.get("stop_distance_R"),
                "distance_to_breakeven_r": p.get("dist_to_breakeven_R"),
                "current_r": p.get("current_R"),
                "regime": (regime_state.get("symbols") or {}).get(str(p.get("symbol", "")).upper(), {}).get("regime"),
                "regime_shift_detected": p.get("regime_shifted") or (regime_state.get("symbols") or {}).get(
                    str(p.get("symbol", "")).upper(), {}
                ).get("regime_shift_detected"),
                "policy_suggestions": [a.get("msg") for a in (report.get("alerts") or [])
                                       if a.get("symbol") == p.get("symbol")],
                "suggested_stop": p.get("suggested_stop"),
            }
            for p in positions
        ],
    }
    write_json("stoplight_status.json", stoplight)

    open_scalps = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "scalps": positions,
    }
    write_json("open_scalps.json", open_scalps)

    alerts = report.get("alerts") or []
    for a in alerts:
        if a.get("level") in ("amber", "red", "yellow"):
            append_audit({
                "agent": "live_monitor",
                "action": "alert",
                "symbol": a.get("symbol"),
                "level": a.get("level"),
                "reason": a.get("msg"),
                "rule": a.get("rule"),
                "policy_section": f"MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md §{a.get('rule', '4')}",
            })

    return {"positions": len(positions), "alerts": len(alerts), "heat_pct": heat_pct, "symbols": len(symbols)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    if args.once:
        out = tick()
        print(json.dumps(out, indent=2))
        return

    print(f"[live_monitor] starting loop interval={args.interval}s", flush=True)
    while True:
        try:
            out = tick()
            print(f"[live_monitor] {now_iso()} positions={out['positions']} heat={out['heat_pct']}%", flush=True)
        except Exception as e:
            print(f"[live_monitor] error: {e}", flush=True)
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()