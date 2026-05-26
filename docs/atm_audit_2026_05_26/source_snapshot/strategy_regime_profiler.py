#!/usr/bin/env python3
"""strategy_regime_profiler.py — Seed strategy-to-regime preference profiles.

Usage:
    .venv/bin/python scripts/strategy_regime_profiler.py --dry-run --json
    .venv/bin/python scripts/strategy_regime_profiler.py --apply --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _uid(p="SRP_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
def _get_conn():
    from session13_db import get_conn
    return get_conn()

# Inferred strategy regime profiles
PROFILES = {
    "momentum_scalp": {"favored": ["risk_on_trend","broad_momentum"], "disfavored": ["risk_off","high_volatility","choppy_range"],
                        "vol": "medium", "trend": "trending", "liquidity": "high", "horizon": "scalp"},
    "gap_and_go": {"favored": ["high_volatility","broad_momentum"], "disfavored": ["low_volatility_grind","choppy_range"],
                    "vol": "high", "trend": "trending", "liquidity": "high", "horizon": "day"},
    "swing_breakout": {"favored": ["risk_on_trend","low_volatility_grind"], "disfavored": ["high_volatility","risk_off"],
                        "vol": "low", "trend": "trending", "liquidity": "medium", "horizon": "swing"},
    "swing_trade": {"favored": ["risk_on_trend","low_volatility_grind"], "disfavored": ["high_volatility"],
                     "vol": "low", "trend": "trending", "liquidity": "medium", "horizon": "swing"},
    "earnings_catalyst": {"favored": ["broad_momentum","risk_on_trend"], "disfavored": ["risk_off"],
                           "vol": "any", "trend": "any", "liquidity": "high", "horizon": "swing"},
    "speculative_growth": {"favored": ["risk_on_trend","broad_momentum"], "disfavored": ["risk_off","defensive_rotation"],
                            "vol": "medium", "trend": "trending", "liquidity": "medium", "horizon": "position"},
    "core_growth_compounder": {"favored": ["risk_on_trend","low_volatility_grind"], "disfavored": [],
                                "vol": "any", "trend": "any", "liquidity": "low", "horizon": "position"},
    "dividend_growth_compounder": {"favored": ["low_volatility_grind","defensive_rotation"], "disfavored": [],
                                    "vol": "any", "trend": "any", "liquidity": "low", "horizon": "income"},
    "covered_call_income": {"favored": ["low_volatility_grind","choppy_range"], "disfavored": ["high_volatility"],
                             "vol": "low", "trend": "range", "liquidity": "low", "horizon": "income"},
    "high_yield_income_bdc": {"favored": ["low_volatility_grind"], "disfavored": ["risk_off","high_volatility"],
                               "vol": "low", "trend": "any", "liquidity": "low", "horizon": "income"},
    "reit_income": {"favored": ["low_volatility_grind","defensive_rotation"], "disfavored": ["high_volatility"],
                     "vol": "low", "trend": "any", "liquidity": "low", "horizon": "income"},
    "sector_rotation": {"favored": ["broad_momentum","defensive_rotation"], "disfavored": ["choppy_range"],
                         "vol": "any", "trend": "any", "liquidity": "medium", "horizon": "swing"},
    "recovery_watch": {"favored": ["risk_on_trend"], "disfavored": ["risk_off"],
                        "vol": "any", "trend": "reversal", "liquidity": "medium", "horizon": "swing"},
    "tax_loss_harvest": {"favored": ["risk_off"], "disfavored": [],
                          "vol": "any", "trend": "any", "liquidity": "low", "horizon": "position"},
    "defense_thesis": {"favored": ["risk_on_trend","broad_momentum"], "disfavored": ["risk_off"],
                        "vol": "any", "trend": "trending", "liquidity": "low", "horizon": "position"},
}


def build_profiles():
    profiles = []
    for sid, p in PROFILES.items():
        profiles.append({
            "profile_id": _uid(), "strategy_id": sid, "strategy_name": sid.replace("_", " ").title(),
            "favored_regimes": p["favored"], "disfavored_regimes": p["disfavored"],
            "neutral_regimes": [], "volatility_preference": p["vol"],
            "trend_preference": p["trend"], "liquidity_requirement": p["liquidity"],
            "breadth_requirement": "any", "time_horizon": p["horizon"],
        })
    return profiles


def save_profiles(conn, profiles, dry_run=True):
    if dry_run: return
    cur = conn.cursor()
    for p in profiles:
        cur.execute("""
            INSERT INTO strategy_regime_profiles
                (profile_id, strategy_id, strategy_name, favored_regimes, disfavored_regimes,
                 neutral_regimes, volatility_preference, trend_preference,
                 liquidity_requirement, breadth_requirement, time_horizon, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'inferred_session33')
            ON CONFLICT (strategy_id) DO UPDATE SET
                favored_regimes=EXCLUDED.favored_regimes, disfavored_regimes=EXCLUDED.disfavored_regimes,
                updated_at=now()
        """, [p["profile_id"], p["strategy_id"], p["strategy_name"],
              json.dumps(p["favored_regimes"]), json.dumps(p["disfavored_regimes"]),
              json.dumps(p["neutral_regimes"]), p["volatility_preference"],
              p["trend_preference"], p["liquidity_requirement"],
              p["breadth_requirement"], p["time_horizon"]])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Strategy Regime Profiler")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--strategy")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    profiles = build_profiles()
    if args.strategy:
        profiles = [p for p in profiles if p["strategy_id"] == args.strategy]

    conn = _get_conn()
    try:
        if not dry_run:
            save_profiles(conn, profiles)

        out = {"mode": "dry_run" if dry_run else "applied", "profiles": len(profiles)}
        if args.json:
            out["data"] = [{k: v for k, v in p.items() if k != "profile_id"} for p in profiles]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Profiler: {out['profiles']} profiles ({out['mode']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
