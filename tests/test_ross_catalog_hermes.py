#!/usr/bin/env python3
"""Tests for Hermes Ross catalog extraction helpers."""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from ross_catalog_hermes import (  # noqa: E402
    filter_symbols,
    is_valid_ticker,
    merge_regex_and_hermes,
    sanitize_pnl,
    _parse_json_response,
)


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True
    ok &= check("rejects AI noise", not is_valid_ticker("AI"))
    ok &= check("rejects VWAP", not is_valid_ticker("VWAP"))
    ok &= check("accepts GMM", is_valid_ticker("GMM"))
    ok &= check("filter drops noise", filter_symbols(["GMM", "AI", "MACD", "CRNX"]) == ["GMM", "CRNX"])
    ok &= check("pnl cap", sanitize_pnl(4_700_000) is None)
    ok &= check("pnl ok", sanitize_pnl(19000) == 19000.0)

    raw = """```json
{"trade_date": "2026-07-09", "net_pnl_usd": 19000, "symbols_traded": ["PMA", "RPGL"],
 "winners": [{"symbol": "PMA", "pnl_usd": 12000}], "losers": [], "confidence": 0.9}
```"""
    parsed = _parse_json_response(raw)
    ok &= check("json parse", parsed and parsed["symbols_traded"] == ["PMA", "RPGL"])

    regex = {
        "trade_date": date(2026, 7, 9),
        "symbols_traded": ["PMA", "RPGL", "AI"],
        "winners": [],
        "net_pnl_usd": 367500,
        "extraction_method": "regex",
        "extraction_confidence": 0.6,
        "hermes_review_json": {},
    }
    hermes = {
        "trade_date": date(2026, 7, 9),
        "symbols_traded": ["PMA", "RPGL"],
        "winners": [{"symbol": "PMA", "pnl_usd": 12000, "note": "big win"}],
        "losers": [],
        "net_pnl_usd": 19000,
        "extraction_confidence": 0.9,
        "hermes_review_json": {"validated_symbol_count": 2},
    }
    merged = merge_regex_and_hermes(regex, hermes)
    ok &= check("merge method hermes", merged["extraction_method"] == "hermes")
    ok &= check("merge symbols", merged["symbols_traded"] == ["PMA", "RPGL"])
    ok &= check("merge pnl fixed", merged["net_pnl_usd"] == 19000)
    ok &= check("merge keeps regex audit", "regex_symbols" in merged["hermes_review_json"])

    if not ok:
        sys.exit(1)
    print("All ross_catalog_hermes checks passed.")


if __name__ == "__main__":
    main()