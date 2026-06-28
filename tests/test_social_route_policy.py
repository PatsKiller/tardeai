#!/usr/bin/env python3
"""P0-5: deterministic social routing matrix.

Verifies each routing class: social-only → watch_only (never GO), verified micro-cap →
momentum_scalp, large-float squeeze → meme_squeeze_momentum (manual review), income tags →
portfolio_agents, missing Finviz → WAIT/never-GO, and that unverified can never reach GO.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from social_route_policy import route_social_candidate, ROUTES, ACTIONABILITY  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # 1. Social-only high-score (no verified catalyst) → watch_only, NOT momentum_scalp, never GO.
    r = route_social_candidate(
        {"symbol": "SOCO", "mention_count": 80, "sources": ["reddit", "stocktwits"], "strategy_tags": []},
        {"price": 4.0, "rvol": 9.0, "float_m": 6.0, "gap_pct": 7.0},
        {})  # no catalyst
    check("social-only routes watch_only", r["route"] == "watch_only")
    check("social-only never GO", r["actionability"] != "GO")
    check("social-only flagged social_only=True", r["social_only"] is True)
    check("social-only reason SOCIAL_ONLY_UNVERIFIED", "SOCIAL_ONLY_UNVERIFIED" in r["reason_codes"])

    # 2. Verified micro-cap high-RVOL → momentum_scalp (GO eligible).
    r = route_social_candidate(
        {"symbol": "SCLP", "mention_count": 30, "sources": ["stocktwits"], "strategy_tags": []},
        {"price": 5.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 4.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("verified micro-cap routes momentum_scalp", r["route"] == "momentum_scalp")
    check("verified micro-cap actionability GO", r["actionability"] == "GO")
    check("verified micro-cap strategy_id set", r["strategy_id"] == "momentum_scalp")

    # 3. Large-float squeeze (verified) → meme_squeeze_momentum, MANUAL REVIEW.
    r = route_social_candidate(
        {"symbol": "MEME", "mention_count": 200, "sources": ["reddit"],
         "strategy_tags": [], "sample_content": "massive short squeeze incoming, shorts trapped"},
        {"price": 18.0, "rvol": 12.0, "float_m": 80.0, "gap_pct": 9.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("large-float squeeze routes meme_squeeze_momentum", r["route"] == "meme_squeeze_momentum")
    check("squeeze requires manual review", r["actionability"] == "MANUAL_REVIEW")
    check("squeeze actionability is not GO", r["actionability"] != "GO")

    # 4. Income/retirement tag → portfolio_agents.
    r = route_social_candidate(
        {"symbol": "DIVY", "mention_count": 10, "sources": ["reddit"], "strategy_tags": ["dividend", "income"]},
        {"price": 60.0, "rvol": 1.2, "float_m": 500.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("income tag routes portfolio_agents", r["route"] == "portfolio_agents")
    check("portfolio route not GO", r["actionability"] != "GO")

    # 5. Missing Finviz (no rvol) → WAIT/never-GO.
    r = route_social_candidate(
        {"symbol": "NODATA", "mention_count": 50, "sources": ["reddit"], "strategy_tags": []},
        {"price": None, "rvol": None},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("missing finviz routes watch_only/reject", r["route"] in ("watch_only", "reject"))
    check("missing finviz never GO", r["actionability"] != "GO")
    check("missing finviz reason MISSING_FINVIZ_DATA", "MISSING_FINVIZ_DATA" in r["reason_codes"])

    # 6. Verified but out of all bounds (huge price, no squeeze) → reject.
    r = route_social_candidate(
        {"symbol": "BIG", "mention_count": 5, "sources": ["reddit"], "strategy_tags": []},
        {"price": 400.0, "rvol": 2.0, "float_m": 5.0, "gap_pct": 1.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("verified out-of-bounds rejects", r["route"] == "reject")

    # 7. Unverified can NEVER route to GO (sweep a few metric combos).
    go_leaked = False
    for fm, pr, rv in [(6, 4, 9), (3, 2, 12), (15, 20, 6)]:
        rr = route_social_candidate(
            {"symbol": "U", "mention_count": 99, "sources": ["reddit"], "strategy_tags": []},
            {"price": pr, "rvol": rv, "float_m": fm, "gap_pct": 8.0}, {})
        if rr["actionability"] == "GO":
            go_leaked = True
    check("unverified catalyst NEVER routes GO", not go_leaked)

    # 8. Return shape sanity.
    check("route value in allowed set", r["route"] in ROUTES)
    check("actionability in allowed set", r["actionability"] in ACTIONABILITY)
    check("trace_id passthrough", route_social_candidate({"symbol": "T"}, {"price": 1, "rvol": 1},
                                                         {}, trace_id="abc")["trace_id"] == "abc")
    check("reason_codes are stable strings", all(isinstance(c, str) for c in r["reason_codes"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
