#!/usr/bin/env python3
"""
Generate decision lineage for each candidate showing what learning
influenced its shadow score vs live score.
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


def generate_lineage():
    """Generate decision lineage from shadow scores + learning candidates."""
    from strategy_learning_shadow_scorer import shadow_score
    from extract_strategy_learning_candidates import extract_expanded_candidates

    shadow = shadow_score()
    learning = extract_expanded_candidates()

    # Build lesson index by strategy
    lessons_by_strategy = {}
    for i, lc in enumerate(learning):
        sid = lc.get("strategy")
        if sid:
            lessons_by_strategy.setdefault(sid, []).append({"lesson_id": i, **lc})

    lineage = []
    for r in shadow["results"]:
        sid = r.get("strategy", "unknown")
        lessons = lessons_by_strategy.get(sid, [])

        lineage.append({
            "symbol": r["symbol"],
            "strategy": sid,
            "base_score": r["original_score"],
            "shadow_score": r["shadow_score"],
            "delta": r["delta"],
            "decision": r.get("decision"),
            "has_learning_links": len(lessons) > 0,
            "lesson_count": len(lessons),
            "lesson_ids": [l["lesson_id"] for l in lessons],
            "lesson_types": list(set(l["lesson_type"] for l in lessons)),
            "lesson_summaries": [l["lesson_summary"][:80] for l in lessons[:3]],
            "sample_size_warning": r.get("sample_size_warning", False),
            "lineage_explanation": _explain(r, lessons),
            "not_live_decision": True,
        })

    with_links = sum(1 for l in lineage if l["has_learning_links"])
    without_links = sum(1 for l in lineage if not l["has_learning_links"])

    return {
        "timestamp": datetime.now().isoformat(),
        "candidates_processed": len(lineage),
        "with_learning_links": with_links,
        "without_learning_links": without_links,
        "learning_candidates_total": len(learning),
        "lineage": lineage,
    }


def _explain(result, lessons):
    """Generate human-readable lineage explanation."""
    if not lessons:
        return f"No learning data affects {result['strategy']}. Score unchanged at {result['original_score']}."

    parts = []
    for l in lessons[:3]:
        parts.append(f"- {l['lesson_type']}: {l['lesson_summary'][:60]}")

    delta_text = f"Penalized {result['delta']}" if result['delta'] < 0 else f"Boosted +{result['delta']}" if result['delta'] > 0 else "No change"
    return f"{delta_text} ({result['original_score']}→{result['shadow_score']}) based on {len(lessons)} lesson(s):\n" + "\n".join(parts)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    output = generate_lineage()
    print(f"Decision Lineage")
    print(f"  Candidates: {output['candidates_processed']}")
    print(f"  With learning links: {output['with_learning_links']}")
    print(f"  Without learning links: {output['without_learning_links']}")
    print(f"\nSample lineage:")
    for l in output["lineage"][:5]:
        if l["delta"] != 0:
            print(f"  {l['symbol']:8s} {l['base_score']}→{l['shadow_score']} ({l['delta']:+d}) lessons={l['lesson_count']} types={l['lesson_types']}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(output, indent=2, default=str))
        print(f"\nWritten to {args.json_out}")
