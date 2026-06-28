#!/usr/bin/env python3
"""P1-1: funnel report runs, degrades gracefully, separates families, never claims live-ready."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scalp_lifecycle_funnel_report import build_funnel, to_markdown, GATE  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    rep = build_funnel(30)
    check("report has ok/status", "status" in rep)
    check("report runs without raising", rep.get("ok") is not None)
    check("has funnel stages or documented warning", bool(rep.get("stages")) or bool(rep.get("warnings")))
    check("separates families", set(rep.get("families", {}).keys()) ==
          {"social_only", "momentum_scalp", "meme_squeeze_momentum"})
    vg = rep.get("validation_gate", {})
    check("reports validation gate thresholds", vg.get("min_closed_paper_trades") == GATE["min_closed_paper_trades"])
    check("NEVER claims live-readiness", vg.get("live_ready_claim") is False)
    check("gate_met is boolean", isinstance(vg.get("gate_met"), bool))
    check("markdown renders", "Scalp Lifecycle Funnel" in to_markdown(rep))
    check("conversions present", "conversions" in rep)
    # Missing-table degradation: a huge window still returns a structured report, not a crash.
    rep2 = build_funnel(1)
    check("short window still structured", rep2.get("status") in ("PASS", "WARN"))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
