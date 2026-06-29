#!/usr/bin/env python3
"""P0-1: deterministic 5-pillar Social Scout scoring.

Verifies threshold behavior (0/1 → no pill; 2-4 → Scout pill; 5 ≠ GO), the exact output shape,
and the HARD invariant that a Scout is always not_tradeable + not_validation_ready.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from social_scout_pillars import (evaluate_social_scout_pillars, PILLARS,  # noqa: E402
                                   SCOUT_STATUS, NO_SCOUT_STATUS, OPERATOR_COLOR_TOKEN)

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- 0/5: nothing present → no Social Scout pill ----
    r = evaluate_social_scout_pillars(
        {"symbol": "ZERO", "mention_count": 0, "sources": []},
        {"price": None, "rvol": None, "float_m": None},
        {})
    check("0/5 pillar_count == 0", r["pillar_count"] == 0)
    check("0/5 no scout status", r["scout_status"] == NO_SCOUT_STATUS)
    check("0/5 no operator_pill", r["operator_pill"] is None)
    check("0/5 still not_tradeable + not_validation_ready",
          r["not_tradeable"] and r["not_validation_ready"])

    # ---- 1/5: only one pillar (social velocity via 2 sources) → still no pill ----
    r = evaluate_social_scout_pillars(
        {"symbol": "ONE", "mention_count": 50, "sources": ["reddit", "stocktwits"]},
        {"price": None, "rvol": None, "float_m": None},  # no confirmation/structure/fit
        {})
    check("1/5 exactly one pillar", r["pillar_count"] == 1)
    check("1/5 no scout status", r["scout_status"] == NO_SCOUT_STATUS)
    check("1/5 no operator_pill", r["operator_pill"] is None)

    # ---- 2/5: social velocity + market confirmation, no catalyst → Social Scout 2/5, never GO ----
    r = evaluate_social_scout_pillars(
        {"symbol": "TWO", "mention_count": 40, "sources": ["reddit"]},
        {"price": None, "rvol": 6.0, "float_m": None},  # confirmation yes, structure/fit no
        {})
    check("2/5 social_velocity + market_confirmation met",
          set(r["pillars_met"]) == {"social_velocity", "market_confirmation"})
    check("2/5 pillar_count == 2", r["pillar_count"] == 2)
    check("2/5 scout_status SOCIAL_SCOUT", r["scout_status"] == SCOUT_STATUS)
    check("2/5 operator_pill exact", r["operator_pill"] == "SOCIAL SCOUT · 2/5")
    check("2/5 subtitle 'Not quite there yet'", r["operator_subtitle"] == "Not quite there yet")
    check("2/5 color token socialScout", r["operator_color_token"] == OPERATOR_COLOR_TOKEN)
    check("2/5 not_validation_ready True", r["not_validation_ready"] is True)
    check("2/5 not_tradeable True", r["not_tradeable"] is True)
    check("2/5 reason codes are SCOUT_ met codes",
          r["reason_codes"] == ["SCOUT_SOCIAL_VELOCITY", "SCOUT_MARKET_CONFIRMATION"])
    check("2/5 missing catalyst → NEEDS_CATALYST", "NEEDS_CATALYST" in r["missing_reason_codes"])

    # ---- 2/5 alt: social velocity + catalyst but NO market confirmation ----
    r = evaluate_social_scout_pillars(
        {"symbol": "TWB", "mention_count": 40, "sources": ["reddit"]},
        {"price": None, "rvol": None, "float_m": None},  # no confirmation
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("2/5-alt velocity+catalyst, no confirmation",
          set(r["pillars_met"]) == {"social_velocity", "catalyst_evidence"})
    check("2/5-alt scout pill 2/5", r["operator_pill"] == "SOCIAL SCOUT · 2/5")
    check("2/5-alt NEEDS_MARKET_CONFIRMATION", "NEEDS_MARKET_CONFIRMATION" in r["missing_reason_codes"])

    # ---- 4/5: everything but catalyst → Social Scout 4/5, never GO ----
    r = evaluate_social_scout_pillars(
        {"symbol": "FOUR", "mention_count": 40, "sources": ["reddit", "stocktwits"]},
        {"price": 6.0, "rvol": 5.0, "float_m": 10.0, "gap_pct": 4.0},
        {})  # no catalyst
    check("4/5 pillar_count == 4", r["pillar_count"] == 4)
    check("4/5 missing only catalyst", r["pillars_missing"] == ["catalyst_evidence"])
    check("4/5 operator_pill exact", r["operator_pill"] == "SOCIAL SCOUT · 4/5")
    check("4/5 scout_status SOCIAL_SCOUT (not GO)", r["scout_status"] == SCOUT_STATUS)
    check("4/5 not_tradeable (pillars alone never tradeable)", r["not_tradeable"] is True)

    # ---- 5/5: all pillars → still NOT GO from the pillar module; still not_tradeable ----
    r = evaluate_social_scout_pillars(
        {"symbol": "FIVE", "mention_count": 40, "sources": ["reddit", "stocktwits"]},
        {"price": 6.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 5.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("5/5 pillar_count == 5", r["pillar_count"] == 5)
    check("5/5 no missing pillars", r["pillars_missing"] == [])
    check("5/5 module does NOT assert tradeable (route policy decides GO)", r["not_tradeable"] is True)
    check("5/5 module does NOT assert validation-ready", r["not_validation_ready"] is True)

    # ---- structure pillar fails on offering/halt risk even with good metrics ----
    r = evaluate_social_scout_pillars(
        {"symbol": "DIL", "mention_count": 40, "sources": ["reddit"],
         "sample_content": "huge dilution risk, shelf offering announced"},
        {"price": 6.0, "rvol": 7.0, "float_m": 8.0},
        {})
    check("structure_tradeability fails on offering/dilution",
          "structure_tradeability" not in r["pillars_met"])

    # ---- portfolio/income tag fails strategy_risk_fit ----
    r = evaluate_social_scout_pillars(
        {"symbol": "DIV", "mention_count": 40, "sources": ["reddit"], "strategy_tags": ["dividend", "income"]},
        {"price": 6.0, "rvol": 7.0, "float_m": 8.0},
        {})
    check("strategy_risk_fit fails for portfolio/income tag",
          "strategy_risk_fit" not in r["pillars_met"])

    # ---- output shape sanity ----
    keys = {"pillar_count", "pillars_met", "pillars_missing", "scout_status", "operator_pill",
            "operator_subtitle", "operator_color_token", "not_validation_ready", "not_tradeable",
            "reason_codes"}
    check("output contains all required keys", keys.issubset(set(r.keys())))
    check("PILLARS has exactly 5", len(PILLARS) == 5)

    # ====================== P0-7: Finviz source → pillar mapping ======================
    # A PURE Finviz candidate (market metrics only, NO social mentions/sources, NO catalyst) meets
    # market_confirmation + structure_tradeability + strategy_risk_fit, but NOT social_velocity
    # (that needs social evidence) and NOT catalyst_evidence — i.e. a 3/5 Social Scout, never GO.
    pure_finviz = evaluate_social_scout_pillars(
        {"symbol": "FVZ", "mention_count": 0, "sources": []},          # no social
        {"price": 6.0, "rvol": 7.0, "float_m": 9.0, "gap_pct": 6.0},   # Finviz metrics
        {})                                                            # no catalyst
    check("pure-Finviz meets market_confirmation", "market_confirmation" in pure_finviz["pillars_met"])
    check("pure-Finviz meets structure_tradeability", "structure_tradeability" in pure_finviz["pillars_met"])
    check("pure-Finviz meets strategy_risk_fit", "strategy_risk_fit" in pure_finviz["pillars_met"])
    check("pure-Finviz does NOT meet social_velocity (needs social evidence)",
          "social_velocity" not in pure_finviz["pillars_met"])
    check("pure-Finviz is a Social Scout (2-4 pillars)", pure_finviz["scout_status"] == SCOUT_STATUS)
    check("pure-Finviz never tradeable", pure_finviz["not_tradeable"] is True)

    # Finviz + verified catalyst (headline) but still NO social → 4/5 (missing only social_velocity).
    finviz_catalyst = evaluate_social_scout_pillars(
        {"symbol": "FVC", "mention_count": 0, "sources": []},
        {"price": 6.0, "rvol": 7.0, "float_m": 9.0, "gap_pct": 6.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("Finviz+catalyst (no social) = 4/5", finviz_catalyst["pillar_count"] == 4)
    check("Finviz+catalyst still missing social_velocity",
          finviz_catalyst["pillars_missing"] == ["social_velocity"])

    # Finviz + social velocity + verified catalyst → 5/5 (all pillars). Still NOT auto-GO — the pillar
    # module keeps not_tradeable/not_validation_ready True; GO is decided ONLY by the route policy.
    full = evaluate_social_scout_pillars(
        {"symbol": "FUL", "mention_count": 40, "sources": ["reddit", "stocktwits"]},  # social velocity
        {"price": 6.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 6.0},                  # Finviz
        {"catalyst_verified": True, "catalyst_source": "news"})                       # catalyst
    check("Finviz+social+catalyst = 5/5", full["pillar_count"] == 5)
    check("5/5 still not tradeable (module never auto-GOs)", full["not_tradeable"] is True)
    check("5/5 still not validation-ready (route policy decides GO)", full["not_validation_ready"] is True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
