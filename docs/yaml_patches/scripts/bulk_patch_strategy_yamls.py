#!/usr/bin/env python3
"""
bulk_patch_strategy_yamls.py
============================
Adds three missing blocks to all 20 strategy YAMLs in config/strategies/:
  - vix_rules
  - technical_indicators_required
  - performance_context

Idempotent: skips files that already have a given block.
Dry-run mode: --dry-run prints what would change without writing.
Backup: writes timestamped backups to backups/strategy_yaml_<ts>/ before modifying.

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/bulk_patch_strategy_yamls.py --dry-run
    python3 scripts/bulk_patch_strategy_yamls.py --apply

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
    from ruamel.yaml.comments import CommentedMap as OrderedDict
except ImportError:
    print("ERROR: ruamel.yaml not installed. Run: pip install ruamel.yaml --break-system-packages")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Configuration: per-strategy values
# -----------------------------------------------------------------------------

# VIX rules: per-strategy thresholds and behavior
VIX_RULES = {
    "momentum_scalp": {
        "max_vix_for_entry": 25,
        "elevated_vix_band": [22, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.5,
            "require_aplus_grade": True,
            "require_catalyst_verified": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": 40,
        "notes": "Micro-cap momentum is most vulnerable to VIX expansion — pause aggressively.",
    },
    "gap_and_go": {
        "max_vix_for_entry": 28,
        "elevated_vix_band": [25, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.5,
            "min_gap_pct_override": 10.0,
            "require_catalyst_verified": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Gap quality degrades in high VIX — require larger gaps and verified catalyst.",
    },
    "earnings_catalyst": {
        "max_vix_for_entry": 30,
        "elevated_vix_band": [25, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.6,
            "pause_pre_earnings_only": True,
            "post_earnings_still_allowed": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Pre-earnings buildup is fragile in high VIX; post-earnings momentum can still work.",
    },
    "swing_breakout": {
        "max_vix_for_entry": 32,
        "elevated_vix_band": [25, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
            "require_aplus_grade": True,
            "require_sector_top_3": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Breakouts in high VIX often fail — require best-of-breed setups only.",
    },
    "swing_trade": {
        "max_vix_for_entry": 32,
        "elevated_vix_band": [25, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
            "require_aplus_grade": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Trend-following degrades in regime shifts — tighten quality bar.",
    },
    "speculative_growth": {
        "max_vix_for_entry": 25,
        "elevated_vix_band": [22, 30],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.5,
            "require_aplus_grade": True,
            "require_revenue_growth_30pct": True,
        },
        "extreme_vix_threshold": 30,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": 35,
        "notes": "Speculative names are first to break in volatility — exit existing at VIX 35.",
    },
    "sector_rotation": {
        "max_vix_for_entry": 40,
        "elevated_vix_band": [30, 40],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
            "top_n_sectors_override": 1,
            "prefer_defensive_sectors": True,
        },
        "extreme_vix_threshold": 40,
        "extreme_vix_action": "rotate_to_defensives",
        "exit_holdings_at_vix": None,
        "notes": "VIX spikes drive defensive rotation — narrow to top-1 sector and prefer XLP/XLU.",
    },
    "recovery_watch": {
        "max_vix_for_entry": 45,
        "elevated_vix_band": [30, 50],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "accelerate_screening": True,
            "expand_universe": True,
        },
        "extreme_vix_threshold": 50,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "VIX spikes are recovery_watch's bread and butter — accelerate, don't pause.",
    },
    "income_add": {
        "max_vix_for_entry": 50,
        "elevated_vix_band": [30, 50],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "prefer_quality_pullbacks": True,
            "accelerate_screening": True,
        },
        "extreme_vix_threshold": 50,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "High VIX creates pullback entry opportunities in quality income names.",
    },
    "dividend_growth_compounder": {
        "max_vix_for_entry": 50,
        "elevated_vix_band": [30, 50],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "accelerate_screening": True,
        },
        "extreme_vix_threshold": 50,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Aristocrat pullbacks in volatility are textbook entry zones.",
    },
    "high_yield_income_bdc": {
        "max_vix_for_entry": 35,
        "elevated_vix_band": [25, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.5,
            "require_nav_premium_under_1_0": True,
            "require_coverage_95pct": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "BDC NAVs degrade with credit spreads — pause when spreads widen.",
    },
    "reit_income": {
        "max_vix_for_entry": 40,
        "elevated_vix_band": [30, 40],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.5,
            "prefer_industrial_residential": True,
            "avoid_office_retail": True,
        },
        "extreme_vix_threshold": 40,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Rate-sensitive — pause until 10y stabilizes.",
    },
    "bond_income": {
        "max_vix_for_entry": None,
        "elevated_vix_band": [30, 50],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "accelerate_screening": True,
            "prefer_treasuries": True,
        },
        "extreme_vix_threshold": None,
        "extreme_vix_action": "no_restriction",
        "exit_holdings_at_vix": None,
        "notes": "Bonds are always eligible — VIX spikes often coincide with bond rallies.",
    },
    "international_dividend": {
        "max_vix_for_entry": 40,
        "elevated_vix_band": [30, 40],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
        },
        "extreme_vix_threshold": 40,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Currency volatility compounds equity volatility in international names.",
    },
    "core_index": {
        "max_vix_for_entry": 50,
        "elevated_vix_band": [30, 50],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "accelerate_screening": True,
        },
        "extreme_vix_threshold": 50,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Core index DCA accelerates during VIX spikes — buy the dip mechanism.",
    },
    "core_growth_compounder": {
        "max_vix_for_entry": 45,
        "elevated_vix_band": [25, 40],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "require_pullback_to_ema_50": True,
        },
        "extreme_vix_threshold": 45,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Quality compounders pull back hardest in volatility — best entry zone.",
    },
    "covered_call_income": {
        "max_vix_for_entry": 30,
        "elevated_vix_band": [22, 30],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
            "shorter_dte_30_max": True,
            "lower_delta_target_0_15": True,
        },
        "extreme_vix_threshold": 30,
        "extreme_vix_action": "pause_new_writes",
        "exit_holdings_at_vix": None,
        "notes": "IV is rich in high VIX but assignment risk also rises — shorter DTE, lower delta.",
    },
    "defense_thesis": {
        "max_vix_for_entry": 40,
        "elevated_vix_band": [25, 40],
        "elevated_vix_changes": {
            "position_size_multiplier": 1.0,
            "accelerate_screening": True,
        },
        "extreme_vix_threshold": 40,
        "extreme_vix_action": "no_restriction",
        "exit_holdings_at_vix": None,
        "notes": "Defense names often benefit from geopolitical-driven VIX spikes.",
    },
    "tax_loss_harvest": {
        "max_vix_for_entry": None,
        "elevated_vix_band": [25, 50],
        "elevated_vix_changes": {
            "accelerate_screening": True,
        },
        "extreme_vix_threshold": None,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "VIX spikes create harvestable losses — accelerate.",
    },
    "cash_or_stable": {
        "max_vix_for_entry": None,
        "elevated_vix_band": [30, 50],
        "elevated_vix_changes": {
            "accelerate_screening": True,
            "prefer_short_duration": True,
        },
        "extreme_vix_threshold": None,
        "extreme_vix_action": "accelerate_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Cash is always eligible — defensive allocation rises with VIX.",
    },
    "fib_retracement_bounce": {
        "max_vix_for_entry": 30,
        "elevated_vix_band": [22, 30],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
            "require_61_8_only": True,
            "require_aplus_grade": True,
        },
        "extreme_vix_threshold": 30,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Retracements often turn into breakdowns in high VIX — require deepest level only.",
    },
    "earnings_pre_buildup": {
        "max_vix_for_entry": 28,
        "elevated_vix_band": [22, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.5,
            "require_aplus_grade": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Pre-earnings positioning is most VIX-sensitive — IV crush risk amplifies.",
    },
    "earnings_post_momentum": {
        "max_vix_for_entry": 35,
        "elevated_vix_band": [25, 35],
        "elevated_vix_changes": {
            "position_size_multiplier": 0.75,
            "require_beat_15pct_plus": True,
        },
        "extreme_vix_threshold": 35,
        "extreme_vix_action": "pause_new_entries",
        "exit_holdings_at_vix": None,
        "notes": "Post-earnings momentum is more durable but require larger beats in high VIX.",
    },
}

# Technical indicators required per strategy
TECHNICAL_INDICATORS = {
    "momentum_scalp": {
        "gates": [
            {"id": "VWAP_RECLAIM", "condition": "price > vwap (intraday)", "metric": "price_vs_vwap", "operator": "gt", "value": 0},
            {"id": "EMA_9_ABOVE_EMA_21", "condition": "EMA(9) > EMA(21) on 5-min", "metric": "ema_9_minus_ema_21", "operator": "gt", "value": 0},
            {"id": "OPENING_RANGE_BREAK", "condition": "price > opening 15-min high", "metric": "price_vs_or_high", "operator": "gt", "value": 0},
        ],
        "preferred": ["rvol_5min", "rsi_5", "atr_pct", "premarket_high_distance"],
        "irrelevant": ["ema_200", "fib_618_distance", "bollinger_squeeze"],
    },
    "gap_and_go": {
        "gates": [
            {"id": "GAP_PCT", "condition": "gap_pct > 5", "metric": "gap_pct", "operator": "gt", "value": 5.0},
            {"id": "FIRST_5MIN_CLOSE_ABOVE_GAP_HIGH", "condition": "close[1] > gap_high", "metric": "first_5min_close_vs_gap_high", "operator": "gt", "value": 0},
            {"id": "VWAP_ABOVE_GAP_LOW", "condition": "vwap > gap_low", "metric": "vwap_vs_gap_low", "operator": "gt", "value": 0},
        ],
        "preferred": ["rvol", "premarket_high", "ema_9", "atr_pct"],
        "irrelevant": ["ema_200", "fib_618_distance", "macd"],
    },
    "swing_breakout": {
        "gates": [
            {"id": "EMA_50_RISING", "condition": "EMA(50) slope > 0 over 5 days", "metric": "ema_50_slope_5d", "operator": "gt", "value": 0},
            {"id": "BASE_LENGTH", "condition": "consolidation base >= 15 days", "metric": "base_days", "operator": "gte", "value": 15},
            {"id": "BREAKOUT_VOLUME", "condition": "breakout day volume >= 1.5x 20-day avg", "metric": "breakout_volume_ratio", "operator": "gte", "value": 1.5},
            {"id": "RSI_NOT_OVERBOUGHT", "condition": "RSI(14) between 50 and 72", "metric": "rsi_14", "operator": "between", "value": [50, 72]},
        ],
        "preferred": ["fib_618_as_stop", "ema_200", "atr_14_pct", "sector_relative_strength"],
        "irrelevant": ["vwap", "opening_range"],
    },
    "swing_trade": {
        "gates": [
            {"id": "PRICE_ABOVE_EMA_50", "condition": "price > EMA(50)", "metric": "price_vs_ema_50", "operator": "gt", "value": 0},
            {"id": "EMA_50_ABOVE_EMA_200", "condition": "EMA(50) > EMA(200)", "metric": "ema_50_vs_ema_200", "operator": "gt", "value": 0},
            {"id": "RSI_BAND", "condition": "RSI(14) between 50 and 72", "metric": "rsi_14", "operator": "between", "value": [50, 72]},
            {"id": "ATR_STOP_REASONABLE", "condition": "ATR(14)-based stop <= 2x ATR", "metric": "stop_vs_atr_multiplier", "operator": "lte", "value": 2.0},
        ],
        "preferred": ["fib_618_distance", "volume_trend", "sector_rs"],
        "irrelevant": ["vwap", "opening_range", "bollinger_squeeze"],
    },
    "earnings_catalyst": {
        "gates": [
            {"id": "PRICE_DATA_FRESH", "condition": "price data <= 15 minutes old", "metric": "price_age_min", "operator": "lte", "value": 15},
        ],
        "preferred": ["ema_21", "rvol", "fib_618_distance"],
        "irrelevant": ["bollinger_squeeze"],
        "note": "See earnings_pre_buildup and earnings_post_momentum for sub-strategy specifics.",
    },
    "earnings_pre_buildup": {
        "gates": [
            {"id": "PRICE_ABOVE_EMA_21", "condition": "price > EMA(21)", "metric": "price_vs_ema_21", "operator": "gt", "value": 0},
            {"id": "VOLUME_TREND_RISING", "condition": "5-day avg volume > 20-day avg", "metric": "volume_5d_vs_20d", "operator": "gt", "value": 1.0},
            {"id": "IV_RANK_ELEVATED", "condition": "IV rank > 40 (signals expected move)", "metric": "iv_rank", "operator": "gte", "value": 40},
        ],
        "preferred": ["options_call_put_ratio", "analyst_revision_30d", "ema_50"],
        "irrelevant": ["vwap", "opening_range"],
    },
    "earnings_post_momentum": {
        "gates": [
            {"id": "GAP_UP_5PCT", "condition": "gap > 5% post-earnings", "metric": "gap_pct", "operator": "gte", "value": 5.0},
            {"id": "HOLD_30MIN_ABOVE_GAP_LOW", "condition": "price holds above gap_low for 30 min", "metric": "gap_hold_30min", "operator": "eq", "value": True},
            {"id": "VOLUME_EXPANSION", "condition": "first hour volume >= 3x avg", "metric": "first_hour_rvol", "operator": "gte", "value": 3.0},
        ],
        "preferred": ["ema_21", "vwap", "atr_14_pct"],
        "irrelevant": ["fib_618_distance", "bollinger_squeeze"],
    },
    "sector_rotation": {
        "gates": [
            {"id": "SECTOR_RS_VS_SPY", "condition": "5-day RS > SPY + 2%", "metric": "sector_5d_rs_minus_spy", "operator": "gte", "value": 0.02},
            {"id": "SECTOR_EMA_50_RISING", "condition": "sector ETF above and rising 50-day EMA", "metric": "ema_50_slope_5d", "operator": "gt", "value": 0},
            {"id": "BREADTH_CONFIRMING", "condition": "60%+ sector components above 50-day SMA", "metric": "pct_components_above_sma_50", "operator": "gte", "value": 0.60},
        ],
        "preferred": ["advance_decline_line", "sector_options_flow"],
        "irrelevant": ["vwap", "opening_range", "rsi_5"],
    },
    "recovery_watch": {
        "gates": [
            {"id": "RSI_OVERSOLD", "condition": "RSI(14) <= 30", "metric": "rsi_14", "operator": "lte", "value": 30},
            {"id": "ABOVE_PRIOR_SWING_LOW", "condition": "price > most recent swing low", "metric": "price_vs_swing_low", "operator": "gt", "value": 0},
            {"id": "VOLUME_CAPITULATION", "condition": "recent volume spike on down day (capitulation signal)", "metric": "down_day_rvol", "operator": "gte", "value": 2.0},
        ],
        "preferred": ["williams_pct_r", "macd_divergence", "atr_14_pct", "bollinger_lower_band_touch"],
        "irrelevant": ["vwap", "opening_range"],
    },
    "income_add": {
        "gates": [
            {"id": "PULLBACK_TO_SUPPORT", "condition": "price at EMA(50) or 61.8% retracement", "metric": "pullback_to_support", "operator": "eq", "value": True},
            {"id": "RSI_NOT_OVERBOUGHT", "condition": "RSI(14) <= 50 (cooled, not euphoric)", "metric": "rsi_14", "operator": "lte", "value": 50},
        ],
        "preferred": ["dividend_ex_date_proximity", "fib_618_distance", "ema_200"],
        "irrelevant": ["vwap", "opening_range", "bollinger_squeeze"],
    },
    "fib_retracement_bounce": {
        "gates": [
            {"id": "UPTREND_CONFIRMED", "condition": "EMA(50) > EMA(200), both rising", "metric": "trend_state", "operator": "eq", "value": "confirmed_uptrend"},
            {"id": "FIB_LEVEL_TOUCH", "condition": "within 1.5% of 50% or 61.8% retracement", "metric": "fib_distance_pct", "operator": "lte", "value": 0.015},
            {"id": "RSI_RESET", "condition": "RSI(14) between 35 and 50", "metric": "rsi_14", "operator": "between", "value": [35, 50]},
            {"id": "BOUNCE_VOLUME", "condition": "bounce day volume >= 1.3x 20-day avg", "metric": "bounce_volume_ratio", "operator": "gte", "value": 1.3},
        ],
        "preferred": ["volume_dryup_3_days", "ema_50_distance", "atr_14_pct"],
        "irrelevant": ["vwap", "opening_range"],
    },
    "speculative_growth": {
        "gates": [
            {"id": "RS_RANK_TOP_20PCT", "condition": "RS rank percentile >= 80", "metric": "rs_rank_percentile", "operator": "gte", "value": 80},
            {"id": "BREAKOUT_CONFIRMED", "condition": "price breaking above consolidation", "metric": "breakout_confirmed", "operator": "eq", "value": True},
            {"id": "EMA_50_RISING", "condition": "EMA(50) slope > 0", "metric": "ema_50_slope_5d", "operator": "gt", "value": 0},
        ],
        "preferred": ["atr_14_pct", "volume_trend", "fib_618_distance"],
        "irrelevant": ["vwap", "opening_range"],
    },
    "covered_call_income": {
        "gates": [
            {"id": "IV_RANK_ELEVATED", "condition": "IV rank >= 50 (rich premium)", "metric": "iv_rank", "operator": "gte", "value": 50},
            {"id": "EXISTING_POSITION_100_SHARES", "condition": "existing long stock position >= 100 shares per contract", "metric": "shares_held", "operator": "gte", "value": 100},
        ],
        "preferred": ["delta_target_0_20_to_0_30", "dte_30_to_45"],
        "irrelevant": ["vwap", "opening_range", "rsi_14", "ema_9"],
        "note": "Technicals largely irrelevant for entry — premium and assignment math drive decision.",
    },
    "dividend_growth_compounder": {
        "gates": [],
        "preferred": ["ema_200_support", "rsi_14_below_50", "pullback_to_ema_50"],
        "irrelevant": ["vwap", "opening_range", "rsi_5", "bollinger_squeeze"],
        "note": "Fundamental entry — technicals only inform timing, not eligibility.",
    },
    "high_yield_income_bdc": {
        "gates": [],
        "preferred": ["ema_200_support", "rsi_14_below_50", "discount_to_nav_widening"],
        "irrelevant": ["vwap", "opening_range", "rsi_5"],
        "note": "NAV and credit metrics drive entry — technicals secondary.",
    },
    "reit_income": {
        "gates": [],
        "preferred": ["ema_200_support", "rate_sensitivity_check"],
        "irrelevant": ["vwap", "opening_range", "rsi_5"],
        "note": "FFO/AFFO and rate environment drive entry.",
    },
    "bond_income": {
        "gates": [],
        "preferred": ["duration_appropriateness", "yield_curve_position"],
        "irrelevant": ["vwap", "opening_range", "rsi_14", "ema_9", "bollinger_squeeze"],
        "note": "Duration and credit drive entry, not price technicals.",
    },
    "international_dividend": {
        "gates": [],
        "preferred": ["ema_200_support", "currency_trend"],
        "irrelevant": ["vwap", "opening_range", "rsi_5"],
        "note": "Fundamental and currency-driven entry.",
    },
    "core_index": {
        "gates": [],
        "preferred": ["pullback_to_ema_200", "volatility_regime"],
        "irrelevant": ["vwap", "opening_range", "rsi_5", "fib_618"],
        "note": "Mechanical DCA — technicals largely irrelevant.",
    },
    "core_growth_compounder": {
        "gates": [
            {"id": "EMA_200_SUPPORT", "condition": "price within 5% of EMA(200) on pullback", "metric": "distance_from_ema_200", "operator": "lte", "value": 0.05},
        ],
        "preferred": ["rsi_14_below_50", "fib_618_distance"],
        "irrelevant": ["vwap", "opening_range", "rsi_5"],
    },
    "defense_thesis": {
        "gates": [],
        "preferred": ["ema_200_support", "sector_rs", "contract_announcement_proximity"],
        "irrelevant": ["vwap", "opening_range"],
        "note": "Thematic/fundamental entry — technicals inform timing only.",
    },
    "tax_loss_harvest": {
        "gates": [],
        "preferred": [],
        "irrelevant": ["vwap", "opening_range", "rsi", "ema", "fib", "bollinger", "macd"],
        "note": "Technicals are entirely irrelevant — this is a tax-driven strategy.",
    },
    "cash_or_stable": {
        "gates": [],
        "preferred": ["yield_vs_t_bill_spread"],
        "irrelevant": ["vwap", "opening_range", "rsi", "ema", "fib", "bollinger", "macd"],
        "note": "Yield environment drives entry.",
    },
}

# Performance context: standard template, populated by paper_performance_governance.py
PERFORMANCE_CONTEXT_TEMPLATE = {
    "last_updated": None,
    "closed_paper_trades": 0,
    "win_rate": None,
    "avg_r_realized": None,
    "profit_factor": None,
    "max_drawdown_pct": None,
    "expectancy_per_trade": None,
    "best_trade_r": None,
    "worst_trade_r": None,
    "current_streak": None,
    "ready_for_review": False,
    "review_thresholds": {
        "min_trades": 30,
        "min_months": 6,
        "min_profit_factor": 1.25,
        "min_win_rate": 0.50,
    },
    "notes": "Populated nightly by scripts/paper_performance_governance.py. Used by LLM prompts to evaluate proposal context.",
}

# -----------------------------------------------------------------------------
# Core patching logic
# -----------------------------------------------------------------------------

def make_yaml():
    """Create a configured ruamel YAML instance that preserves comments/order."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096  # don't wrap long lines
    return yaml


