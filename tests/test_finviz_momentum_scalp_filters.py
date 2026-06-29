#!/usr/bin/env python3
"""P0-3: the Finviz momentum-scalp screen filters MUST stay aligned with momentum_scalp.yaml and
must never let an unverified / social-only candidate become GO. Allows Social Scout surfacing at 2-4
pillars without GO. Pure (yaml + route policy) — no DB, no network."""
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from social_route_policy import route_social_candidate  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def _load(p):
    with open(os.path.join(ROOT, p)) as fh:
        return yaml.safe_load(fh)


def main():
    fv = _load("config/finviz_momentum_scalp_screen.yaml")["momentum_scalp_finviz_screen"]
    ms = _load("config/strategies/momentum_scalp.yaml")["screen_filters"]
    tr = fv["tradeable"]

    # --- Alignment with momentum_scalp.yaml (authoritative) ---
    check("finviz price.max == momentum_scalp max_price", tr["price"]["max"] == ms["max_price"])
    check("finviz price.min == momentum_scalp min_price", tr["price"]["min"] == ms["min_price"])
    check("finviz float_m.max == momentum_scalp max_float_m", tr["float_m"]["max"] == ms["max_float_m"])
    check("finviz rvol.min == momentum_scalp min_rvol", tr["rvol"]["min"] == ms["min_rvol"])
    check("finviz gap min_abs == momentum_scalp min_gap_pct", tr["gap_pct"]["min_abs"] == ms["min_gap_pct"])
    check("finviz volume.min_shares == momentum_scalp min_volume", tr["volume"]["min_shares"] == ms["min_volume"])
    check("finviz score.min >= momentum_scalp min_score", tr["score"]["min"] >= ms["min_score"])

    # --- Drift guards (the build FAILS if these regress) ---
    check("float max never above 20M for momentum_scalp GO", tr["float_m"]["max"] <= 20)
    check("RVOL min never below 5 for momentum_scalp GO", tr["rvol"]["min"] >= 5.0)
    check("price max never above 25 for standard momentum_scalp", tr["price"]["max"] <= 25.0)
    check("gap min never below 5%", tr["gap_pct"]["min_abs"] >= 5.0)

    # --- GO requires verified catalyst + momentum_scalp route + GO actionability ---
    check("catalyst verification required for momentum_scalp GO",
          tr["catalyst"]["verified_required_for_momentum_scalp"] is True
          and tr["catalyst"]["required_for_go"] is True)
    check("route required == momentum_scalp", tr["route_required"] == "momentum_scalp")
    check("actionability required == GO", tr["actionability_required"] == "GO")

    # --- Social Scout lane: 2-4 pillars surfaces, never GO ---
    sc = fv["scout"]
    check("scout min_pillars == 2", sc["min_pillars"] == 2)
    check("social-only max actionability is SCOUT (never GO)", sc["social_only_max_actionability"] == "SCOUT")
    check("large-float manual-review only", sc["large_float_manual_review_only"] is True)
    check("social_velocity NOT a Finviz pillar (needs social evidence)",
          "social_velocity" not in fv["scout"]["finviz_pillars"])

    # --- Behavioral: a candidate meeting EVERY tradeable Finviz metric but UNVERIFIED can never GO ---
    unverified = route_social_candidate(
        {"symbol": "UNV", "mention_count": 90, "sources": ["reddit", "stocktwits"]},
        {"price": tr["price"]["max"] - 1, "rvol": tr["rvol"]["min"] + 2,
         "float_m": tr["float_m"]["max"] - 2, "gap_pct": tr["gap_pct"]["min_abs"] + 2}, {})  # no catalyst
    check("unverified meeting all metrics is NEVER GO", unverified["actionability"] != "GO")
    check("unverified is social_only / not tradeable", unverified["not_tradeable"] is True)

    # A verified micro-float candidate routes momentum_scalp/GO through the normal path.
    verified = route_social_candidate(
        {"symbol": "VER", "mention_count": 30, "sources": ["stocktwits"]},
        {"price": 5.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 6.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("verified micro-float CAN route momentum_scalp/GO", verified["actionability"] == "GO")

    # A large-float verified candidate is manual-review only, never momentum_scalp.
    large = route_social_candidate(
        {"symbol": "LRG", "mention_count": 120, "sources": ["reddit"]},
        {"price": 18.0, "rvol": 7.0, "float_m": 80.0, "gap_pct": 6.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    check("large-float verified is manual-review only (not momentum_scalp)",
          large["actionability"] == "MANUAL_REVIEW" and large["strategy_id"] != "momentum_scalp")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
