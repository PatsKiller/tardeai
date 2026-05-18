#!/usr/bin/env python3
"""report_yaml_scoring_weights_inventory.py — Inventory all strategy YAML scoring_weights.

Read-only. No YAML mutation.

Usage:
    .venv/bin/python scripts/report_yaml_scoring_weights_inventory.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def main():
    p = argparse.ArgumentParser(description="YAML scoring weights inventory (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception:
        configs = {}

    strategies = []
    for sid, cfg in sorted(configs.items()):
        sw = cfg.get("scoring_weights") or {}
        ec = cfg.get("entry_criteria") or []
        total_weight = sum(v for v in sw.values() if isinstance(v, (int, float)))
        strategies.append({
            "strategy_id": sid,
            "has_scoring_weights": bool(sw),
            "weight_keys": list(sw.keys()) if sw else [],
            "weight_values": {k: v for k, v in sw.items() if isinstance(v, (int, float))},
            "total_weight": total_weight,
            "entry_criteria_count": len(ec),
            "fallback_required": not bool(sw),
        })

    has_weights = len([s for s in strategies if s["has_scoring_weights"]])
    no_weights = len([s for s in strategies if not s["has_scoring_weights"]])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_strategies": len(strategies),
        "with_scoring_weights": has_weights,
        "without_scoring_weights": no_weights,
        "strategies": strategies,
    }

    if args.verbose:
        print(f"YAML Scoring Weights Inventory — {len(strategies)} strategies ({has_weights} with weights, {no_weights} fallback)")
        for s in strategies:
            flag = "W" if s["has_scoring_weights"] else "F"
            print(f"  [{flag}] {s['strategy_id']:35s} total={s['total_weight']:>3} keys={s['weight_keys']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# YAML Scoring Weights Inventory\n",
              f"With weights: {has_weights} | Fallback: {no_weights}\n",
              "| Strategy | Has Weights | Total | Keys |", "|----------|-------------|-------|------|"]
        for s in strategies:
            md.append(f"| {s['strategy_id']} | {'Yes' if s['has_scoring_weights'] else 'No'} | {s['total_weight']} | {', '.join(s['weight_keys'][:5])} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