def patch_file(yaml_path: Path, dry_run: bool, backup_dir: Path) -> dict:
    """
    Patch a single YAML file. Returns a result dict:
        { "path": ..., "added": [...], "skipped": [...], "error": ... }
    """
    result = {"path": str(yaml_path), "added": [], "skipped": [], "error": None}
    strategy_id = yaml_path.stem

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

    # 1. vix_rules
    if "vix_rules" in data:
        result["skipped"].append("vix_rules")
    else:
        vix = VIX_RULES.get(strategy_id)
        if vix is None:
            result["skipped"].append(f"vix_rules (no template for {strategy_id})")
        else:
            data["vix_rules"] = vix
            result["added"].append("vix_rules")

    # 2. technical_indicators_required
    if "technical_indicators_required" in data:
        result["skipped"].append("technical_indicators_required")
    else:
        ti = TECHNICAL_INDICATORS.get(strategy_id)
        if ti is None:
            result["skipped"].append(f"technical_indicators_required (no template for {strategy_id})")
        else:
            data["technical_indicators_required"] = ti
            result["added"].append("technical_indicators_required")

    # 3. performance_context
    if "performance_context" in data:
        result["skipped"].append("performance_context")
    else:
        # deep-copy by re-serializing the template
        import copy
        data["performance_context"] = copy.deepcopy(PERFORMANCE_CONTEXT_TEMPLATE)
        result["added"].append("performance_context")

    # Write changes (or simulate)
    if result["added"] and not result["error"]:
        if dry_run:
            pass  # nothing to write
        else:
            # Backup first
            backup_path = backup_dir / yaml_path.name
            shutil.copy2(yaml_path, backup_path)
            with open(yaml_path, "w") as f:
                yaml.dump(data, f)

    return result


