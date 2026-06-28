#!/usr/bin/env python3
"""P0-5: hybrid large-float social scout handling.

Large-float verified social/momentum names are RETAINED (not discarded), clearly labelled
LARGE FLOAT / MANUAL REVIEW, and can never become a standard micro-cap momentum_scalp or use
its fast-path. Social-only names stay WATCH/WAIT.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from social_route_policy import route_social_candidate, ROUTES, FLOAT_CLASSES  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    base = {"symbol": "X", "mention_count": 50, "sources": ["reddit"], "strategy_tags": []}
    ver = {"catalyst_verified": True, "catalyst_source": "news"}

    # 1. Micro-cap verified → standard momentum_scalp / GO.
    r = route_social_candidate(base, {"price": 5, "rvol": 7, "float_m": 8, "gap_pct": 6}, ver)
    check("micro verified → momentum_scalp/GO", r["route"] == "momentum_scalp" and r["actionability"] == "GO")
    check("micro is micro_float, no scout label", r["float_class"] == "micro_float" and r["scout_label"] is None)

    # 2. Large-float verified momentum → scout / MANUAL_REVIEW with full labelling.
    r = route_social_candidate(base, {"price": 12, "rvol": 7, "float_m": 50, "gap_pct": 4}, ver)
    check("large verified → scout or meme route",
          r["route"] in ("large_float_social_scout", "meme_squeeze_momentum"))
    check("large verified → MANUAL_REVIEW", r["actionability"] == "MANUAL_REVIEW")
    check("large verified → float_class large_float", r["float_class"] == "large_float")
    check("large verified → scout_label set", r["scout_label"] == "large_float_social_scout")
    check("large verified → manual_review_required", r["manual_review_required"] is True)
    check("large verified → operator_label LARGE FLOAT", "LARGE FLOAT" in (r["operator_label"] or ""))
    check("large verified is NEVER momentum_scalp", r["strategy_id"] != "momentum_scalp")
    check("large verified is NEVER GO", r["actionability"] != "GO")

    # 3. Large-float verified squeeze → meme_squeeze_momentum with scout sublabel.
    r = route_social_candidate({**base, "sample_content": "short squeeze gamma incoming"},
                               {"price": 18, "rvol": 12, "float_m": 80, "gap_pct": 9}, ver)
    check("large squeeze → meme_squeeze_momentum", r["route"] == "meme_squeeze_momentum")
    check("large squeeze keeps scout sublabel", r["scout_label"] == "large_float_social_scout")
    check("large squeeze is large_float + manual review",
          r["float_class"] == "large_float" and r["manual_review_required"] is True)

    # 4. Social-only large-float (unverified) → WATCH/WAIT only, never scout-GO.
    r = route_social_candidate(base, {"price": 12, "rvol": 7, "float_m": 50, "gap_pct": 6}, {})
    check("social-only large → watch_only", r["route"] == "watch_only")
    check("social-only large never actionable", r["actionability"] in ("WATCH", "WAIT"))
    check("social-only large is social_only", r["social_only"] is True)

    # 5. Output contract: scout label is one consistent value; route in allowed set.
    check("route in allowed ROUTES", r["route"] in ROUTES)
    check("float_class in allowed set", r["float_class"] in FLOAT_CLASSES)

    # 6. The scout config exists and is non-intraday (cannot use momentum_scalp fast-path).
    import proposal_lifecycle as pl
    check("large_float_social_scout NOT in INTRADAY_STRATEGIES",
          "large_float_social_scout" not in pl.INTRADAY_STRATEGIES)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
