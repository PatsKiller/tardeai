#!/usr/bin/env python3
"""P1: route-policy replay — retains large-float scouts, social-only never GO."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from replay_social_route_policy import build, to_markdown  # noqa: E402
from social_route_policy import route_social_candidate  # noqa: E402
from continuous_runner import classify_social_injection  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # 1. Live replay structure + invariants.
    r = build(365)
    check("replay structured", "status" in r)
    if not r.get("ok"):
        WARN.append("db")
        print(f"  [WARN] {r.get('warnings')}")
    else:
        check("counts all route buckets", "route_distribution" in r)
        check("old vs new injection comparison present", "injection_comparison" in r)
        check("social-only GO leaks == 0", r["social_only_go_leaks"] == 0)
        check("markdown renders", "Social Route Policy Replay" in to_markdown(r))

    # 2. Synthetic demonstration: a verified large-float name is RETAINED as a scout, not discarded.
    route = route_social_candidate(
        {"symbol": "BIGF", "mention_count": 100, "sources": ["reddit"], "strategy_tags": []},
        {"price": 12, "rvol": 8, "float_m": 60, "gap_pct": 5},
        {"catalyst_verified": True, "catalyst_source": "news"}, trace_id="t")
    inj = classify_social_injection({"decision": "GO", "route": route["route"],
                                     "route_actionability": route["actionability"],
                                     "route_strategy_id": route["strategy_id"],
                                     "catalyst_verified": True, "rvol": 8, "float_m": 60, "price": 12})
    check("large-float scout retained (injectable)", inj["injectable"])
    check("large-float scout is manual-review, not tradeable",
          inj["manual_review_required"] and not inj["tradeable"])
    check("large-float scout not momentum_scalp", inj["strategy_id"] != "momentum_scalp")

    # 3. Social-only large-float → not injected, never GO.
    so = route_social_candidate(
        {"symbol": "SOC", "mention_count": 200, "sources": ["reddit"], "strategy_tags": []},
        {"price": 12, "rvol": 8, "float_m": 60, "gap_pct": 5}, {}, trace_id="t")
    check("social-only never GO", so["actionability"] != "GO")
    inj2 = classify_social_injection({"decision": "WAIT", "route": so["route"],
                                      "route_actionability": so["actionability"],
                                      "route_strategy_id": so["strategy_id"], "catalyst_verified": False})
    check("social-only not injected as tradeable", not inj2.get("tradeable"))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
