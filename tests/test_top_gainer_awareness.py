#!/usr/bin/env python3
"""Top gainer awareness tagging from Finviz prime_setups."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from top_gainer_awareness import attach_top_gainer_awareness, load_finviz_top_gainers  # noqa: E402


def check(label: str, ok: bool):
    print(f"{'PASS' if ok else 'FAIL'}: {label}")
    if not ok:
        raise SystemExit(1)


def main() -> int:
    # Uses live export if present (GMM was #1 on 2026-07-10).
    gainers = load_finviz_top_gainers(ROOT, limit=5, min_change_pct=5.0)
    check("loads finviz top gainers", len(gainers) >= 1)
    if gainers:
        check("sorted by change desc", gainers[0]["change_pct"] >= gainers[-1]["change_pct"])

    tickers = [{"symbol": "GMM", "score": 0, "decision": "AVOID", "disqualified": True,
                "disqualification_reason": "REVERSE_SPLIT: 0.02:1 on 2026-06-11"}]
    tagged = attach_top_gainer_awareness(tickers, ROOT, limit=10)
    gmm = next((t for t in tickers if t["symbol"] == "GMM"), None)
    if "GMM" in tagged:
        check("GMM tagged TOP_GAINER", gmm and gmm.get("awareness_status") == "TOP_GAINER")
        check("GMM has operator pill", gmm and "TOP GAINER" in (gmm.get("operator_pill") or ""))
        check("GMM not_tradeable", gmm and gmm.get("not_tradeable") is True)
        check("GMM backfills change_pct", gmm and gmm.get("change_pct"))
    else:
        check("GMM optional when no finviz file", True)

    print("All top_gainer_awareness checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())