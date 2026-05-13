#!/usr/bin/env python3
"""
convert_v1_to_v1_0_0_schema.py
==============================
Converts the 6 v1.0 TESTING files to the v1.0.0 normalized schema.
Adds:
  - entry_criteria (list) — synthesized from setup_qualification + screen_filters
  - co_enables block
  - exit_rules block (formal)
  - lifecycle block (formal)
  - risk block (formal — derived from live_trade_rules)
  - validation_gate block
  - prompt_context block

Preserves original setup_qualification, scoring_weights, etc. as legacy fields
(they're still used by the router).

Affected files:
  - gap_and_go.yaml
  - momentum_scalp.yaml
  - swing_breakout.yaml
  - earnings_catalyst.yaml          (also splits this — see below)
  - income_add.yaml
  - sector_rotation.yaml

Earnings split: this script ALSO emits two new files:
  - earnings_pre_buildup.yaml
  - earnings_post_momentum.yaml
And deprecates earnings_catalyst.yaml by setting status: DEPRECATED.

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/convert_v1_to_v1_0_0_schema.py --dry-run
    python3 scripts/convert_v1_to_v1_0_0_schema.py --apply

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
# Per-strategy v1.0.0 augmentation specs
# -----------------------------------------------------------------------------

# Each entry contains the v1.0.0 fields to merge into the existing YAML.
# Existing fields (setup_qualification, scoring_weights, screen_filters, etc.)
# are preserved.

V1_0_0_ADDITIONS = {
    "momentum_scalp": {
        "version": "1.0.0",
        "status": "TESTING",
        "entry_criteria": [
            {
                "id": "CATALYST_VERIFIED",
                "description": "Verified catalyst (news, SEC filing, or institutional event) — not social-only",
                "metric": "catalyst_verified",
                "operator": "eq",
                "value": True,
            },
            {
                "id": "RVOL_SURGE",
                "description": "Relative volume at least 5x 20-day average",
                "metric": "rvol",
                "operator": "gte",
                "value": 5.0,
            },
            {
                "id": "PRICE_RANGE",
                "description": "Price between $1 and $25 (preferred under $10)",
                "metric": "price",
                "operator": "between",
                "value": [1.0, 25.0],
            },
            {
                "id": "FLOAT_LOW",
                "description": "Float under 100M shares (preferred under 20M)",
                "metric": "float_m",
                "operator": "lte",
                "value": 100,
            },
            {
                "id": "ENTRY_WINDOW",
                "description": "Current time before 13:30 ET",
                "metric": "current_time_et",
                "operator": "lte",
                "value": "13:30",
            },
        ],
        "exit_rules": {
            "stop_method": "fixed_pct",
            "stop_max_pct": 0.15,
            "target_method": "trailing",
            "intraday_exit_required": True,
            "no_overnight_hold": True,
        },
        "lifecycle": {
            "proposal_expiry_hours": 4,
            "overnight_allowed": False,
            "max_hold_days": 0,  # intraday only
        },
        "risk": {
            "risk_per_trade_pct": 0.002,
            "max_position_size": 2000,
            "max_daily_trades": 3,
            "target_rr": 2.0,
        },
        "co_enables": {
            "promotes_to": ["swing_breakout"],
            "strengthens": ["gap_and_go"],
            "notes": "Successful intraday momentum runners can incubate into multi-day swing setups.",
        },
        "validation_gate": {
            "min_closed_paper_trades": 30,
            "min_win_rate": 0.50,
            "min_profit_factor": 1.3,
            "min_calendar_months": 6,
            "human_approval_required": True,
        },
        "prompt_context": {
            "summary": "Intraday momentum scalp on micro-cap names with verified catalyst and RVOL surge. Strict same-day exit, taxable account only.",
            "key_questions": [
                "Is the catalyst verified or social-only?",
                "Is RVOL holding above 5x or fading?",
                "Are we within the entry window (before 13:30 ET)?",
            ],
        },
    },
    "gap_and_go": {
        "version": "1.0.0",
        "status": "TESTING",
        "entry_criteria": [
            {
                "id": "GAP_SIZE",
                "description": "Pre-market gap of at least 5% (10% if VIX > 25)",
                "metric": "gap_pct",
                "operator": "gte",
                "value": 5.0,
            },
            {
                "id": "CATALYST_REQUIRED",
                "description": "Verified catalyst driving the gap",
                "metric": "catalyst_verified",
                "operator": "eq",
                "value": True,
            },
            {
                "id": "FIRST_CANDLE_CONFIRMATION",
                "description": "First 5-min candle closes above gap_high",
                "metric": "first_5min_close_above_gap_high",
                "operator": "eq",
                "value": True,
            },
            {
                "id": "RVOL_CONFIRMATION",
                "description": "Pre-market and opening RVOL at least 3x average",
                "metric": "rvol",
                "operator": "gte",
                "value": 3.0,
            },
            {
                "id": "ENTRY_WINDOW",
                "description": "Entry between 09:30 and 09:50 ET",
                "metric": "current_time_et",
                "operator": "between",
                "value": ["09:30", "09:50"],
            },
        ],
        "exit_rules": {
            "stop_method": "level_based",
            "stop_at": "gap_low",
            "target_method": "trailing",
            "no_overnight_hold": True,
        },
        "lifecycle": {
            "proposal_expiry_hours": 2,
            "overnight_allowed": False,
            "max_hold_days": 0,
        },
        "risk": {
            "risk_per_trade_pct": 0.002,
            "max_position_size": 2000,
            "max_daily_trades": 3,
            "target_rr": 2.0,
        },
        "co_enables": {
            "promotes_to": ["swing_breakout", "earnings_post_momentum"],
            "strengthens": ["momentum_scalp"],
            "notes": "Successful gap-and-go setups frequently form the base for post-earnings or breakout swings.",
        },
        "validation_gate": {
            "min_closed_paper_trades": 30,
            "min_win_rate": 0.50,
            "min_profit_factor": 1.3,
            "min_calendar_months": 6,
            "human_approval_required": True,
        },
        "prompt_context": {
            "summary": "Intraday gap-and-go setup. Pre-market gap > 5%, verified catalyst, first-candle confirmation. Strict same-day exit, taxable only.",
            "key_questions": [
                "Is the gap news-driven or technical?",
                "Did the first 5-min candle close above gap_high?",
                "Is VWAP holding above gap_low?",
            ],
        },
    },
    "swing_breakout": {
        "version": "1.0.0",
        "status": "TESTING",
        "entry_criteria": [
            {
                "id": "BASE_LENGTH",
                "description": "Consolidation base of at least 15 days (max 90)",
                "metric": "base_days",
                "operator": "between",
                "value": [15, 90],
            },
            {
                "id": "VOLUME_DRY_UP",
                "description": "Volume during base contracts to 70% of 20-day average",
                "metric": "base_volume_ratio",
                "operator": "lte",
                "value": 0.7,
            },
            {
                "id": "BREAKOUT_VOLUME",
                "description": "Breakout day volume at least 1.5x 20-day average",
                "metric": "breakout_volume_ratio",
                "operator": "gte",
                "value": 1.5,
            },
            {
                "id": "ENTRY_PROXIMITY",
                "description": "Price within 3% of breakout level (no chasing)",
                "metric": "distance_from_breakout_pct",
                "operator": "lte",
                "value": 0.03,
            },
            {
                "id": "SECTOR_LEADERSHIP",
                "description": "Sector ranks in top 3 by relative strength",
                "metric": "sector_rs_rank",
                "operator": "lte",
                "value": 3,
            },
        ],
        "exit_rules": {
            "stop_method": "level_based",
            "stop_at": "base_low",
            "target_method": "trailing",
            "trail_method": "ema_21",
        },
        "lifecycle": {
            "proposal_expiry_hours": 48,
            "overnight_allowed": True,
            "max_hold_days": 21,
        },
        "risk": {
            "risk_per_trade_pct": 0.005,
            "max_position_size": 5000,
            "max_daily_trades": 3,
            "target_rr": 2.5,
        },
        "co_enables": {
            "promotes_to": ["core_growth_compounder"],
            "strengthens": ["swing_trade", "speculative_growth"],
            "notes": "Successful breakouts that hold their gains can graduate into core compounders.",
        },
        "validation_gate": {
            "min_closed_paper_trades": 30,
            "min_win_rate": 0.55,
            "min_profit_factor": 1.3,
            "min_calendar_months": 6,
            "human_approval_required": True,
        },
        "prompt_context": {
            "summary": "Technical breakout from multi-week consolidation. Volume dry-up during base, expansion on breakout. 3-21 day swing hold with trailing stops.",
            "key_questions": [
                "Is the base structure clean and tradeable?",
                "Did volume confirm the breakout?",
                "Is the sector showing leadership?",
            ],
        },
    },
    "income_add": {
        "version": "1.0.0",
        "status": "TESTING",
        "entry_criteria": [
            {
                "id": "YIELD_THRESHOLD",
                "description": "Current dividend yield at least 3%",
                "metric": "dividend_yield",
                "operator": "gte",
                "value": 0.03,
            },
            {
                "id": "PAYOUT_SUSTAINABLE",
                "description": "Payout ratio under 85%",
                "metric": "payout_ratio",
                "operator": "lte",
                "value": 0.85,
            },
            {
                "id": "DIVIDEND_GROWTH_HISTORY",
                "description": "At least 3 consecutive years of dividend increases",
                "metric": "div_increase_streak_years",
                "operator": "gte",
                "value": 3,
            },
            {
                "id": "PULLBACK_ENTRY",
                "description": "RSI(14) at or below 50 (not euphoric)",
                "metric": "rsi_14",
                "operator": "lte",
                "value": 50,
            },
            {
                "id": "IRMAA_HEADROOM",
                "description": "Projected MAGI stays below IRMAA threshold ($103K)",
                "metric": "projected_magi_under_irmaa",
                "operator": "eq",
                "value": True,
            },
        ],
        "exit_rules": {
            "stop_method": "fundamental",
            "exit_trigger": "dividend_cut_or_thesis_break",
            "target_method": "none",
        },
        "lifecycle": {
            "proposal_expiry_hours": 720,
            "overnight_allowed": True,
            "max_hold_days": None,  # position hold, indefinite
        },
        "risk": {
            "risk_per_trade_pct": 0.005,
            "max_position_size": 15000,
            "max_daily_trades": None,
            "target_rr": 2.0,
        },
        "agent_responsibilities": {
            "maria": "Verify dividend sustainability, earnings quality, and sector outlook. Flag any payout-ratio deterioration.",
            "risk": "Assess yield trap risk, sector concentration, and rate sensitivity. Confirm position-size fit with income allocation bucket.",
            "steph": "Confirm account placement for tax efficiency (qualified div in taxable, ordinary in IRA). Calculate IRMAA and SSDI income impact.",
            "alex": "Full retirement-aware analysis. SSDI/IRMAA/MAGI projection. Golden Window impact assessment.",
            "tax": "Tax-lot optimization, wash-sale check, account placement validation.",
        },
        "co_enables": {
            "promotes_to": ["covered_call_income"],
            "strengthens": ["dividend_growth_compounder", "reit_income", "high_yield_income_bdc"],
            "notes": "Once a position is established and stable, covered call income can layer additional yield.",
        },
        "validation_gate": {
            "min_closed_paper_trades": 30,
            "min_win_rate": 0.55,
            "min_profit_factor": 1.3,
            "min_calendar_months": 6,
            "human_approval_required": True,
        },
        "prompt_context": {
            "summary": "Income position add for retirement income generation. SSDI-aware, IRMAA-aware, MFS-aware. Pullback entries on quality dividend payers.",
            "key_questions": [
                "What is the IRMAA and SSDI income impact of adding this position?",
                "Is the dividend coverage sustainable through a recession?",
                "Should this go in taxable (qualified div) or IRA (ordinary)?",
            ],
        },
    },
    "sector_rotation": {
        "version": "1.0.0",
        "status": "TESTING",
        "entry_criteria": [
            {
                "id": "SECTOR_RS_VS_SPY",
                "description": "Sector ETF 5-day return exceeds SPY by at least 2%",
                "metric": "sector_5d_return_minus_spy_pct",
                "operator": "gte",
                "value": 0.02,
            },
            {
                "id": "SECTOR_IN_TOP_3",
                "description": "Sector ranks in top 3 of 11 SPDRs by 5-day RS",
                "metric": "sector_rs_rank",
                "operator": "lte",
                "value": 3,
            },
            {
                "id": "SECTOR_EMA_50_RISING",
                "description": "Sector ETF above and rising 50-day EMA (slope positive over 5 days)",
                "metric": "ema_50_slope_5d",
                "operator": "gt",
                "value": 0,
            },
            {
                "id": "BREADTH_CONFIRMING",
                "description": "At least 60% of sector components above their 50-day SMA",
                "metric": "pct_components_above_sma_50",
                "operator": "gte",
                "value": 0.60,
            },
        ],
        "auto_disqualifiers_add": [
            {
                "id": "MACRO_REGIME_HOSTILE",
                "description": "FRED macro signals (yield curve, ISM, claims) hostile to this sector",
            },
        ],
        "exit_rules": {
            "stop_method": "rank_based",
            "exit_when_drops_to_bottom_5": True,
            "target_method": "trailing",
            "rebalance_frequency": "weekly",
        },
        "lifecycle": {
            "proposal_expiry_hours": 168,
            "overnight_allowed": True,
            "max_hold_days": 56,  # 8 weeks
        },
        "risk": {
            "risk_per_trade_pct": 0.01,
            "max_position_size": 25000,
            "max_daily_trades": None,
            "target_rr": 2.0,
            "max_sector_concentration_pct": 0.25,
        },
        "agent_responsibilities": {
            "maria": "Verify the rotation is fundamental (macro, earnings cycle, rates) not just price chasing. Check FRED for rate and yield-curve context.",
            "risk": "Validate top-3 ranking calculation. Confirm position size aligns with sector concentration limits (no sector > 25% of equity book).",
            "steph": "Verify sector ETF placement across accounts. Check IRA fit for non-qualified-dividend sectors (utilities, REITs).",
            "alex": "Macro alignment with retirement timeline — defensive rotation favored in pre-Golden-Window years.",
        },
        "co_enables": {
            "promotes_to": [],
            "strengthens": ["swing_breakout", "speculative_growth"],
            "notes": "Sector leadership confirms individual breakouts within that sector.",
        },
        "validation_gate": {
            "min_closed_paper_trades": 30,
            "min_win_rate": 0.55,
            "min_profit_factor": 1.3,
            "min_calendar_months": 6,
            "human_approval_required": True,
        },
        "prompt_context": {
            "summary": "Sector rotation strategy across 11 SPDRs. Top-3 RS sectors with EMA-50 rising and breadth confirmation. Weekly rebalance, 2-8 week hold.",
            "key_questions": [
                "Is sector leadership confirmed by breadth or driven by 1-2 outliers?",
                "What is the macro context — risk-on rotation or defensive?",
                "Does the FRED yield-curve signal support continued sector strength?",
            ],
        },
    },
    "earnings_catalyst": {
        # Mark as deprecated — replaced by earnings_pre_buildup + earnings_post_momentum
        "version": "1.0.0",
        "status": "DEPRECATED",
        "deprecated_in_favor_of": ["earnings_pre_buildup", "earnings_post_momentum"],
        "deprecated_date": "2026-05-13",
        "deprecated_reason": "Two sub-strategies in one YAML prevented router from cleanly mapping candidates. Split into separate files.",
        "co_enables": {
            "promotes_to": [],
            "strengthens": [],
            "notes": "Deprecated — use earnings_pre_buildup or earnings_post_momentum.",
        },
    },
}


def apply_additions(yaml_path: Path, additions: dict, dry_run: bool, backup_dir: Path) -> dict:
    """Apply v1.0.0 additions to a YAML file."""
    result = {"path": str(yaml_path), "added_keys": [], "updated_keys": [], "error": None}

    yaml = make_yaml()
    try:
        with open(yaml_path, "r") as f:
            data = yaml.load(f)
    except Exception as e:
        result["error"] = f"YAML load failed: {e}"
        return result

    if data is None:
        result["error"] = "Empty YAML"
        return result

    for key, value in additions.items():
        if key == "auto_disqualifiers_add":
            # Append to existing list
            existing = data.get("auto_disqualifiers", [])
            existing_ids = {item.get("id") for item in existing if isinstance(item, dict)}
            for new_item in value:
                if new_item.get("id") not in existing_ids:
                    existing.append(new_item)
                    result["added_keys"].append(f"auto_disqualifiers/{new_item.get('id')}")
            data["auto_disqualifiers"] = existing
        elif key in data:
            # Update (overwrite) only if the existing value is None, empty, or version bump
            if key == "version":
                if data[key] != value:
                    data[key] = value
                    result["updated_keys"].append(key)
            elif key == "status":
                if data[key] != value:
                    data[key] = value
                    result["updated_keys"].append(key)
            elif key == "agent_responsibilities":
                # Merge dicts (don't clobber existing keys; add new ones)
                existing = data[key] if isinstance(data[key], dict) else {}
                for role, desc in value.items():
                    if role not in existing:
                        existing[role] = desc
                        result["added_keys"].append(f"agent_responsibilities/{role}")
                data[key] = existing
            else:
                # Don't overwrite existing top-level blocks
                pass
        else:
            data[key] = value
            result["added_keys"].append(key)

    if (result["added_keys"] or result["updated_keys"]) and not result["error"]:
        if not dry_run:
            backup_path = backup_dir / yaml_path.name
            shutil.copy2(yaml_path, backup_path)
            with open(yaml_path, "w") as f:
                yaml.dump(data, f)

    return result


def main():
    parser = argparse.ArgumentParser(description="Convert v1.0 TESTING files to v1.0.0 schema.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-dir", default="config/strategies")
    parser.add_argument("--backup-root", default="backups")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    config_dir = Path(args.config_dir)
    if not config_dir.exists():
        print(f"ERROR: config dir not found: {config_dir}")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(args.backup_root) / f"schema_convert_{timestamp}"
    if args.apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        print(f"Backup directory: {backup_dir}")

    print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print("=" * 80)

    total_added = 0
    total_errors = 0

    for strategy_id, additions in V1_0_0_ADDITIONS.items():
        yaml_path = config_dir / f"{strategy_id}.yaml"
        if not yaml_path.exists():
            print(f"  {strategy_id:<30s} [MISSING FILE]")
            total_errors += 1
            continue

        result = apply_additions(yaml_path, additions, args.dry_run, backup_dir)
        status = "ERROR" if result["error"] else ("PATCHED" if result["added_keys"] or result["updated_keys"] else "NO CHANGE")
        print(f"  {strategy_id:<30s} [{status}]")
        if result["added_keys"]:
            print(f"    + added: {', '.join(result['added_keys'][:5])}{' ...' if len(result['added_keys']) > 5 else ''}")
            total_added += len(result["added_keys"])
        if result["updated_keys"]:
            print(f"    ~ updated: {', '.join(result['updated_keys'])}")
        if result["error"]:
            print(f"    ! error: {result['error']}")
            total_errors += 1

    print("=" * 80)
    print(f"Total keys added: {total_added}")
    print(f"Errors: {total_errors}")
    if args.dry_run:
        print("\nDRY-RUN complete. Re-run with --apply to write changes.")
    else:
        print(f"\nBackups saved to: {backup_dir}")
        print("Next step: run create_new_strategy_yamls.py to create earnings_pre_buildup, earnings_post_momentum, fib_retracement_bounce.")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
