#!/usr/bin/env python3
"""audit_finviz_throttle_coverage.py — every Finviz caller must be throttled.

The 2026-06-22 429 storm collapsed the screener universe and zeroed the GO tier
because one bulk consumer ignored the shared cooldown. On 2026-07-20 an audit
found 12 live callers still bypassing scripts/finviz_throttle.py.

A module is COVERED if it either imports finviz_http (the sanctioned wrapper)
or calls finviz_throttle directly. A module that merely BUILDS a Finviz URL
without fetching it needs neither.

Exit 1 if any fetching module is uncovered — wire this into CI/preflight.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

FINVIZ_HOST = re.compile(r"https?://(?:\w+\.)?finviz\.com", re.I)
# NOTE: bare `session.get(` is deliberately NOT a fetch signal — dict.get()
# collides with it (html_dashboard.py:470 is session.get("session_label")).
FETCH = re.compile(r"requests\.(get|post)\s*\(|urlopen\s*\(|"
                   r"finviz_get\s*\(|finviz_probe\s*\(", re.I)
COVERED = re.compile(r"finviz_http|finviz_throttle")

# Modules that reference a Finviz URL but never fetch it (string builders,
# display links, seed constants). Verified 2026-07-20.
URL_BUILDERS_ONLY = {
    "backtest_analyzer.py",          # returns chart URLs for display
    "add_winning_strategy_screeners.py",  # seed definition constant
    "finviz_http.py",                # the wrapper itself
    "finviz_throttle.py",
    "finviz_filter_validator.py",    # uses _rows() -> finviz_throttle
    "html_dashboard.py",             # client-side <a>/window.open links only
    "journal_tab.py",                # display links only
    "portfolio_dashboard.py",        # display links only
    "patch_screeners_yaml.py",       # writes definitions, never fetches
    "audit_finviz_throttle_coverage.py",
}


def main() -> int:
    uncovered, covered, builders = [], [], []
    for p in sorted(SCRIPTS.glob("*.py")):
        if p.name in URL_BUILDERS_ONLY:
            continue
        try:
            txt = p.read_text(errors="replace")
        except Exception:
            continue
        if not FINVIZ_HOST.search(txt):
            continue
        if not FETCH.search(txt):
            builders.append(p.name)
            continue
        (covered if COVERED.search(txt) else uncovered).append(p.name)

    print(f"Finviz callers that fetch: {len(covered) + len(uncovered)}")
    print(f"  covered   : {len(covered)}")
    print(f"  UNCOVERED : {len(uncovered)}")
    if builders:
        print(f"  url-only  : {len(builders)} ({', '.join(builders)})")
    for n in uncovered:
        print(f"    !! {n} fetches Finviz without the global throttle")
    return 1 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
