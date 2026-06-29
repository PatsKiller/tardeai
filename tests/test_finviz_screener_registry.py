#!/usr/bin/env python3
"""P1: the Finviz screener registry is well-formed, contains the 5 operator presets, scopes the scalp
lane to scalp_fast-only, and stays in sync with the live DB (validator). Discovery-only invariant."""
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from validate_finviz_screener_registry import validate  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    reg = yaml.safe_load(open(os.path.join(ROOT, "config", "finviz_screeners.yaml")).read())
    presets = reg["screeners"]
    pid = {p["preset_id"] for p in presets}

    check("registry has 5 operator presets", len(presets) == 5)
    for need in ("s144880153", "s144880160", "s144880157", "s144880159", "s144880158"):
        check(f"preset {need} present", need in pid)
    check("db_screeners present (29 from DB)", len(reg.get("db_screeners", [])) >= 25)

    # discovery-only invariant: NO screener is GO-eligible by itself
    all_s = presets + reg.get("db_screeners", [])
    check("no screener is GO-eligible by itself", all(s.get("go_eligible_by_itself") is False for s in all_s))

    # scalp lane is scalp_fast only
    scalp_ids = reg["scalp_lane_screener_ids"]
    check("scalp lane has exactly the 3 scalp screens", len(scalp_ids) == 3)
    by_id = {p["screener_id"]: p for p in presets}
    check("every scalp-lane screen is scalp_fast",
          all(by_id[s]["cadence_class"] == "scalp_fast" for s in scalp_ids))
    check("intraday_continuation is in the scalp lane", "momentum_scalp_intraday_continuation" in scalp_ids)

    # swing presets are NOT in the scalp lane
    check("swing presets not in scalp lane",
          "swing_smallcap_quality_trend_extension" not in scalp_ids
          and "swing_smallcap_uptrend_pullback" not in scalp_ids)

    # the swing presets are swing cadence, not scalp_fast
    check("swing quality preset is swing_daily",
          by_id["swing_smallcap_quality_trend_extension"]["cadence_class"] == "swing_daily")

    # validator passes (registry ↔ DB in sync, or DB-unavailable degrade)
    v = validate()
    check("registry validator PASS (no drift) or DB-unavailable",
          v["ok"] or not v["db_available"])
    check("validator reports no broker writes", "No broker writes" in v["note"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
