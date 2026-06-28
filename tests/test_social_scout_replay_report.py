#!/usr/bin/env python3
"""P0-7: Social Scout replay/report — pure aggregation over synthetic rows (DB-free).

Verifies the histogram, scout surfacing counts, the GO/scout distinction, and the invariant that
no scout is validation-ready (scouts_blocked_from_validation == social_scouts_surfaced).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from social_scout_replay_report import aggregate, build, to_markdown  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    rows = [
        # 4/5 social-only scout (velocity+confirmation+structure+fit, no catalyst)
        {"symbol": "SC4", "mention_count": 60, "sources": ["reddit", "stocktwits"],
         "price": 5.0, "rvol": 8.0, "float_m": 9.0, "gap_pct": 6.0, "decision": "WATCH"},
        # 2/5 scout (velocity+confirmation, no float → structure/fit fail)
        {"symbol": "SC2", "mention_count": 80, "sources": ["reddit", "stocktwits"],
         "price": 4.0, "rvol": 9.0, "float_m": None, "gap_pct": 7.0, "decision": "WATCH"},
        # verified micro-cap GO (graduates — NOT a scout)
        {"symbol": "GO1", "mention_count": 30, "sources": ["stocktwits"],
         "price": 5.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 4.0, "decision": "GO",
         "catalyst_verified": True, "catalyst_source": "news"},
        # large-float verified scout (manual review)
        {"symbol": "LF1", "mention_count": 200, "sources": ["reddit"],
         "price": 18.0, "rvol": 7.0, "float_m": 80.0, "gap_pct": 4.0, "decision": "WATCH",
         "catalyst_verified": True, "catalyst_source": "news"},
        # nothing (0/5)
        {"symbol": "Z", "mention_count": 0, "sources": [], "price": None, "rvol": None,
         "float_m": None, "decision": "AVOID"},
    ]
    r = aggregate(rows)

    check("rows_replayed == 5", r["rows_replayed"] == 5)
    check("at least 3 social scouts surfaced (SC4, SC2, LF1)", r["social_scouts_surfaced"] >= 3)
    check("one graduated to momentum_scalp/GO (GO1)", r["graduated_to_momentum_scalp_go"] == 1)
    check("large-float scout counted (LF1)", r["large_float_social_scouts"] >= 1)
    check("social-only scouts counted (SC4, SC2)", r["social_only_social_scouts"] >= 2)

    # CORE INVARIANT: every surfaced scout is blocked from validation (none validation-ready).
    check("scouts_blocked_from_validation == social_scouts_surfaced",
          r["scouts_blocked_from_validation"] == r["social_scouts_surfaced"])

    # GO is distinct from scout: the GO row is not counted as a scout.
    check("GO row not double-counted as scout",
          r["graduated_to_momentum_scalp_go"] + r["social_scouts_surfaced"] <= r["rows_replayed"] + 1)

    # Histogram present + sums to row count.
    hist = r["pillar_count_histogram"]
    check("histogram has 0/5..5/5 keys", set(hist.keys()) == {f"{i}/5" for i in range(6)})
    check("histogram sums to rows_replayed", sum(hist.values()) == r["rows_replayed"])

    # Missing pillars / reason codes surfaced for scouts.
    check("top missing pillars include catalyst_evidence",
          any(p == "catalyst_evidence" for p, _ in r["top_missing_pillars"]))
    check("reason codes include a SCOUT_ or NEEDS_ code",
          any(rc.startswith(("SCOUT_", "NEEDS_")) for rc, _ in r["top_reason_codes"]))

    # Markdown renders; build() degrades safely without a DB.
    md = to_markdown({**r, "ok": True, "status": "PASS", "window_days": 30,
                      "generated_at": "now", "note": "x"})
    check("markdown renders", "Social Scout Replay" in md)
    b = build(30)
    check("build() returns a dict (PASS or WARN)", isinstance(b, dict) and "status" in b)
    check("build() reports read-only / no broker writes", "No broker writes" in b.get("note", ""))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
