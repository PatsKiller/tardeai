#!/usr/bin/env python3
"""Tests for P2-2 ticker alias resolution."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from ticker_alias import resolve_symbol, STATIC_ALIASES  # noqa: E402


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True
    ok &= check("static VRX alias defined", STATIC_ALIASES.get("VRX") == "VRAX")

    res = resolve_symbol("VRX", ROOT, trade_date=date(2026, 7, 9), universe={"VRAX", "GMM"})
    ok &= check("VRX resolves to VRAX", res["resolved_symbol"] == "VRAX")
    ok &= check("VRX symbol_candidate set", res["symbol_candidate"] == "VRX")
    ok &= check("VRX confidence high", res["confidence"] >= 0.85)

    exact = resolve_symbol("GMM", ROOT, universe={"GMM", "VRAX"})
    ok &= check("exact match unchanged", exact["resolved_symbol"] == "GMM" and exact["symbol_candidate"] is None)

    prefix = resolve_symbol("IOT", ROOT, universe={"IOTR", "ABC"})
    ok &= check("prefix extension", prefix["resolved_symbol"] == "IOTR")

    if not ok:
        sys.exit(1)
    print("All ticker alias checks passed.")


if __name__ == "__main__":
    main()