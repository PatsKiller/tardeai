#!/usr/bin/env python3
"""Tests for micro-float → MANUAL_REVIEW lane."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from micro_float_manual_review import (  # noqa: E402
    apply_micro_float_manual_fields,
    attach_micro_float_manual_tags,
    qualifies_micro_float_manual,
)
from squeeze_manual_review import classify_ticker_risk  # noqa: E402


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True
    row = {"symbol": "BJDX", "float_m": 0.7, "relative_volume": 23.6, "price": 2.5, "gap_percent": 40}
    risk = classify_ticker_risk("BJDX", row)
    ok &= check("BJDX micro_float_manual", risk["action"] == "micro_float_manual")

    halt = {"symbol": "X", "float_m": 0.3, "relative_volume": 60}
    ok &= check("halt still hard_dq", classify_ticker_risk("X", halt)["action"] == "hard_dq")

    upgraded = apply_micro_float_manual_fields({"symbol": "CLRO", "decision": "AVOID", "disqualified": True,
        "disqualification_reason": "MICRO_FLOAT_RVOL: 0.7M float with 23.6x RVOL", "rvol": 23.6, "float_m": 0.7})
    ok &= check("CLRO MANUAL_REVIEW", upgraded["decision"] == "MANUAL_REVIEW")
    ok &= check("CLRO MICRO_FLOAT", upgraded["awareness_status"] == "MICRO_FLOAT")

    tickers = [{"symbol": "BJDX", "decision": "AVOID", "disqualified": True,
                "disqualification_reason": "MICRO_FLOAT_RVOL: 0.7M float with 23.6x RVOL", "rvol": 23.6, "float_m": 0.7}]
    ok &= check("attach", attach_micro_float_manual_tags(tickers) == 1)

    if not ok:
        sys.exit(1)
    print("All micro_float_manual_review checks passed.")


if __name__ == "__main__":
    main()