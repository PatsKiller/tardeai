#!/usr/bin/env python3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from finviz_snapshot import nearest_prime_setup_file, lookup_finviz_symbol  # noqa: E402


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True
    td = date(2026, 7, 8)
    ref = datetime(2026, 7, 8, 11, 28, 20)
    path = nearest_prime_setup_file(ROOT, td, ref)
    ok &= check("nearest file found", path is not None)
    if path:
        ok &= check("nearest is 112820", "112820" in path.name)

    scan = {"rvol": 24.45, "gap_pct": 35.5, "change_pct": 36.79, "price": 6.93}
    fb = lookup_finviz_symbol(ROOT, date(2026, 5, 26), "CODX", scan_row=scan)
    ok &= check("scan_row fallback", fb and fb.get("source") == "trade_ai_scans")
    ok &= check("fallback rvol", fb and float(fb.get("rvol") or 0) > 20)

    if not ok:
        sys.exit(1)
    print("All finviz_snapshot checks passed.")


if __name__ == "__main__":
    main()