#!/usr/bin/env python3
"""strategy_rule_adapter.py — Read-only adapter for strategy configs into backtestable rules.

Usage:
    .venv/bin/python scripts/strategy_rule_adapter.py --list-strategies --json
    .venv/bin/python scripts/strategy_rule_adapter.py --strategy momentum_scalp --describe --json
    .venv/bin/python scripts/strategy_rule_adapter.py --strategy momentum_scalp --validate --json
"""
import argparse, json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

STRATEGY_DIR = PROJECT_ROOT / "config" / "strategies"
SKIP_FILES = {"recommendation_schema.yaml", "strategy_schema.yaml", "shared_risk_rules.yaml"}


def load_strategy_configs():
    """Load all strategy YAML configs (read-only)."""
    configs = {}
    if not STRATEGY_DIR.exists():
        return configs
    try:
        import yaml
    except ImportError:
        return configs
    for f in sorted(STRATEGY_DIR.glob("*.yaml")):
        if f.name in SKIP_FILES:
            continue
        try:
            cfg = yaml.safe_load(f.read_text())
            if cfg and isinstance(cfg, dict):
                sid = cfg.get("strategy_id", f.stem)
                configs[sid] = {"file": str(f.name), "config": cfg}
        except Exception:
            pass
    return configs


def describe_strategy(strategy_id, configs):
    """Extract backtestable rule description from strategy config."""
    if strategy_id not in configs:
        return {"error": f"Strategy '{strategy_id}' not found"}
    cfg = configs[strategy_id]["config"]
    return {
        "strategy_id": strategy_id,
        "file": configs[strategy_id]["file"],
        "name": cfg.get("name", strategy_id),
        "category": cfg.get("category", "unknown"),
        "time_horizon": cfg.get("time_horizon", "unknown"),
        "min_score": cfg.get("min_score", cfg.get("scoring", {}).get("min_score")),
        "entry_filters": cfg.get("entry_filters", cfg.get("filters", {})),
        "stop_method": cfg.get("stop", cfg.get("risk", {}).get("stop_method")),
        "target_method": cfg.get("target", cfg.get("risk", {}).get("target_method")),
        "position_sizing": cfg.get("position_sizing", {}),
        "has_scoring_rules": "scoring" in cfg or "min_score" in cfg,
        "has_entry_filters": bool(cfg.get("entry_filters") or cfg.get("filters")),
        "has_risk_rules": bool(cfg.get("stop") or cfg.get("risk") or cfg.get("target")),
        "backtestable": True,  # all configs are testable at signal level
        "limitations": ["no intrabar OHLCV data", "scan-time price snapshots only",
                        "no real spread/volume tick data", "stop/target simulated from close prices"],
    }


def validate_strategy(strategy_id, configs):
    """Validate a strategy config is complete enough for backtesting."""
    desc = describe_strategy(strategy_id, configs)
    if "error" in desc:
        return desc
    issues = []
    if not desc["has_scoring_rules"]:
        issues.append("no_scoring_rules")
    if not desc["has_risk_rules"]:
        issues.append("no_risk_rules_defined")
    return {
        "strategy_id": strategy_id,
        "valid": len(issues) == 0,
        "issues": issues,
        "description": desc,
    }


def main():
    parser = argparse.ArgumentParser(description="Strategy Rule Adapter")
    parser.add_argument("--list-strategies", action="store_true")
    parser.add_argument("--strategy")
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    configs = load_strategy_configs()

    if args.list_strategies:
        strategies = [{"strategy_id": sid, "file": data["file"],
                       "name": data["config"].get("name", sid)}
                      for sid, data in configs.items()]
        if args.json:
            print(json.dumps(strategies, indent=2, default=str))
        else:
            for s in strategies:
                print(f"  {s['strategy_id']}: {s['name']} ({s['file']})")
        return

    if args.strategy and args.describe:
        desc = describe_strategy(args.strategy, configs)
        print(json.dumps(desc, indent=2, default=str) if args.json else str(desc))
    elif args.strategy and args.validate:
        result = validate_strategy(args.strategy, configs)
        print(json.dumps(result, indent=2, default=str) if args.json else str(result))


if __name__ == "__main__":
    main()
