#!/usr/bin/env python3
"""
Learning Effectiveness Metrics — measures whether shadow learning
recommendations would have improved candidate decisions.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def compute_effectiveness():
    """Compute learning effectiveness metrics."""
    from strategy_learning_shadow_scorer import shadow_score
    from generate_candidate_decision_lineage import generate_lineage
    from validate_journal_learning_fields import validate

    shadow = shadow_score()
    lineage = generate_lineage()
    journal = validate()

    # Loop closure metrics
    total_candidates = shadow["candidates_scored"]
    with_lineage = lineage["with_learning_links"]
    lineage_pct = round(100 * with_lineage / max(total_candidates, 1), 1)

    # Shadow recommendation summary
    penalized = shadow["penalized"]
    boosted = shadow["boosted"]
    unchanged = shadow["unchanged"]

    # Journal completeness
    journal_fields = journal["fields"]
    journal_pct = round(sum(f["pct"] for f in journal_fields.values()) / max(len(journal_fields), 1), 1)
    hold_time_pct = journal_fields.get("hold_time_min", {}).get("pct", 0)
    exit_reason_pct = journal_fields.get("exit_reason", {}).get("pct", 0)

    # Strategy-level analysis
    strategy_deltas = {}
    for r in shadow["results"]:
        sid = r.get("strategy", "unknown")
        if sid not in strategy_deltas:
            strategy_deltas[sid] = {"count": 0, "total_delta": 0, "candidates": []}
        strategy_deltas[sid]["count"] += 1
        strategy_deltas[sid]["total_delta"] += r["delta"]
        strategy_deltas[sid]["candidates"].append(r["symbol"])

    # Learning proven?
    sample_sufficient = journal["total"] >= 20
    loop_closed_pct = lineage_pct  # % of candidates with learning links
    learning_active = penalized + boosted > 0

    proven = sample_sufficient and loop_closed_pct >= 50 and learning_active
    luck_risk = "HIGH" if journal["total"] < 15 else "MEDIUM" if journal["total"] < 30 else "LOW"

    return {
        "timestamp": datetime.now().isoformat(),
        "learning_proven_beyond_luck": proven,
        "evidence_strength": "WEAK" if not proven else "MODERATE",
        "luck_risk": luck_risk,
        "sample_size": journal["total"],
        "sample_sufficient": sample_sufficient,
        "loop_closed_pct": loop_closed_pct,
        "candidates_with_lineage": with_lineage,
        "candidates_total": total_candidates,
        "shadow_penalized": penalized,
        "shadow_boosted": boosted,
        "shadow_unchanged": unchanged,
        "journal_completeness_pct": journal_pct,
        "hold_time_completeness_pct": hold_time_pct,
        "exit_reason_completeness_pct": exit_reason_pct,
        "stop_geometry_defects": journal["stop_defects"],
        "strategy_deltas": {k: {"count": v["count"], "avg_delta": round(v["total_delta"] / max(v["count"], 1), 1)}
                           for k, v in strategy_deltas.items() if v["total_delta"] != 0},
        "recommendations_used_in_live_scoring": False,  # NOT YET
        "shadow_vs_actual_validated": False,  # NOT YET — need outcome data
        "not_live": True,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    m = compute_effectiveness()
    print(f"Learning Effectiveness Metrics")
    print(f"  Learning proven: {m['learning_proven_beyond_luck']}")
    print(f"  Evidence strength: {m['evidence_strength']}")
    print(f"  Luck risk: {m['luck_risk']}")
    print(f"  Sample size: {m['sample_size']} (sufficient: {m['sample_sufficient']})")
    print(f"  Loop closed: {m['loop_closed_pct']}%")
    print(f"  Shadow: {m['shadow_penalized']} penalized, {m['shadow_boosted']} boosted, {m['shadow_unchanged']} unchanged")
    print(f"  Journal completeness: {m['journal_completeness_pct']}%")
    print(f"  Hold time: {m['hold_time_completeness_pct']}%")
    print(f"  Stop defects: {m['stop_geometry_defects']}")
    print(f"  Recommendations in live scoring: {m['recommendations_used_in_live_scoring']}")
    if m["strategy_deltas"]:
        print(f"\n  Strategy deltas:")
        for k, v in sorted(m["strategy_deltas"].items(), key=lambda x: x[1]["avg_delta"]):
            print(f"    {k}: avg delta {v['avg_delta']:+.1f} across {v['count']} candidates")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(m, indent=2, default=str))
        print(f"\nWritten to {args.json_out}")
