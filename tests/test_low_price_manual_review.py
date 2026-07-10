#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from low_price_manual_review import qualifies_low_price_manual, apply_low_price_manual_fields  # noqa: E402
from squeeze_manual_review import classify_ticker_risk  # noqa: E402


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True
    hcwb = {
        "symbol": "HCWB", "decision": "AVOID", "disqualified": True,
        "disqualification_reason": "LOW_PRICE_SPIKE: $1.03 up 205% — pump or split distortion",
        "price": 1.03, "change_pct": 205, "rvol": 12, "float_m": 5.1,
    }
    ok &= check("HCWB qualifies", qualifies_low_price_manual(hcwb))
    apply_low_price_manual_fields(hcwb)
    ok &= check("HCWB MANUAL_REVIEW", hcwb["decision"] == "MANUAL_REVIEW")
    ok &= check("HCWB LOW_PRICE", hcwb["awareness_status"] == "LOW_PRICE")

    risk = classify_ticker_risk("HCWB", {"price": 1.03, "change_pct": 205, "rvol": 12, "float_m": 5.1})
    ok &= check("classify low_price_manual", risk["action"] == "low_price_manual")

    if not ok:
        sys.exit(1)
    print("All low_price_manual_review checks passed.")


if __name__ == "__main__":
    main()