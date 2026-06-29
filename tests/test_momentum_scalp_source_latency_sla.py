#!/usr/bin/env python3
"""P0-6: latency SLA grading is deterministic, identifies the bottleneck, and NEVER counts a
stale-quote reject as a pass (quote freshness is not weakened)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_source_latency_sla import (grade, evaluate_window, build, to_markdown,  # noqa: E402
                                               WINDOWS)

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- grade() ----
    check("under target → PASS", grade(4, 5) == "PASS")
    check("at target → PASS", grade(5, 5) == "PASS")
    check("<=1.5x → WARN", grade(7, 5) == "WARN")
    check(">1.5x → FAIL", grade(20, 5) == "FAIL")
    check("missing data → WARN (never silent PASS)", grade(None, 5) == "WARN")

    open_t = WINDOWS["open"]

    # ---- evaluate_window: clean pass with fresh evaluations ----
    ev = evaluate_window({"source_to_proposal_min": 3, "proposal_to_validation_min": 0.5,
                          "fresh_quote_evaluations": 5, "stale_quote_rejects": 0}, open_t)
    check("open window clean → PASS", ev["overall"] == "PASS")
    check("no bottleneck when PASS", ev["bottleneck"] is None)

    # ---- CRITICAL: a fast proposal→validation that is ALL stale-quote rejects is NOT a PASS ----
    ev = evaluate_window({"source_to_proposal_min": 3, "proposal_to_validation_min": 0.4,
                          "fresh_quote_evaluations": 0, "stale_quote_rejects": 9}, open_t)
    check("stale-quote-only validation is NOT PASS (freshness preserved)",
          ev["grades"]["proposal_to_validation"] != "PASS")

    # ---- bottleneck identification ----
    ev = evaluate_window({"source_to_proposal_min": 30, "proposal_to_validation_min": 0.5,
                          "fresh_quote_evaluations": 3, "stale_quote_rejects": 0}, open_t)
    check("slow source→proposal flagged FAIL", ev["grades"]["source_to_proposal"] == "FAIL")
    check("bottleneck = source_to_proposal", ev["bottleneck"] == "source_to_proposal")

    # ---- missing data → WARN, never PASS ----
    ev = evaluate_window({"source_to_proposal_min": None, "proposal_to_validation_min": None,
                          "fresh_quote_evaluations": 0, "stale_quote_rejects": 0}, open_t)
    check("no data → overall not PASS", ev["overall"] != "PASS")

    # ---- build(): structure + safety notes ----
    r = build(30)
    check("report ok", r.get("ok") is True)
    check("has 3 windows", set(r["windows"].keys()) == {"premarket", "open", "late_morning"})
    check("freshness note: stale not counted as pass", "stale-quote DEFER is not counted" in r["freshness_note"])
    check("no live broker writes note", "No live broker writes" in r["safety_note"])
    check("targets match spec (open 5/1)",
          r["windows"]["open"]["targets"] == {"source_to_proposal_max": 5, "proposal_to_validation_max": 1})
    check("markdown renders", "Latency SLA" in to_markdown(r))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
