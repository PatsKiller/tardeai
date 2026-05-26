#!/usr/bin/env python3
"""report_strategy_architecture_diagnostic.py — Architecture health diagnostic.

Read-only. No mutations. Surfaces all STRAT-ARCH-1 findings in one report.

Usage:
    .venv/bin/python scripts/report_strategy_architecture_diagnostic.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def main():
    p = argparse.ArgumentParser(description="Strategy architecture diagnostic (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # Load strategy configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception:
        configs = {}

    # Classify strategies
    zero_criteria = []
    low_criteria = []
    by_family = {}
    unused_weights = []

    for sid, cfg in configs.items():
        ec = cfg.get("entry_criteria", [])
        tc = cfg.get("timeframe_class", "UNKNOWN")
        sw = cfg.get("scoring_weights", {})
        bucket = cfg.get("freshness", {}).get("bucket", "UNKNOWN")

        by_family.setdefault(tc, []).append(sid)
        if len(ec) == 0:
            zero_criteria.append(sid)
        elif len(ec) <= 2:
            low_criteria.append(sid)
        if sw:
            unused_weights.append(sid)

    # Score range analysis
    score_ranges = {}
    for sid, cfg in configs.items():
        ec = len(cfg.get("entry_criteria", []))
        max_score = ec * 10 + 15 + 10 + 10  # criteria + rvol + price + catalyst
        score_ranges[sid] = {"criteria": ec, "max_possible": max_score}

    # Findings
    findings = {
        "zero_criteria_strategies": zero_criteria,
        "low_criteria_strategies": low_criteria,
        "unused_scoring_weights": len(unused_weights),
        "families": {k: len(v) for k, v in by_family.items()},
        "score_ranges": score_ranges,
        "total_strategies": len(configs),
        "gaps_identified": {
            "Q-1": "No proactive quote refresh",
            "Q-2": "No quote quality score",
            "Q-3": "No provider fallback alerting",
            "R-1": "Flat scoring without strategy specificity",
            "R-2": "No family-level gating",
            "R-3": "Primary strategy override hides mismatch",
            "R-4": "No score normalization",
            "R-5": "YAML scoring_weights unused by router",
            "T-1": f"{len(zero_criteria)} strategies with zero criteria",
            "E-1": "No pre-proposal evidence score",
            "F-1": "Screener run health naming mismatch",
            "F-2": "Most runs underfilled",
            "F-3": "No screener-to-outcome tracking",
        },
        "p0_items": ["R-5 Wire YAML weights", "R-2 Family gating", "Q-1 Quote refresh", "F-1 Naming fix"],
        "p1_items": ["R-1 Weighted scoring", "R-3 Mismatch blocker", "T-1 Add criteria", "E-1 Evidence score", "F-3 Conversion funnel"],
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "human_review_only": True,
    }

    if args.verbose:
        print(f"Strategy Architecture Diagnostic — {len(configs)} strategies")
        print(f"  Zero criteria: {len(zero_criteria)} ({', '.join(zero_criteria[:5])}...)")
        print(f"  Unused YAML scoring_weights: {len(unused_weights)}")
        print(f"  Families: {findings['families']}")
        print(f"  P0 gaps: {findings['p0_items']}")
        print(f"  P1 gaps: {findings['p1_items']}")
        print(f"\n  Score ranges (criteria x10 + bonuses):")
        for sid, sr in sorted(score_ranges.items(), key=lambda x: -x[1]["max_possible"]):
            print(f"    {sid:35s} criteria={sr['criteria']:2d} max={sr['max_possible']:3d}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Strategy Architecture Diagnostic\n",
              f"Strategies: {len(configs)} | Zero criteria: {len(zero_criteria)} | Gaps: {len(findings['gaps_identified'])}\n",
              "## Score Ranges\n",
              "| Strategy | Criteria | Max Score |", "|----------|----------|-----------|"]
        for sid, sr in sorted(score_ranges.items(), key=lambda x: -x[1]["max_possible"]):
            md.append(f"| {sid} | {sr['criteria']} | {sr['max_possible']} |")
        md.append(f"\n## P0 Priorities\n")
        for item in findings["p0_items"]:
            md.append(f"- {item}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
