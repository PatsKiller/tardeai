#!/usr/bin/env python3
"""P3: the efficiency audit's recommend() logic (keep/reduce/merge/disable/promote) + the build report."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from finviz_screener_efficiency_audit import recommend, build  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- recommend() ----
    check("high overlap + low unique → disable_sunset",
          recommend({"overlap_pct": 85, "unique_contribution": 1, "cadence_class": "swing_daily"}) == "disable_sunset")
    check("duplicate → merge_duplicate", recommend({"is_duplicate": True}) == "merge_duplicate")
    check("slow family at fast cadence → reduce_cadence",
          recommend({"cadence_class": "fundamental_daily", "runs_at_fast_cadence": True,
                     "overlap_pct": 10, "unique_contribution": 5, "conversions_30d": 1}) == "reduce_cadence")
    check("zero conversions + low unique (non-scalp) → disable_sunset",
          recommend({"overlap_pct": 10, "unique_contribution": 1, "conversions_30d": 0, "cadence_class": "swing_daily"}) == "disable_sunset")
    check("low overlap + unique + conv + scalp → promote",
          recommend({"overlap_pct": 10, "unique_contribution": 8, "conversions_30d": 3, "cadence_class": "scalp_fast"}) == "promote")
    check("healthy scalp screen → keep",
          recommend({"overlap_pct": 25, "unique_contribution": 4, "conversions_30d": 1, "cadence_class": "scalp_fast", "runs_at_fast_cadence": True}) == "keep")
    check("high latency low yield → reduce_cadence",
          recommend({"latency_ms": 12000, "unique_contribution": 2, "overlap_pct": 10, "cadence_class": "swing_daily"}) in ("reduce_cadence", "disable_sunset"))

    # ---- build() ----
    r = build(30)
    check("audit report ok", r["ok"] is True)
    check("has per-screener list", len(r["screeners"]) >= 30)  # 5 presets + 29 db
    check("by_recommendation present", set(r["by_recommendation"].keys()) ==
          {"keep", "reduce_cadence", "merge_duplicate", "disable_sunset", "promote"})
    check("scalp screens are never auto-sunset",
          all(s["recommendation"] != "disable_sunset" for s in r["screeners"] if s["cadence_class"] == "scalp_fast"))
    check("note: discovery only / no broker writes", "no broker writes" in r["note"].lower())
    from finviz_screener_efficiency_audit import to_markdown
    check("markdown renders", "Finviz Screener Efficiency Audit" in to_markdown(r))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
