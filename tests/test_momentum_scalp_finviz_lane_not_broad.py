#!/usr/bin/env python3
"""P2: the 5-minute momentum-scalp lane must run ONLY the purpose-built scalp/gapper screens and must
NOT shell out to `finviz_screener_runner.py --run` (which fires all 29 broad DB screeners)."""
import os
import re
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import momentum_scalp_early_lane_runner as lane  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    src = open(os.path.join(ROOT, "scripts", "momentum_scalp_early_lane_runner.py")).read()
    scan_src = open(os.path.join(ROOT, "scripts", "run_finviz_momentum_scalp_scan.py")).read()

    # No EXECUTABLE call to finviz_screener_runner.py --run (a _run([... "--run"]) command list).
    exec_broad = re.search(r'finviz_screener_runner\.py"\s*\]\s*,\s*"--run"|"finviz_screener_runner\.py"\),\s*"--run"', src + scan_src)
    check("lane does NOT execute finviz_screener_runner.py --run", exec_broad is None)
    check("lane uses run_finviz_targeted_screeners", "run_finviz_targeted_screeners.py" in src)

    # The scalp lane screen set is the registry scalp_lane ids (scalp_fast only).
    reg = yaml.safe_load(open(os.path.join(ROOT, "config", "finviz_screeners.yaml")).read())
    scalp_ids = set(reg["scalp_lane_screener_ids"])
    by_id = {p["screener_id"]: p for p in reg["screeners"]}
    lane_ids = set(lane._scalp_lane_screener_ids(lane.now_et("2026-06-29T07:00:00")))   # pre-open
    check("pre-open lane excludes intraday_continuation", "momentum_scalp_intraday_continuation" not in lane_ids)
    check("pre-open lane is the 2 gapper screens",
          lane_ids == {"momentum_scalp_primary_gappers", "momentum_scalp_low_price_active_gappers"})

    open_ids = set(lane._scalp_lane_screener_ids(lane.now_et("2026-06-29T10:00:00")))   # post-open
    check("post-open lane includes intraday_continuation", "momentum_scalp_intraday_continuation" in open_ids)

    # Every lane screen is scalp_fast — NO swing/fundamental/income screen is in the lane.
    check("every lane screen is scalp_fast",
          all(by_id[i]["cadence_class"] == "scalp_fast" for i in (lane_ids | open_ids)))
    check("swing presets NOT in the scalp lane",
          "swing_smallcap_quality_trend_extension" not in (lane_ids | open_ids)
          and "swing_smallcap_uptrend_pullback" not in (lane_ids | open_ids))
    # No DB (income/swing/fundamental) screener_id can appear in the scalp lane.
    db_ids = {s["screener_id"] for s in reg.get("db_screeners", [])}
    check("no broad DB screener in the scalp lane", not ((lane_ids | open_ids) & db_ids))

    # stage_finviz_scan reports targeted + the scalp screen set.
    s = lane.stage_finviz_scan(dry_run=True)
    check("stage marks itself targeted", s.get("targeted") is True)
    check("stage scalp_screeners ⊆ scalp_lane registry", set(s["scalp_screeners"]) <= scalp_ids)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
