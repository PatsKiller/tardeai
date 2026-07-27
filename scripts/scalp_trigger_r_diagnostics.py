#!/usr/bin/env python3
"""M3-S5.5 — S5 trigger-R quality diagnostics (measurement only; NO threshold change).

The S5 finding (6 TRIGGER fires, 0/6 hit +1R) was driven by extremely small calculated R on thin
names. This measures — through the required sample, not on 6 events — how often R is operationally
meaningless: ATR-floor binding, R in $/bps, min-tick-to-R, spread-to-R, assumed-slippage-to-R, the
frequency of R below 1/2/4 ticks, split by profiled vs proxy cohort and by selected source/feed.

Read-only over scalp_ignition_events (lane='TRIGGER'). Produces EVIDENCE for a later operator
decision. Does NOT add a minimum-R filter and does NOT change any threshold. No engine import beyond
config; no order/proposal path.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_CONFIG = _REPO / "config" / "scalp_signal_engine.yaml"


def r_quality(entry: float, r_dollars: float, spread_bps, tick: float,
              assumed_slippage_bps: float) -> dict:
    """Pure per-trigger R-quality metrics. Returns ratios that expose whether R is meaningful.
    Larger tick/spread/slippage relative to R = R is operationally too small to be tradeable."""
    if not entry or not r_dollars or r_dollars <= 0:
        return {"valid": False}
    r_bps = r_dollars / entry * 1e4
    spread_dollars = (float(spread_bps) / 1e4 * entry) if spread_bps is not None else None
    slippage_dollars = assumed_slippage_bps / 1e4 * entry
    return {
        "valid": True,
        "r_dollars": round(r_dollars, 4),
        "r_bps": round(r_bps, 2),
        "tick_to_r": round(tick / r_dollars, 3),
        "spread_to_r": round(spread_dollars / r_dollars, 3) if spread_dollars is not None else None,
        "slippage_to_r": round(slippage_dollars / r_dollars, 3),
        "r_below_1_tick": r_dollars < tick,
        "r_below_2_tick": r_dollars < 2 * tick,
        "r_below_4_tick": r_dollars < 4 * tick,
    }


def _tick_for(price: float) -> float:
    return 0.0001 if (price is not None and price < 1.0) else 0.01


def _summ(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "median": round(statistics.median(vals), 3),
            "mean": round(statistics.mean(vals), 3), "max": round(max(vals), 3)}


def run(args) -> int:
    cfg = yaml.safe_load(_CONFIG.read_text())
    slip_bps = float(cfg["data_tiers"]["assumed_slippage_bps"][cfg["data_tiers"]["active_tier"]])
    try:
        from db_adapter import get_connection
    except ModuleNotFoundError:
        from scripts.db_adapter import get_connection
    c = get_connection().cursor()
    c.execute("""SELECT entry_ref, r_dollars, spread_bps, profile_source, data_tier,
                        gate_reasons->>'floor_bound' AS floor_bound
                 FROM scalp_ignition_events WHERE lane='TRIGGER' AND entry_ref IS NOT NULL""")
    rows = c.fetchall()
    cohorts: dict = {}
    floor_bound_known = floor_bound_true = 0
    for entry, R, spread_bps, psrc, tier, fb in rows:
        if entry is None or R is None:
            continue
        entry, R = float(entry), float(R)
        q = r_quality(entry, R, spread_bps, _tick_for(entry), slip_bps)
        if not q["valid"]:
            continue
        cohort = "profiled" if psrc == "per_symbol" else "proxy"
        feed = tier or "T0"
        for key in (("cohort", cohort), ("feed", feed)):
            bucket = cohorts.setdefault(f"{key[0]}={key[1]}", {"tick_to_r": [], "spread_to_r": [],
                     "slippage_to_r": [], "r_bps": [], "below1": 0, "below2": 0, "below4": 0, "n": 0})
            bucket["n"] += 1
            bucket["tick_to_r"].append(q["tick_to_r"])
            bucket["spread_to_r"].append(q["spread_to_r"])
            bucket["slippage_to_r"].append(q["slippage_to_r"])
            bucket["r_bps"].append(q["r_bps"])
            bucket["below1"] += int(q["r_below_1_tick"])
            bucket["below2"] += int(q["r_below_2_tick"])
            bucket["below4"] += int(q["r_below_4_tick"])
        if fb is not None:
            floor_bound_known += 1
            floor_bound_true += int(fb == "true")

    print(f"S5 trigger-R diagnostics — {len(rows)} TRIGGER rows; assumed_slippage={slip_bps}bps ({cfg['data_tiers']['active_tier']})")
    print(f"ATR-floor binding: {floor_bound_true}/{floor_bound_known} known "
          f"({'n/a — legacy rows lack floor_bound' if floor_bound_known == 0 else ''})")
    for name, b in sorted(cohorts.items()):
        print(f"\n[{name}] n={b['n']}")
        print(f"  R (bps):        {_summ(b['r_bps'])}")
        print(f"  tick/R:         {_summ(b['tick_to_r'])}")
        print(f"  spread/R:       {_summ(b['spread_to_r'])}")
        print(f"  slippage/R:     {_summ(b['slippage_to_r'])}")
        print(f"  R<1tick={b['below1']}  R<2tick={b['below2']}  R<4tick={b['below4']}  (of {b['n']})")
    print("\nNOTE: measurement only. Do NOT add a minimum-R filter until the §12 sample gate "
          "(≥100 TRIGGER fires / ≥15 sessions). Cohorts never pooled.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M3-S5.5 S5 trigger-R quality diagnostics (read-only)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
