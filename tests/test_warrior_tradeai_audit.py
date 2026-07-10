#!/usr/bin/env python3
"""Smoke tests for warrior audit helpers."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from warrior_daily_catalog_extractor import extract_row, _extract_pnl, _parse_trade_date  # noqa: E402
from warrior_tradeai_audit import _classify_gap, _gap_counts  # noqa: E402


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True
    ok &= check("pnl from title", _extract_pnl("$12,345 Day Trading Recap", "") == 12345.0)
    ok &= check("trade date july", _parse_trade_date("July 10, 2026 Recap", date(2026, 7, 11)) == date(2026, 7, 10))

    row = {
        "id": 1, "video_id": "abc", "title": "July 10, 2026 | $8,500 Green Day Recap | GMM INUV",
        "publish_date": date(2026, 7, 10),
        "transcript_text": "Traded GMM for a nice win and INUV as well. RVOL was huge.",
    }
    ex = extract_row(row, {"GMM", "INUV", "ELAB"})
    ok &= check("extract symbols", ex and "GMM" in ex["symbols_traded"] and "INUV" in ex["symbols_traded"])
    ok &= check("extract pnl", ex and ex.get("net_pnl_usd") == 8500.0)

    ok &= check("gap missing", _classify_gap(None, None) == "DATA_MISSING")
    ok &= check("gap dq", _classify_gap({"disqualified": True, "disqualification_reason": "REVERSE_SPLIT"}, {}) == "DQ_REVERSE_SPLIT")
    ok &= check("gap high rvol", _classify_gap({
        "decision": "MANUAL_REVIEW", "awareness_status": "HIGH_RVOL", "setup_class": "high_rvol_runner",
        "rvol": 12, "disqualified": False,
    }, {}) == "HIGH_RVOL_MANUAL_REVIEW")
    ok &= check("gap low price", _classify_gap({
        "decision": "MANUAL_REVIEW", "awareness_status": "LOW_PRICE", "setup_class": "low_price_runner",
    }, {}) == "LOW_PRICE_MANUAL_REVIEW")
    ok &= check("gap catalyst exception", _classify_gap({
        "decision": "MANUAL_REVIEW", "setup_class": "momentum_runner", "catalyst_optional": True,
    }, {}) == "CATALYST_EXCEPTION_MANUAL_REVIEW")
    ok &= check("aligned via scan fallback", _classify_gap(
        {"decision": "GO", "disqualified": False, "rvol": 24.0},
        {"source": "trade_ai_scans", "rvol": 24.0},
    ) == "ALIGNED")
    ok &= check("gap counts", _gap_counts([{"gap_reason": "DATA_MISSING"}, {"gap_reason": "DATA_MISSING"}])["DATA_MISSING"] == 2)

    if not ok:
        sys.exit(1)
    print("All warrior audit checks passed.")


if __name__ == "__main__":
    main()