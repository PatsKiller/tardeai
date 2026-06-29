#!/usr/bin/env python3
"""P0-2/P0-6: SEC/Form 4 is a SUPPORTING catalyst-evidence source — recent open-market insider buys
contribute the catalyst_evidence pillar when relevant + recent, but NEVER create GO, never bypass
gates, and never satisfy social_velocity."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from sec_form4_source_maturity import (classify_insider_context, sec_form4_catalyst_evidence,  # noqa: E402
                                       score_source, CATALYST_RELEVANT_DAYS)
from social_scout_pillars import evaluate_social_scout_pillars  # noqa: E402
from social_route_policy import route_social_candidate  # noqa: E402

PASS, FAIL = [], []
TODAY = date(2026, 6, 29)
FULL = {"configured": True, "scheduled": True, "tested": True, "monitored": True,
        "traceable": True, "integrated": True, "safe_fail": True}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- classify_insider_context ----
    recent_buy = [{"transaction_type": "P", "filing_date": (TODAY - timedelta(days=2)).isoformat(),
                   "total_value": 250000, "sec_url": "https://sec.gov/x"}]
    c = classify_insider_context(recent_buy, now=TODAY)
    check("recent open-market buy → catalyst_relevant", c["catalyst_relevant"] is True)
    check("recent buy direction insider_buy", c["direction"] == "insider_buy")
    check("recent buy carries evidence url", c["evidence_url"] == "https://sec.gov/x")
    check("confidence moderate, not a trigger", 0 < c["confidence"] < 1)

    stale_buy = [{"transaction_type": "P", "filing_date": (TODAY - timedelta(days=30)).isoformat(),
                  "total_value": 250000, "sec_url": "u"}]
    check("stale buy NOT catalyst_relevant", classify_insider_context(stale_buy, now=TODAY)["catalyst_relevant"] is False)

    sell_only = [{"transaction_type": "S", "filing_date": (TODAY - timedelta(days=1)).isoformat(),
                  "total_value": 999999, "sec_url": "u"}]
    cs = classify_insider_context(sell_only, now=TODAY)
    check("sell-only NOT catalyst_relevant", cs["catalyst_relevant"] is False)
    check("sell-only direction insider_sell", cs["direction"] == "insider_sell")

    # ---- sec_form4_catalyst_evidence ----
    check("flagged recent insider buy → catalyst evidence",
          sec_form4_catalyst_evidence({"sec_form4_insider_buy": True, "sec_form4_age_days": 2}) is True)
    check("stale insider buy → NOT catalyst evidence",
          sec_form4_catalyst_evidence({"sec_form4_insider_buy": True, "sec_form4_age_days": 30}) is False)
    check("no SEC flag → NOT catalyst evidence", sec_form4_catalyst_evidence({}) is False)

    # ---- score_source ----
    check("4.5 when all criteria met, live obs pending", score_source(FULL, True, True, live_observed=False) == 4.5)
    check("5.0 only with live observation + fresh coverage", score_source(FULL, True, True, live_observed=True) == 5.0)
    check("3.0 when a 4.5 criterion missing", score_source({**FULL, "integrated": False}, True, True, True) == 3.0)

    # ---- Pillar integration (P0-6): SEC insider buy contributes catalyst_evidence ----
    # Finviz metrics + a recent SEC insider buy, but NO social mentions/sources and NO verified news.
    p = evaluate_social_scout_pillars(
        {"symbol": "SEC", "mention_count": 0, "sources": []},
        {"price": 6.0, "rvol": 7.0, "float_m": 9.0, "gap_pct": 6.0},
        {"sec_form4_insider_buy": True, "sec_form4_age_days": 2})   # SEC catalyst context, not news
    check("SEC insider buy satisfies catalyst_evidence pillar", "catalyst_evidence" in p["pillars_met"])
    check("SEC alone still does NOT satisfy social_velocity", "social_velocity" not in p["pillars_met"])

    # ---- SEC/Form 4 can NEVER create GO by itself ----
    # SEC catalyst context is NOT a verified news catalyst → route policy keeps it social-only / never GO.
    r = route_social_candidate(
        {"symbol": "SEC", "mention_count": 0, "sources": []},
        {"price": 6.0, "rvol": 7.0, "float_m": 9.0, "gap_pct": 6.0},
        {"sec_form4_insider_buy": True, "sec_form4_age_days": 2})   # no catalyst_verified
    check("SEC-only catalyst is NEVER GO", r["actionability"] != "GO")
    check("SEC-only candidate not tradeable", r["not_tradeable"] is True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
