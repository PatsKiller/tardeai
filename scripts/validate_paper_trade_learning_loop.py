#!/usr/bin/env python3
"""Validate closed-loop learning for every closed paper trade.

Usage:
    python scripts/validate_paper_trade_learning_loop.py [--json]

Output:
    data/learning/paper_trade_loop_validation_latest.json
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from db_adapter import _execute


def _q(sql, **kw):
    return _execute(sql, fetch=kw.get("fetch", "all")) or ([] if kw.get("fetch", "all") == "all" else {})


def validate():
    """Check every closed paper trade for loop completeness."""
    now = datetime.now(timezone.utc).isoformat()

    # Get all closed trades
    trades = _q("""
        SELECT id, symbol, strategy_id, entry_price, exit_price, stop_loss, target_1,
               exit_reason, close_reason, pnl, pnl_pct, r_multiple,
               hold_time_min, dollar_size, dollar_risk,
               catalyst_at_entry, market_regime, vix_at_entry,
               max_adverse_excursion, max_favorable_excursion,
               post_trade_analyzed, broker_order_id, proposal_id, backtest_quality,
               created_at::text, closed_at::text
        FROM paper_trades WHERE status='closed' ORDER BY id
    """)

    # Preload linkage data
    thesis_ids = set()
    for r in _q("SELECT paper_trade_id FROM trade_thesis_outcomes WHERE paper_trade_id IS NOT NULL"):
        thesis_ids.add(r["paper_trade_id"])

    outcome_ids = set()
    for r in _q("SELECT paper_trade_id FROM paper_trade_outcome_analytics WHERE paper_trade_id IS NOT NULL"):
        outcome_ids.add(r["paper_trade_id"])

    hermes_ids = set()
    for r in _q("SELECT related_trade_id FROM hermes_research_intelligence WHERE related_trade_id IS NOT NULL"):
        hermes_ids.add(r["related_trade_id"])

    analysis_ids = set()
    for r in _q("SELECT paper_trade_id FROM paper_trade_analysis WHERE paper_trade_id IS NOT NULL"):
        analysis_ids.add(r["paper_trade_id"])

    multi_review_ids = set()
    for r in _q("SELECT paper_trade_id FROM paper_trade_multi_reviews WHERE paper_trade_id IS NOT NULL"):
        multi_review_ids.add(r["paper_trade_id"])

    lesson_strategies = set()
    for r in _q("SELECT DISTINCT strategy_id FROM trade_lesson_memory WHERE strategy_id IS NOT NULL"):
        lesson_strategies.add(r["strategy_id"])

    results = []
    totals = {
        "scanned": 0,
        "fully_closed_loop": 0,
        "partially_closed_loop": 0,
        "broken_loop": 0,
        "missing_journal": 0,
        "missing_exit_reason": 0,
        "missing_hold_time": 0,
        "missing_pnl": 0,
        "missing_exit_price": 0,
        "missing_r_multiple": 0,
        "missing_hermes": 0,
        "missing_backtest": 0,
        "missing_learning": 0,
        "missing_post_analysis": 0,
        "missing_outcome_analytics": 0,
        "missing_thesis": 0,
        "missing_catalyst": 0,
    }

    for t in trades:
        tid = t["id"]
        totals["scanned"] += 1

        checks = {}

        # Core trade data
        checks["has_strategy"] = bool(t["strategy_id"])
        checks["has_entry_price"] = t["entry_price"] is not None
        checks["has_exit_price"] = t["exit_price"] is not None
        checks["has_exit_reason"] = bool(t["exit_reason"])
        checks["has_stop_loss"] = t["stop_loss"] is not None
        checks["has_target"] = t["target_1"] is not None
        checks["has_pnl"] = t["pnl"] is not None
        checks["has_hold_time"] = t["hold_time_min"] is not None and t["hold_time_min"] > 0
        checks["has_r_multiple"] = t["r_multiple"] is not None
        checks["has_dollar_size"] = t["dollar_size"] is not None
        checks["has_catalyst"] = bool(t["catalyst_at_entry"])
        checks["has_regime"] = bool(t["market_regime"])
        checks["has_mae"] = t["max_adverse_excursion"] is not None
        checks["has_mfe"] = t["max_favorable_excursion"] is not None

        # Linkage checks
        checks["has_thesis_outcome"] = tid in thesis_ids
        checks["has_outcome_analytics"] = tid in outcome_ids
        checks["has_hermes_audit"] = tid in hermes_ids
        checks["has_post_analysis"] = bool(t["post_trade_analyzed"])
        checks["has_backtest_quality"] = bool(t["backtest_quality"])
        checks["has_learning_linkage"] = t["strategy_id"] in lesson_strategies if t["strategy_id"] else False
        checks["has_multi_review"] = tid in multi_review_ids

        # Score
        critical_fields = ["has_strategy", "has_entry_price", "has_exit_price", "has_exit_reason",
                           "has_stop_loss", "has_pnl", "has_hold_time", "has_r_multiple"]
        linkage_fields = ["has_thesis_outcome", "has_outcome_analytics", "has_hermes_audit",
                          "has_post_analysis", "has_backtest_quality", "has_learning_linkage"]

        critical_score = sum(1 for f in critical_fields if checks[f]) / len(critical_fields) * 100
        linkage_score = sum(1 for f in linkage_fields if checks[f]) / len(linkage_fields) * 100
        total_score = (critical_score * 0.6 + linkage_score * 0.4)

        if total_score >= 90:
            loop_status = "FULLY_CLOSED"
            totals["fully_closed_loop"] += 1
        elif total_score >= 50:
            loop_status = "PARTIALLY_CLOSED"
            totals["partially_closed_loop"] += 1
        else:
            loop_status = "BROKEN"
            totals["broken_loop"] += 1

        # Count missing
        if not checks["has_thesis_outcome"]:
            totals["missing_thesis"] += 1
        if not checks["has_exit_reason"]:
            totals["missing_exit_reason"] += 1
        if not checks["has_hold_time"]:
            totals["missing_hold_time"] += 1
        if not checks["has_pnl"]:
            totals["missing_pnl"] += 1
        if not checks["has_exit_price"]:
            totals["missing_exit_price"] += 1
        if not checks["has_r_multiple"]:
            totals["missing_r_multiple"] += 1
        if not checks["has_hermes_audit"]:
            totals["missing_hermes"] += 1
        if not checks["has_backtest_quality"]:
            totals["missing_backtest"] += 1
        if not checks["has_learning_linkage"]:
            totals["missing_learning"] += 1
        if not checks["has_post_analysis"]:
            totals["missing_post_analysis"] += 1
        if not checks["has_outcome_analytics"]:
            totals["missing_outcome_analytics"] += 1
        if not checks["has_catalyst"]:
            totals["missing_catalyst"] += 1

        results.append({
            "trade_id": tid,
            "symbol": t["symbol"],
            "strategy": t["strategy_id"],
            "loop_status": loop_status,
            "critical_score": round(critical_score, 1),
            "linkage_score": round(linkage_score, 1),
            "total_score": round(total_score, 1),
            "checks": checks,
        })

    scanned = totals["scanned"] or 1
    output = {
        "timestamp": now,
        "mode": "PAPER_ONLY",
        "trades_scanned": totals["scanned"],
        "fully_closed_loop": totals["fully_closed_loop"],
        "partially_closed_loop": totals["partially_closed_loop"],
        "broken_loop": totals["broken_loop"],
        "loop_completeness_pct": round(totals["fully_closed_loop"] / scanned * 100, 1),
        "missing_summary": {
            "exit_reason": totals["missing_exit_reason"],
            "hold_time": totals["missing_hold_time"],
            "pnl": totals["missing_pnl"],
            "exit_price": totals["missing_exit_price"],
            "r_multiple": totals["missing_r_multiple"],
            "thesis_outcome": totals["missing_thesis"],
            "outcome_analytics": totals["missing_outcome_analytics"],
            "hermes_audit": totals["missing_hermes"],
            "backtest_quality": totals["missing_backtest"],
            "post_analysis": totals["missing_post_analysis"],
            "learning_linkage": totals["missing_learning"],
            "catalyst": totals["missing_catalyst"],
        },
        "trades": results,
    }

    out_dir = PROJECT_ROOT / "data" / "learning"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "paper_trade_loop_validation_latest.json").write_text(json.dumps(output, indent=2, default=str))
    return output


def print_report(data):
    """Print human-readable validation report."""
    print("=" * 60)
    print("PAPER TRADE CLOSED-LOOP VALIDATION REPORT")
    print(f"Generated: {data['timestamp']}")
    print("=" * 60)

    print(f"\nTrades scanned:          {data['trades_scanned']}")
    print(f"Fully closed-loop:       {data['fully_closed_loop']}")
    print(f"Partially closed-loop:   {data['partially_closed_loop']}")
    print(f"Broken loop:             {data['broken_loop']}")
    print(f"Loop completeness:       {data['loop_completeness_pct']}%")

    print(f"\nMissing Fields:")
    for field, count in sorted(data["missing_summary"].items(), key=lambda x: -x[1]):
        pct = round(count / max(data["trades_scanned"], 1) * 100, 1)
        bar = "#" * int((data["trades_scanned"] - count) / max(data["trades_scanned"], 1) * 20)
        bar += "." * (20 - len(bar))
        print(f"  {field:25s} [{bar}] {count}/{data['trades_scanned']} missing ({pct}%)")

    print(f"\nPer-Trade Detail:")
    for t in data["trades"]:
        icon = "+" if t["loop_status"] == "FULLY_CLOSED" else "~" if t["loop_status"] == "PARTIALLY_CLOSED" else "X"
        print(f"  [{icon}] #{t['trade_id']:3d} {t['symbol']:6s} {t['strategy']:25s} score={t['total_score']:5.1f} {t['loop_status']}")
    print()


if __name__ == "__main__":
    data = validate()
    if "--json" in sys.argv:
        print(json.dumps(data, indent=2, default=str))
    else:
        print_report(data)
    print(f"Written to: data/learning/paper_trade_loop_validation_latest.json")
