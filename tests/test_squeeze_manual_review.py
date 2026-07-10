#!/usr/bin/env python3
"""Tests for reverse-split squeeze → MANUAL_REVIEW lane."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from squeeze_manual_review import (  # noqa: E402
    apply_squeeze_manual_fields,
    attach_squeeze_manual_tags,
    classify_ticker_risk,
    is_halt_risk_hard_block,
)


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True

    row = {"symbol": "GMM", "price": 4.06, "float_m": 1.68, "relative_volume": 225, "gap_percent": 61}
    risk = classify_ticker_risk("GMM", row)
    # May be squeeze_manual if yfinance returns split for GMM, else score
    if risk["action"] == "squeeze_manual":
        ok &= check("GMM classifies squeeze_manual when R/S present", True)
        scored = apply_squeeze_manual_fields(
            {"symbol": "GMM", "score": 0, "rvol": 225, "gap_pct": "61", "change_pct": "99"},
            rs_reason=risk["reasons"],
        )
        ok &= check("GMM decision MANUAL_REVIEW", scored["decision"] == "MANUAL_REVIEW")
        ok &= check("GMM not disqualified", scored["disqualified"] is False)
        ok &= check("GMM awareness SQUEEZE", scored["awareness_status"] == "SQUEEZE")
        ok &= check("GMM score bumped", scored["score"] >= 30)
    else:
        ok &= check("GMM classify without live yfinance", risk["action"] == "score")

    ok &= check("halt risk block", is_halt_risk_hard_block({"float_m": 0.3, "rvol": 60}))
    ok &= check("not halt risk", not is_halt_risk_hard_block({"float_m": 1.7, "rvol": 225}))

    tickers = [{
        "symbol": "GMM",
        "decision": "AVOID",
        "disqualified": True,
        "disqualification_reason": "REVERSE_SPLIT: 0.02:1 on 2026-06-11 — delisting avoidance",
        "rvol": 225,
        "gap_pct": "61",
        "float_m": 1.68,
    }]
    n = attach_squeeze_manual_tags(tickers)
    ok &= check("attach upgrades DQ row", n == 1)
    ok &= check("attach sets MANUAL_REVIEW", tickers[0]["decision"] == "MANUAL_REVIEW")

    if not ok:
        sys.exit(1)
    print("All squeeze_manual_review checks passed.")


if __name__ == "__main__":
    main()