def main():
    parser = argparse.ArgumentParser(description="Bulk-patch strategy YAML files with missing blocks.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (writes files, makes backups).")
    parser.add_argument(
        "--config-dir",
        default="config/strategies",
        help="Path to strategy YAML directory (default: config/strategies)",
    )
    parser.add_argument(
        "--backup-root",
        default="backups",
        help="Root directory for backups (default: backups)",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)
    if args.dry_run and args.apply:
        print("ERROR: --dry-run and --apply are mutually exclusive")
        sys.exit(1)

    config_dir = Path(args.config_dir)
    if not config_dir.exists():
        print(f"ERROR: config dir not found: {config_dir}")
        print(f"  Run from project root: cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
        sys.exit(1)

    # Create backup directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(args.backup_root) / f"strategy_yaml_{timestamp}"
    if args.apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        print(f"Backup directory: {backup_dir}")

    print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"Scanning: {config_dir}")
    print("=" * 80)

    yaml_files = sorted(config_dir.glob("*.yaml"))
    # Skip shared_risk_rules and any "_template" or "_example" files
    yaml_files = [
        f for f in yaml_files
        if not f.stem.startswith("_")
        and f.stem not in ("shared_risk_rules",)
    ]

    total_added = 0
    total_skipped = 0
    total_errors = 0
    results = []

    for yaml_path in yaml_files:
        result = patch_file(yaml_path, args.dry_run, backup_dir)
        results.append(result)
        added = result["added"]
        skipped = result["skipped"]
        err = result["error"]
        status = "ERROR" if err else ("ADDED" if added else "OK")
        print(f"  {yaml_path.stem:30s} [{status}]")
        if added:
            print(f"    + added: {', '.join(added)}")
            total_added += len(added)
        if skipped:
            print(f"    = skipped (already present): {', '.join(skipped)}")
            total_skipped += len(skipped)
        if err:
            print(f"    ! error: {err}")
            total_errors += 1

    print("=" * 80)
    print(f"Summary: {len(yaml_files)} files scanned")
    print(f"  Blocks added: {total_added}")
    print(f"  Blocks skipped (already present): {total_skipped}")
    print(f"  Errors: {total_errors}")

    if args.dry_run:
        print("\nDRY-RUN complete. Re-run with --apply to write changes.")
    else:
        print(f"\nBackups saved to: {backup_dir}")
        print("Run validate_strategy_yamls.py to verify.")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
