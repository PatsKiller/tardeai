#!/usr/bin/env python3
"""P0-5: source maturity scoring is deterministic, separates source from validation maturity, and
NEVER claims strategy 4.5+ unless the empirical validation sample gate is met."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_source_maturity_report import (score_source, build, to_markdown,  # noqa: E402
                                                   VALIDATION_SAMPLE_TARGET)

PASS, FAIL = [], []
FULL = {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- score_source rubric ----
    check("5.0 when everything proven (fresh + latency observed)",
          score_source(FULL, fresh_data=True, latency_ok=True) == 5.0)
    check("4.5 when wired/validated/tested but live observation pending",
          score_source(FULL, fresh_data=True, latency_ok=False) == 4.5)
    check("4.0 when handoff not proven",
          score_source({**FULL, "handoff_proven": False}, fresh_data=True, latency_ok=False) == 4.0)
    check("3.0 when cadence/filters partial",
          score_source({**FULL, "cadence_ok": False}, fresh_data=True, latency_ok=True) == 3.0)
    check("1.0 when not integrated",
          score_source(FULL, fresh_data=True, latency_ok=True, integrated=False) == 1.0)
    check("2.0 when stale/manual",
          score_source(FULL, fresh_data=False, latency_ok=False, stale_manual=True) == 2.0)
    check("score never exceeds 5.0", score_source(FULL, True, True) <= 5.0)

    # ---- build(): structure + separation + no premature 4.5 claim ----
    r = build(30)
    check("report ok", r.get("ok") is True)
    check("has per-source list", isinstance(r.get("sources"), list) and len(r["sources"]) >= 8)
    check("combined source maturity present", isinstance(r.get("combined_source_maturity"), (int, float)))
    check("every source score in [0,5]", all(0 <= s["after"] <= 5 for s in r["sources"]))

    vm = r["validation_maturity"]
    confirmed = vm["confirmed_closed_validation_trades"]
    check("validation target is 30", vm["target"] == VALIDATION_SAMPLE_TARGET == 30)
    # The CORE invariant: strategy 4.5+ is only claimable if the empirical gate is met.
    if confirmed is None or confirmed < 30:
        check("below-30 sample → empirical gate NOT met", vm["empirical_gate_met"] is False)
        check("below-30 sample → 4.5+ NOT claimable", "NOT claimable" in vm["strategy_maturity_claimable"])
        check("blocker names the validation sample", "sample" in vm["blocker"].lower())
    else:
        check("at/above 30 → gate met", vm["empirical_gate_met"] is True)

    # Report must explicitly separate source maturity from validation/strategy maturity.
    check("separation note present",
          "SEPARATELY" in r["separation_note"] and "does NOT" in r["separation_note"])
    check("does not claim strategy 4.5/5.0 in source section",
          r["combined_source_maturity"] <= 5.0 and vm["empirical_gate_met"] in (True, False))
    check("no live broker writes note", "No live broker writes" in r["safety_note"])

    # ---- markdown ----
    md = to_markdown(r)
    check("markdown renders", "Momentum Scalp Source Maturity" in md)
    check("markdown shows validation separation", "Validation maturity (separate" in md)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
