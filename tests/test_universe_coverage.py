#!/usr/bin/env python3
"""Tests for Finviz top-gainer universe injection."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from universe_coverage import inject_prime_setup_universe  # noqa: E402


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True
    tickers = [{"symbol": "AAPL", "price": 200, "change_percent": 1}]
    n = inject_prime_setup_universe(tickers, ROOT, limit=5, min_change_pct=5.0)
    ok &= check("inject runs", n >= 0)
    if n > 0:
        injected = [t for t in tickers if t.get("_universe_inject")]
        ok &= check("injected tagged", len(injected) == n)
        ok &= check("pre_score boost", all(t.get("_pre_score", 0) >= 12 for t in injected))
    if not ok:
        sys.exit(1)
    print("All universe_coverage checks passed.")


if __name__ == "__main__":
    main()