#!/usr/bin/env python3
"""Audit hard-stop to trailing-stop conversions across all paper trades.

Usage:
    python scripts/audit_stop_to_trailing_conversion.py [--json]

Output:
    data/paper_trading/stop_trailing_audit_latest.json
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from db_adapter import _execute


def _q(sql, **kw):
    return _execute(sql, fetch=kw.get("fetch", "all")) or ([] if kw.get("fetch", "all") == "all" else {})


def audit():
    """Audit all paper trades for stop type and trailing conversions."""
    now = datetime.now(timezone.utc).isoformat()

    # All closed trades
    trades = _q("""
        SELECT id, symbol, strategy_id, entry_price, exit_price, stop_loss,
               exit_reason, pnl, r_multiple, hold_time_min, dollar_risk,
               max_favorable_excursion, max_adverse_excursion,
               created_at::text, closed_at::text
        FROM paper_trades WHERE status='closed' ORDER BY id
    """)

    # All stop-related risk actions
    actions = _q("""
        SELECT paper_trade_id, symbol, action_type, old_value, new_value,
               trigger_reason, trigger_price, action_time::text
        FROM paper_trade_risk_actions ORDER BY paper_trade_id, action_time
    """)

    # Group actions by trade
    actions_by_trade = {}
    for a in actions:
        tid = a["paper_trade_id"]
        actions_by_trade.setdefault(tid, []).append(a)

    # Classify each trade
    hard_stop_only = []
    trailing_converted = []
    no_stop_data = []
    stop_exits = []

    for t in trades:
        tid = t["id"]
        trade_actions = actions_by_trade.get(tid, [])
        exit_reason = t.get("exit_reason", "") or ""

        has_stop = t["stop_loss"] is not None
        is_stop_exit = "stop" in exit_reason.lower()

        # Check for trailing stop activity
        trailing_actions = [a for a in trade_actions if a["action_type"] in
                            ("trailing_stop_update", "trailing_stop_switch", "adjust_stop")]
        trailing_switch = [a for a in trade_actions if a["action_type"] == "trailing_stop_switch"]

        if not has_stop:
            no_stop_data.append(tid)
            continue

        if is_stop_exit:
            stop_exits.append({
                "trade_id": tid,
                "symbol": t["symbol"],
                "strategy": t["strategy_id"],
                "exit_reason": exit_reason,
                "entry": float(t["entry_price"]) if t["entry_price"] else None,
                "stop": float(t["stop_loss"]) if t["stop_loss"] else None,
                "exit_price": float(t["exit_price"]) if t["exit_price"] else None,
                "pnl": float(t["pnl"]) if t["pnl"] else None,
                "r_multiple": float(t["r_multiple"]) if t["r_multiple"] else None,
                "mfe": float(t["max_favorable_excursion"]) if t["max_favorable_excursion"] else None,
                "trailing_actions": len(trailing_actions),
                "was_converted": len(trailing_switch) > 0,
                "stop_type": "trailing" if trailing_switch else ("trailed" if trailing_actions else "hard"),
            })

        if trailing_switch:
            trailing_converted.append({
                "trade_id": tid,
                "symbol": t["symbol"],
                "strategy": t["strategy_id"],
                "conversion_action": trailing_switch[0]["action_type"],
                "old_stop": trailing_switch[0]["old_value"],
                "new_stop": trailing_switch[0]["new_value"],
                "trigger": trailing_switch[0].get("trigger_reason"),
                "total_adjustments": len(trailing_actions),
                "exit_reason": exit_reason,
                "pnl": float(t["pnl"]) if t["pnl"] else None,
                "r_multiple": float(t["r_multiple"]) if t["r_multiple"] else None,
            })
        elif trailing_actions:
            # R-multiple based auto-trailing (not operator-initiated switch)
            trailing_converted.append({
                "trade_id": tid,
                "symbol": t["symbol"],
                "strategy": t["strategy_id"],
                "conversion_action": "auto_r_trail",
                "total_adjustments": len(trailing_actions),
                "exit_reason": exit_reason,
                "pnl": float(t["pnl"]) if t["pnl"] else None,
                "r_multiple": float(t["r_multiple"]) if t["r_multiple"] else None,
            })
        else:
            hard_stop_only.append(tid)

    total_closed = len(trades)
    total_stop_exits = len(stop_exits)
    hard_stop_exits = len([s for s in stop_exits if s["stop_type"] == "hard"])
    trailing_stop_exits = len([s for s in stop_exits if s["stop_type"] in ("trailing", "trailed")])

    result = {
        "timestamp": now,
        "total_closed_trades": total_closed,
        "total_stop_exits": total_stop_exits,
        "hard_stop_exits": hard_stop_exits,
        "trailing_stop_exits": trailing_stop_exits,
        "converted_hard_to_trailing": len(trailing_converted),
        "converted_pct": round(len(trailing_converted) / max(total_closed, 1) * 100, 1),
        "hard_stop_only_pct": round(len(hard_stop_only) / max(total_closed, 1) * 100, 1),
        "no_stop_data": len(no_stop_data),
        "stop_exits_detail": stop_exits,
        "trailing_conversions": trailing_converted,
        "hard_stop_only_trade_ids": hard_stop_only,

        "risk_action_summary": {},
        "algorithm": {
            "exists": True,
            "name": "strategy_trailing_policy v2.3",
            "trigger": "R-multiple tiers per strategy family",
            "families": ["momentum", "swing", "income", "position"],
            "momentum_tiers": "breakeven@1R, 0.5R@1.5R, 1.0R@2R, 2.0R@3R",
            "swing_tiers": "breakeven@1R, 0.5R@1.5R, 1.0R@2R, 2.0R@3R",
            "income_tiers": "breakeven@1.5R, 0.5R@2.5R, 1.0R@3.5R, 2.0R@5R",
            "position_tiers": "breakeven@2R, 0.5R@3R, 1.5R@4R, 3.0R@6R",
            "after_hours_trail": False,
            "operator_trailing_switch": "supported via Telegram",
        },
    }

    # Risk action summary
    action_counts = {}
    for a in actions:
        at = a["action_type"]
        action_counts[at] = action_counts.get(at, 0) + 1
    result["risk_action_summary"] = action_counts

    out_dir = PROJECT_ROOT / "data" / "paper_trading"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stop_trailing_audit_latest.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def print_report(data):
    """Print human-readable stop audit report."""
    print("=" * 60)
    print("HARD-STOP TO TRAILING-STOP CONVERSION AUDIT")
    print(f"Generated: {data['timestamp']}")
    print("=" * 60)

    print(f"\nTotal closed trades:       {data['total_closed_trades']}")
    print(f"Total stop exits:          {data['total_stop_exits']}")
    print(f"  Hard stop exits:         {data['hard_stop_exits']}")
    print(f"  Trailing stop exits:     {data['trailing_stop_exits']}")
    print(f"Converted hard→trailing:   {data['converted_hard_to_trailing']} ({data['converted_pct']}%)")
    print(f"Hard stop only:            {data['hard_stop_only_pct']}%")
    print(f"No stop data:              {data['no_stop_data']}")

    print(f"\nRisk Action Summary:")
    for action, count in sorted(data["risk_action_summary"].items(), key=lambda x: -x[1]):
        print(f"  {action}: {count}")

    print(f"\nStop Exit Details:")
    for s in data["stop_exits_detail"]:
        print(f"  #{s['trade_id']} {s['symbol']:6s} {s['strategy']:25s} type={s['stop_type']:8s} pnl=${s['pnl'] or 0:>7.2f} r={s['r_multiple'] or 0:>5.2f} mfe={s['mfe'] or 0:>5.1f}%")

    if data["trailing_conversions"]:
        print(f"\nTrailing Conversions:")
        for c in data["trailing_conversions"]:
            print(f"  #{c['trade_id']} {c['symbol']:6s} {c['strategy']:25s} {c['conversion_action']} adjustments={c['total_adjustments']} pnl=${c['pnl'] or 0:.2f}")

    print(f"\nAlgorithm: {data['algorithm']['name']}")
    print(f"  Trigger: {data['algorithm']['trigger']}")
    print(f"  After-hours trail: {data['algorithm']['after_hours_trail']}")
    print()


if __name__ == "__main__":
    data = audit()
    if "--json" in sys.argv:
        print(json.dumps(data, indent=2, default=str))
    else:
        print_report(data)
    print(f"Written to: data/paper_trading/stop_trailing_audit_latest.json")
