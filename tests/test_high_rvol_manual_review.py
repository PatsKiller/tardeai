#!/usr/bin/env python3
"""Tests for high-RVOL WAIT → MANUAL_REVIEW lane."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from high_rvol_manual_review import (  # noqa: E402
    apply_high_rvol_manual_fields,
    attach_high_rvol_manual_tags,
    qualifies_high_rvol_manual,
)


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True

    wait_row = {"symbol": "IOTR", "decision": "WAIT", "rvol": 12.5, "gap_pct": 45, "score": 32}
    ok &= check("IOTR qualifies", qualifies_high_rvol_manual(wait_row))
    upgraded = apply_high_rvol_manual_fields(dict(wait_row))
    ok &= check("IOTR → MANUAL_REVIEW", upgraded["decision"] == "MANUAL_REVIEW")
    ok &= check("IOTR awareness HIGH_RVOL", upgraded["awareness_status"] == "HIGH_RVOL")
    ok &= check("IOTR not tradeable", upgraded["not_tradeable"] is True)

    low_rvol = {"symbol": "X", "decision": "WAIT", "rvol": 3.0}
    ok &= check("low RVOL skipped", not qualifies_high_rvol_manual(low_rvol))

    squeeze = {"symbol": "GMM", "decision": "WAIT", "rvol": 200, "awareness_status": "SQUEEZE"}
    ok &= check("squeeze skipped", not qualifies_high_rvol_manual(squeeze))

    tickers = [
        {"symbol": "JZXN", "decision": "WAIT", "rvol": 9.2, "gap_pct": 20},
        {"symbol": "BATL", "decision": "WAIT", "rvol": 8.1},
        {"symbol": "GO1", "decision": "GO", "rvol": 20},
    ]
    n = attach_high_rvol_manual_tags(tickers)
    ok &= check("attach upgrades 2 WAIT rows", n == 2)
    ok &= check("GO untouched", tickers[2]["decision"] == "GO")

    if not ok:
        sys.exit(1)
    print("All high_rvol_manual_review checks passed.")


if __name__ == "__main__":
    main()