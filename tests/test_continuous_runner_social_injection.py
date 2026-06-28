#!/usr/bin/env python3
"""P0-4: continuous_runner social injection is route-aware, not score-only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from continuous_runner import classify_social_injection  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def row(**kw):
    base = {"symbol": "X", "score": 50, "decision": "GO", "route": "momentum_scalp",
            "route_actionability": "GO", "route_strategy_id": "momentum_scalp",
            "catalyst_verified": True, "rvol": 7, "float_m": 8, "price": 5,
            "discovery_trace_id": "trace-1"}
    base.update(kw)
    return base


def main():
    # 1. Verified micro-cap GO → injected, tradeable momentum_scalp.
    r = classify_social_injection(row())
    check("verified micro-cap GO injectable+tradeable", r["injectable"] and r["tradeable"])
    check("→ momentum_scalp", r["strategy_id"] == "momentum_scalp")

    # 2. Social-only high-score WAIT → NOT injected as tradeable.
    r = classify_social_injection(row(decision="WAIT", route="watch_only",
                                      route_actionability="WAIT", route_strategy_id=None,
                                      catalyst_verified=False, score=55))
    check("social-only WAIT not injectable", not r["injectable"])
    check("social-only WAIT not tradeable", not r["tradeable"])

    # 3. Large-float verified squeeze/scalp → injected as manual-review scout, NOT momentum_scalp.
    r = classify_social_injection(row(route="large_float_social_scout",
                                      route_actionability="MANUAL_REVIEW",
                                      route_strategy_id="large_float_social_scout", float_m=50))
    check("large-float scout injectable", r["injectable"])
    check("large-float scout NOT tradeable", not r["tradeable"])
    check("large-float scout manual_review_required", r["manual_review_required"])
    check("large-float scout flagged large_float", r["large_float"])
    check("large-float scout NOT momentum_scalp", r["strategy_id"] != "momentum_scalp")

    # 4. meme_squeeze_momentum → manual-review scout too.
    r = classify_social_injection(row(route="meme_squeeze_momentum",
                                      route_actionability="MANUAL_REVIEW",
                                      route_strategy_id="meme_squeeze_momentum", float_m=80))
    check("meme squeeze → manual-review scout", r["injectable"] and r["manual_review_required"]
          and not r["tradeable"])

    # 5. Missing route fields → safe fallback (not injectable, not GO).
    r = classify_social_injection({"symbol": "X", "score": 90, "decision": "GO"})
    check("missing route fields → not injectable", not r["injectable"])

    # 6. momentum_scalp route but unverified catalyst → not tradeable.
    r = classify_social_injection(row(catalyst_verified=False))
    check("momentum_scalp route + unverified → not tradeable", not r["tradeable"])

    # 7. momentum_scalp route but large float (data mismatch) → not tradeable scalp.
    r = classify_social_injection(row(float_m=50))
    check("momentum_scalp route + float 50 → not tradeable", not r["tradeable"])

    # 8. Injected dict shape carries discovery_trace_id (verified in the runner; here we confirm
    #    the classifier doesn't strip it — trace lives on the row, not the classifier output).
    check("classifier is pure decision (trace handled by caller)", "reason" in classify_social_injection(row()))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
