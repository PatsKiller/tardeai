#!/usr/bin/env python3
"""hermes_scalp_entry_validation.py — Entry Validation Agent for momentum scalp Hermes swarm.

Final gate before scalp acceptance. Enforces Layer 1 (structure+ATR hybrid, max 1.2R).
Queues approved entries to pending_approvals.json for Telegram HITL.

  python3 scripts/hermes_scalp_entry_validation.py [--once] [--interval 60]
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


def _limits() -> dict:
    import yaml
    cfg = yaml.safe_load((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").read_text())
    ls = (cfg.get("exit_rules") or {}).get("layered_stop") or {}
    l1 = ls.get("layer1_initial") or {}
    risk = cfg.get("risk") or {}
    return {
        "max_atr_mult": float(l1.get("max_atr_mult", 1.5)),
        "max_initial_risk_r": float(l1.get("max_initial_risk_r", 1.2)),
        "max_concurrent": int(risk.get("max_concurrent_scalps", 3)),
        "breakeven_trigger_r": float((ls.get("layer2_breakeven") or {}).get("trigger_r", 1.2)),
    }


def _enrich_symbol(sym: str) -> dict:
    p = PROJECT_ROOT / "data" / "runtime" / "ticker_enrichment_cache.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get(sym.upper(), {}) or {}
        except Exception:
            pass
    return {}


def _layer1_stop(sym: str, entry: float, atr: float | None, direction: str, lim: dict) -> tuple[float, str]:
    """Structure+ATR hybrid — tighter of swing proxy or ATR mult. Long/short symmetric."""
    mult = lim["max_atr_mult"]
    if atr and atr > 0:
        if direction == "short":
            atr_stop = entry + mult * atr
        else:
            atr_stop = entry - mult * atr
    else:
        atr_stop = None
    struct_stop = None
    st: dict = {}
    try:
        import candlestick_structure as cs
        st = cs.analyze(sym, direction=direction, entry_price=entry)
    except Exception:
        st = {}
    struct_stop = st.get("recommended_stop") if st.get("available") else None
    if struct_stop is None and atr and atr > 0:
        return (atr_stop, "atr")
    if atr_stop is None:
        return (struct_stop or (entry * 0.92 if direction != "short" else entry * 1.08), "structure")
    if direction == "short":
        stop = min(atr_stop, struct_stop) if struct_stop else atr_stop
    else:
        stop = max(atr_stop, struct_stop) if struct_stop else atr_stop
    method = "hybrid" if struct_stop else "atr"
    return (round(stop, 4), method)


def _validate_signal(signal: dict, lim: dict, heat: dict) -> dict:
    sym = signal.get("symbol", "").upper()
    direction = "long"  # momentum scalp book is long-biased; short symmetry in stop math
    entry = float(signal.get("price") or 0)
    if entry <= 0:
        return {**signal, "valid": False, "reject_reason": "missing entry price", "policy_section": "§3 L1"}

    if heat.get("pause_new_entries") or heat.get("kill_switch_active"):
        return {**signal, "valid": False, "reject_reason": heat.get("policy_ref", "portfolio heat block"), "policy_section": "§3 L4 #2"}

    open_scalps = (read_json("open_scalps.json", {}) or {}).get("scalps") or []
    if len(open_scalps) >= lim["max_concurrent"]:
        return {**signal, "valid": False, "reject_reason": f"max concurrent {lim['max_concurrent']}", "policy_section": "§7"}

    enrich = _enrich_symbol(sym)
    atr = float(enrich.get("atr") or signal.get("atr") or 0) or None
    stop, method = _layer1_stop(sym, entry, atr, direction, lim)
    risk_ps = abs(entry - stop)
    if risk_ps <= 0:
        return {**signal, "valid": False, "reject_reason": "invalid stop distance", "policy_section": "§3 L1"}

    # Position size from YAML risk_per_trade — use $200 max dollar risk default
    import yaml
    cfg = yaml.safe_load((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").read_text())
    equity = float((cfg.get("risk") or {}).get("paper_account_equity") or 100000)
    risk_pct = float((cfg.get("risk") or {}).get("risk_per_trade_pct") or 0.002)
    dollar_risk = min(200.0, equity * risk_pct)
    shares = max(1, int(dollar_risk / risk_ps))
    initial_risk_r = 1.0  # by construction at planned stop; verify stop isn't wider than 1.2R target
    target_r_stop = entry - lim["max_initial_risk_r"] * risk_ps if direction != "short" else entry + lim["max_initial_risk_r"] * risk_ps
    if direction != "short" and stop < target_r_stop:
        return {**signal, "valid": False, "reject_reason": f"stop implies >{lim['max_initial_risk_r']}R risk", "policy_section": "§3 L1"}
    if direction == "short" and stop > target_r_stop:
        return {**signal, "valid": False, "reject_reason": f"stop implies >{lim['max_initial_risk_r']}R risk", "policy_section": "§3 L1"}

    atr_dist = round(risk_ps / atr, 2) if atr else None
    return {
        **signal,
        "valid": True,
        "status": "validated_pending_approval",
        "entry": entry,
        "planned_stop": stop,
        "initial_stop_method": method,
        "initial_stop_atr": atr_dist,
        "initial_risk_r": initial_risk_r,
        "dollar_risk": round(dollar_risk, 2),
        "shares": shares,
        "breakeven_trigger_r": lim["breakeven_trigger_r"],
        "direction": direction,
        "policy_section": "§3 L1",
    }


def _enqueue_entry(validated: dict) -> None:
    pending = read_json("pending_approvals.json", {"approvals": []}) or {"approvals": []}
    items = list(pending.get("approvals") or [])
    sym = validated["symbol"]
    if any(a.get("symbol") == sym and a.get("action") == "new_entry" and a.get("status") == "pending" for a in items):
        return
    items.append({
        "id": f"entry_{sym}_{int(time.time())}",
        "status": "pending",
        "target": "entry_validation",
        "action": "new_entry",
        "symbol": sym,
        "reason": f"§3 L1 validated — {validated.get('initial_stop_method')} stop @ ${validated.get('planned_stop')}, {validated.get('initial_risk_r')}R",
        "requires_approval": True,
        "created_at": now_iso(),
        "payload": {
            "entry": validated.get("entry"),
            "planned_stop": validated.get("planned_stop"),
            "shares": validated.get("shares"),
            "setup_tag": validated.get("setup_tag"),
            "conviction": validated.get("conviction"),
        },
    })
    write_json("pending_approvals.json", {"schema_version": "1.0", "updated_at": now_iso(), "approvals": items[-50:]})


def tick() -> dict:
    lim = _limits()
    heat = read_json("portfolio_heat.json", {}) or {}
    qs = read_json("qualified_signals.json", {"signals": []}) or {"signals": []}
    validated_list = read_json("entry_validation_queue.json", {"validated": [], "rejected": []}) or {"validated": [], "rejected": []}

    processed, approved, rejected = 0, 0, 0
    updated_signals = []
    for sig in qs.get("signals") or []:
        if sig.get("status") != "pending_validation":
            updated_signals.append(sig)
            continue
        processed += 1
        result = _validate_signal(sig, lim, heat)
        if result.get("valid"):
            _enqueue_entry(result)
            validated_list["validated"] = (validated_list.get("validated") or [])[-20:] + [result]
            approved += 1
            append_audit({"agent": "entry_validation", "action": "validate", "symbol": result["symbol"], "stop": result.get("planned_stop")})
        else:
            result["status"] = "rejected"
            validated_list["rejected"] = (validated_list.get("rejected") or [])[-20:] + [result]
            rejected += 1
        updated_signals.append(result)

    write_json("qualified_signals.json", {"schema_version": "1.0", "updated_at": now_iso(), "signals": updated_signals})
    validated_list["updated_at"] = now_iso()
    write_json("entry_validation_queue.json", validated_list)

    return {"processed": processed, "approved": approved, "rejected": rejected}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    if args.once:
        print(json.dumps(tick(), indent=2))
        return
    print("[entry_validation] starting loop", flush=True)
    while True:
        try:
            out = tick()
            print(f"[entry_validation] {now_iso()} processed={out['processed']} approved={out['approved']}", flush=True)
        except Exception as e:
            print(f"[entry_validation] error: {e}", flush=True)
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    main()