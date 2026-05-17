#!/usr/bin/env python3
"""
patch_screeners_yaml.py
=======================
Patches assets/screeners.yaml to:
  1. Lower min_score thresholds on income/position-strategy screeners
  2. Add new screeners that feed underused strategies:
       - quality_pullback     -> fib_retracement_bounce + income_add
       - oversold_quality     -> recovery_watch + tax_loss_harvest candidates
       - dividend_value_pullback -> dividend_growth_compounder + income_add
       - post_earnings_gappers   -> earnings_post_momentum
       - sector_leadership_rs    -> sector_rotation

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/patch_screeners_yaml.py --dry-run
    python3 scripts/patch_screeners_yaml.py --apply

Author: Trade AI v12 Session 33 patch package
Date: 2026-05-13
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ERROR: ruamel.yaml not installed. Run: pip install ruamel.yaml --break-system-packages")
    sys.exit(1)


def make_yaml():
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


# -----------------------------------------------------------------------------
# New screeners to add — adapt the Finviz URL params to your existing pattern
# -----------------------------------------------------------------------------
# NOTE: The Finviz URL filter strings below are placeholders that follow
# Finviz's documented filter format. Adjust to match your Elite account's
# saved screeners if you prefer named screens. The KEY thing is the
# `strategies:` field — that's what the router uses to map candidates.

NEW_SCREENERS = {
    "quality_pullback": {
        "name": "quality_pullback",
        "description": "Quality names pulling back to 50-day EMA or 61.8% Fib — feeds fib_retracement_bounce and income_add",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=cap_midover,fa_div_high,fa_payoutratio_u80,sh_avgvol_o500,ta_sma50_pa,ta_sma200_pa,ta_rsi_30to50",
        "run_windows": ["1000", "1300", "1600"],
        "strategies": ["fib_retracement_bounce", "income_add", "swing_trade"],
        "min_score": 25,
        "max_results": 30,
    },
    "oversold_quality": {
        "name": "oversold_quality",
        "description": "Oversold quality names — feeds recovery_watch and tax_loss_harvest scanning",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=cap_midover,fa_roe_pos,ta_rsi_os30,ta_sma200_pa,sh_avgvol_o500",
        "run_windows": ["0900", "1500"],
        "strategies": ["recovery_watch", "tax_loss_harvest"],
        "min_score": 20,
        "max_results": 30,
    },
    "dividend_value_pullback": {
        "name": "dividend_value_pullback",
        "description": "Dividend aristocrats and kings on pullbacks — feeds dividend_growth_compounder and income_add",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=fa_div_pos,fa_payoutratio_u85,fa_divgrowth5y_o5,ta_rsi_30to50,sh_avgvol_o500",
        "run_windows": ["1000", "1400"],
        "strategies": ["dividend_growth_compounder", "income_add", "international_dividend"],
        "min_score": 25,
        "max_results": 30,
    },
    "post_earnings_gappers": {
        "name": "post_earnings_gappers",
        "description": "Stocks gapping up post-earnings — feeds earnings_post_momentum",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=earningsdate_yesterday,sh_avgvol_o500,sh_curvol_o2000,ta_gap_u5",
        "run_windows": ["0930", "1000", "1100"],
        "strategies": ["earnings_post_momentum", "swing_breakout"],
        "min_score": 30,
        "max_results": 20,
    },
    "sector_leadership_rs": {
        "name": "sector_leadership_rs",
        "description": "Sector ETFs ranked by 5-day relative strength vs SPY — feeds sector_rotation",
        "url": "https://elite.finviz.com/screener.ashx?v=152&t=XLF,XLE,XLK,XLV,XLI,XLU,XLP,XLB,XLRE,XLC,XLY",
        "run_windows": ["1000", "1500"],
        "strategies": ["sector_rotation"],
        "min_score": 20,
        "max_results": 11,
    },
    "covered_call_candidates": {
        "name": "covered_call_candidates",
        "description": "Established holdings with elevated IV rank — feeds covered_call_income",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=cap_midover,sh_opt_optionshort,sh_avgvol_o1000",
        "run_windows": ["1100"],
        "strategies": ["covered_call_income"],
        "min_score": 25,
        "max_results": 20,
        "requires_existing_position": True,
    },
    "speculative_growth_breakouts": {
        "name": "speculative_growth_breakouts",
        "description": "Small/mid-cap revenue growers with momentum — feeds speculative_growth",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=cap_smallover,fa_salesqoq_o20,sh_relvol_o2,ta_perf_4w20o,ta_rsi_50to70",
        "run_windows": ["1000", "1400"],
        "strategies": ["speculative_growth", "swing_breakout"],
        "min_score": 35,
        "max_results": 20,
    },
    "defensive_quality": {
        "name": "defensive_quality",
        "description": "Low-beta dividend payers and defensive names — feeds bond_income alternatives and reit_income",
        "url": "https://elite.finviz.com/screener.ashx?v=152&f=fa_div_high,fa_payoutratio_u85,ta_beta_u1,sec_realestate,sec_utilities,sec_consumerdefensive",
        "run_windows": ["1100", "1500"],
        "strategies": ["reit_income", "international_dividend", "dividend_growth_compounder"],
        "min_score": 25,
        "max_results": 20,
    },
}


# Existing screeners that should have min_score lowered for income/position strategies
SCORE_REDUCTIONS = {
    # screener_name : new_min_score
    "income_screen": 25,
    "dividend_aristocrats": 25,
    "high_yield_bdc": 25,
    "reit_screen": 25,
    "bond_screen": 20,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--screeners-file", default="assets/screeners.yaml")
    parser.add_argument("--backup-root", default="backups")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    screeners_path = Path(args.screeners_file)
    if not screeners_path.exists():
        print(f"ERROR: {screeners_path} not found")
        sys.exit(1)

    yaml = make_yaml()
    with open(screeners_path, "r") as f:
        data = yaml.load(f)

    if data is None:
        print(f"ERROR: {screeners_path} parsed as empty")
        sys.exit(1)

    # Detect the screener container — could be a list under 'screeners'/'screens'/'items',
    # a dict under 'screeners'/'screens', or a top-level dict of screeners.
    screener_list_key = None
    screener_dict_key = None
    for key in ("screeners", "screens", "items"):
        if key in data:
            if isinstance(data[key], list):
                screener_list_key = key
                break
            if isinstance(data[key], dict):
                screener_dict_key = key
                break

    if screener_list_key is None and screener_dict_key is None:
        # Maybe it's a top-level dict of screeners (no 'screeners:' wrapper)
        if isinstance(data, dict) and data and all(
            isinstance(v, dict) for v in data.values() if v is not None
        ):
            print("Detected: top-level dict of screeners")
            existing_names = set(data.keys())
            added = 0
            for name, spec in NEW_SCREENERS.items():
                if name in existing_names:
                    print(f"  Skip (exists): {name}")
                    continue
                data[name] = spec
                added += 1
                print(f"  + {name}")
            print(f"\nWould add {added} screeners")
        else:
            print("ERROR: cannot detect screeners structure in YAML")
            sys.exit(1)
    elif screener_dict_key is not None:
        print(f"Detected: nested dict under '{screener_dict_key}:' key")
        container = data[screener_dict_key]
        existing_names = set(container.keys())
        added = 0
        for name, spec in NEW_SCREENERS.items():
            if name in existing_names:
                print(f"  Skip (exists): {name}")
                continue
            # Strip 'name' field for dict-keyed form (the key IS the name)
            spec_copy = {k: v for k, v in spec.items() if k != "name"}
            container[name] = spec_copy
            added += 1
            print(f"  + {name}")
        print(f"\nWould add {added} screeners")

        # Apply score reductions
        for screen_name, s in container.items():
            if not isinstance(s, dict):
                continue
            if screen_name in SCORE_REDUCTIONS:
                old_score = s.get("min_score")
                new_score = SCORE_REDUCTIONS[screen_name]
                if old_score != new_score:
                    s["min_score"] = new_score
                    print(f"  ~ {screen_name}: min_score {old_score} -> {new_score}")
    else:
        existing_names = {s.get("name") for s in data[screener_list_key] if isinstance(s, dict)}
        added = 0
        for name, spec in NEW_SCREENERS.items():
            if name in existing_names:
                print(f"  Skip (exists): {name}")
                continue
            data[screener_list_key].append(spec)
            added += 1
            print(f"  + {name}")
        print(f"\nWould add {added} screeners")

        # Apply score reductions
        for s in data[screener_list_key]:
            if not isinstance(s, dict):
                continue
            name = s.get("name")
            if name in SCORE_REDUCTIONS:
                old_score = s.get("min_score")
                new_score = SCORE_REDUCTIONS[name]
                if old_score != new_score:
                    s["min_score"] = new_score
                    print(f"  ~ {name}: min_score {old_score} -> {new_score}")

    if args.apply:
        # Backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(args.backup_root) / f"screeners_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(screeners_path, backup_dir / screeners_path.name)
        print(f"\nBackup: {backup_dir / screeners_path.name}")

        with open(screeners_path, "w") as f:
            yaml.dump(data, f)
        print(f"Updated: {screeners_path}")
    else:
        print("\nDRY-RUN — re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
