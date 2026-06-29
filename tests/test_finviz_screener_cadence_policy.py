#!/usr/bin/env python3
"""P3: every screener has a cadence class; only scalp_fast runs at <=5-min cadence; swing screens never
run at scalp cadence; the broad DB screeners are not at 5-min cadence."""
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from apply_finviz_screener_cadence import build  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    pol = yaml.safe_load(open(os.path.join(ROOT, "config", "finviz_screener_cadence_policy.yaml")).read())["cadence_classes"]
    for need in ("scalp_fast", "scout_intraday", "swing_intraday", "swing_daily",
                 "fundamental_daily", "income_weekly", "experimental_disabled"):
        check(f"cadence class defined: {need}", need in pol)
    # only scalp_fast has a <=5-min window
    fast = [c for c, p in pol.items() if p.get("default_windows") and any(w.get("every_minutes", 999) <= 5 for w in p["default_windows"])]
    check("only scalp_fast runs at <=5-min cadence", fast == ["scalp_fast"])

    r = build()
    check("cadence assignment PASS (no invariant violations)", r["ok"])
    check("every screener has a cadence class", all(a["cadence_class"] in pol for a in r["assignments"]))
    check("exactly 3 scalp_fast screeners (the lane)", r["by_class"]["scalp_fast"] == 3)
    check("swing presets in swing classes, not scalp", r["by_class"]["swing_daily"] >= 1 and r["by_class"]["swing_intraday"] >= 1)
    check("income/fundamental screeners exist on slow cadence",
          r["by_class"]["income_weekly"] >= 1 and r["by_class"]["fundamental_daily"] >= 1)
    # No swing/income/fundamental screener landed in scalp_fast.
    nonscalp_in_fast = [a for a in r["assignments"]
                        if a["cadence_class"] == "scalp_fast" and a["strategy_family"] != "momentum_scalp"]
    check("no non-momentum_scalp screener at scalp cadence", nonscalp_in_fast == [])
    check("scalp_fast forbids cloud LLM", pol["scalp_fast"]["cloud_llm_allowed"] is False)
    check("no broker writes note", "No broker writes" in r["note"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
