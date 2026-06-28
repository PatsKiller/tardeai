#!/usr/bin/env python3
"""P1-2: maturity score is evidence-derived, cap logic is correct, never falsely claims 4.5."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from compute_scalp_lifecycle_maturity import apply_caps, score_dimensions, DIMENSIONS, compute  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def _all_good_ev():
    return {"config_ok": True, "config_test": True, "expiry_test": True, "window_test": True,
            "alerts_test": True, "route_test": True, "liquidity_test": True, "trace_test": True,
            "trace_cols_present": True, "no_bypass_test": True, "funnel_runs": True,
            "funnel_gate_met": True, "outcome_runs": True}


def main():
    # 1. Weights sum to 1.0.
    check("dimension weights sum to 1.0", abs(sum(w for _, _, w in DIMENSIONS) - 1.0) < 1e-9)

    # 2. All-good + gate met → no caps, 5.0.
    ev = _all_good_ev()
    dims = score_dimensions(ev)
    final, caps = apply_caps(5.0, ev, dims)
    check("all-good gate-met → uncapped 5.0", final == 5.0 and not caps)

    # 3. Validation sample unmet caps at 4.4.
    ev2 = {**_all_good_ev(), "funnel_gate_met": False}
    final, caps = apply_caps(5.0, ev2, ev2)
    check("no validation sample caps at 4.4", final == 4.4)
    check("4.4 cap reason cites validation sample",
          any(c["cap"] == 4.4 and "validation sample" in c["reason"] for c in caps))

    # 4. Config conflict caps at 4.0.
    ev3 = {**_all_good_ev(), "config_ok": False, "config_test": False}
    final, _ = apply_caps(5.0, ev3, ev3)
    check("config conflict caps at 4.0", final == 4.0)

    # 5. Expired-approvable caps at 3.8.
    ev4 = {**_all_good_ev(), "expiry_test": False}
    final, _ = apply_caps(5.0, ev4, ev4)
    check("expired intraday approvable caps at 3.8", final == 3.8)

    # 6. Social-only GO alert caps at 3.8.
    ev5 = {**_all_good_ev(), "alerts_test": False}
    final, _ = apply_caps(5.0, ev5, ev5)
    check("social-only GO alert caps at 3.8", final == 3.8)

    # 7. No traceability caps at 4.1.
    ev6 = {**_all_good_ev(), "trace_test": False}
    final, _ = apply_caps(5.0, ev6, ev6)
    check("no traceability caps at 4.1", final == 4.1)

    # 8. Broker-write bypass caps at 3.5 (strongest).
    ev7 = {**_all_good_ev(), "no_bypass_test": False}
    final, _ = apply_caps(5.0, ev7, ev7)
    check("broker-write bypass caps at 3.5", final == 3.5)

    # 9. Lowest cap wins when several apply.
    ev8 = {**_all_good_ev(), "no_bypass_test": False, "funnel_gate_met": False}
    final, _ = apply_caps(5.0, ev8, ev8)
    check("lowest cap wins (3.5 over 4.4)", final == 3.5)

    # 10. Live compute() emits required fields and does not falsely claim 4.5.
    r = compute()
    check("compute emits final score", isinstance(r["final_maturity_score_of_5"], (int, float)))
    check("compute emits meets_4_5 bool", isinstance(r["meets_4_5"], bool))
    check("meets_4_5 consistent with score", r["meets_4_5"] == (r["final_maturity_score_of_5"] >= 4.5))
    check("emits momentum + social sub-scores",
          "momentum_scalp_lifecycle_of_5" in r and "social_scalp_lifecycle_of_5" in r)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
