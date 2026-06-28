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

    # ====================== P0-2: Social Scout pillar surfacing ======================

    # S1. Social-only with social velocity + market confirmation (no catalyst, no float) =
    #     Social Scout 2/5, watch_only, never GO.
    r = route_social_candidate(
        {"symbol": "SCT2", "mention_count": 80, "sources": ["reddit", "stocktwits"], "strategy_tags": []},
        {"price": 4.0, "rvol": 9.0, "float_m": None, "gap_pct": 7.0},  # no float → structure/fit fail
        {})  # no catalyst
    check("S1 social-only 2/5 scout_status", r["scout_status"] == "SOCIAL_SCOUT")
    check("S1 pillar_count == 2", r["scout_pillar_count"] == 2)
    check("S1 operator_pill 'SOCIAL SCOUT · 2/5'", r["operator_pill"] == "SOCIAL SCOUT · 2/5")
    check("S1 never GO (SCOUT actionability)", r["actionability"] == "SCOUT")
    check("S1 route stays watch_only", r["route"] == "watch_only")
    check("S1 not_validation_ready", r["not_validation_ready"] is True)
    check("S1 not_tradeable", r["not_tradeable"] is True)
    check("S1 strategy_id null (no signal)", r["strategy_id"] is None)
    check("S1 needs catalyst tooltip", "NEEDS_CATALYST" in r["reason_codes"])

    # S2. Social velocity + catalyst but missing market confirmation/structure = Social Scout 2/5.
    r = route_social_candidate(
        {"symbol": "SCT2B", "mention_count": 40, "sources": ["reddit"], "strategy_tags": []},
        {"price": None, "rvol": None},  # no market data → confirmation + structure missing
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("S2 velocity+catalyst 2/5 scout", r["scout_status"] == "SOCIAL_SCOUT")
    check("S2 pillar_count == 2", r["scout_pillar_count"] == 2)
    check("S2 operator_pill 2/5", r["operator_pill"] == "SOCIAL SCOUT · 2/5")
    check("S2 never GO", r["actionability"] != "GO")
    check("S2 needs market confirmation", "NEEDS_MARKET_CONFIRMATION" in r["reason_codes"])

    # S3. 4/5 (everything but catalyst) = Social Scout 4/5, never GO.
    r = route_social_candidate(
        {"symbol": "SCT4", "mention_count": 60, "sources": ["reddit", "stocktwits"], "strategy_tags": []},
        {"price": 5.0, "rvol": 8.0, "float_m": 9.0, "gap_pct": 6.0},  # micro metrics, but unverified
        {})  # no catalyst
    check("S3 4/5 scout_status", r["scout_status"] == "SOCIAL_SCOUT")
    check("S3 pillar_count == 4", r["scout_pillar_count"] == 4)
    check("S3 operator_pill 'SOCIAL SCOUT · 4/5'", r["operator_pill"] == "SOCIAL SCOUT · 4/5")
    check("S3 never GO (no catalyst)", r["actionability"] != "GO")
    check("S3 not_validation_ready", r["not_validation_ready"] is True)

    # S4. Verified micro-float meeting all momentum_scalp gates STILL routes normal GO (no scout pill).
    r = route_social_candidate(
        {"symbol": "GOOD", "mention_count": 30, "sources": ["stocktwits"], "strategy_tags": []},
        {"price": 5.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 4.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("S4 verified micro routes momentum_scalp", r["route"] == "momentum_scalp")
    check("S4 GO preserved", r["actionability"] == "GO")
    check("S4 GO suppresses scout pill", r["operator_pill"] is None and r["scout_status"] == "NONE")
    check("S4 GO is validation/tradeable eligible via normal path",
          r["not_tradeable"] is False and r["not_validation_ready"] is False)

    # S5. Large-float with 2+ pillars = Social Scout / LARGE FLOAT, manual-review only, never momentum_scalp.
    r = route_social_candidate(
        {"symbol": "LRGF", "mention_count": 200, "sources": ["reddit"], "strategy_tags": []},
        {"price": 18.0, "rvol": 7.0, "float_m": 80.0, "gap_pct": 4.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("S5 large-float scout route", r["route"] in ("large_float_social_scout", "meme_squeeze_momentum"))
    check("S5 LARGE FLOAT pill", "LARGE FLOAT" in (r["operator_pill"] or ""))
    check("S5 manual review only", r["actionability"] == "MANUAL_REVIEW" and r["manual_review_required"])
    check("S5 never momentum_scalp", r["strategy_id"] != "momentum_scalp")
    check("S5 not validation-fast-path eligible", r["not_validation_ready"] is True)

    # S6. A Social Scout can NEVER be validation-fast-path eligible (sweep scout-producing combos).
    scout_leak = False
    for fm, pr, rv, cat in [(None, 4, 9, {}), (9, 5, 8, {}), (80, 18, 7,
                            {"catalyst_verified": True, "catalyst_source": "news"})]:
        rr = route_social_candidate(
            {"symbol": "X", "mention_count": 60, "sources": ["reddit", "stocktwits"]},
            {"price": pr, "rvol": rv, "float_m": fm, "gap_pct": 6.0}, cat)
        if rr["scout_status"] == "SOCIAL_SCOUT" and (not rr["not_validation_ready"]
                                                     or rr["actionability"] == "GO"):
            scout_leak = True
    check("S6 no Social Scout is validation-ready or GO", not scout_leak)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
