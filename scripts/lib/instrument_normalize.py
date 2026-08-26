"""Instrument-type normalization. OCC options are not unknown equities."""
from __future__ import annotations

import re
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def classify_instrument(symbol: str, *, is_cash: bool = False, asset_type: str | None = None) -> dict[str, Any]:
    sym = str(symbol or "").upper().replace(" ", "")
    asset = str(asset_type or "").upper()
    if is_cash or sym in {"CASH", "USD"}:
        kind = "CASH"
    elif OCC_RE.match(sym) or "OPTION" in asset:
        kind = "OPTION"
    elif "ETF" in asset:
        kind = "ETF"
    elif "FUND" in asset or "MUTUAL" in asset:
        kind = "MUTUAL_FUND"
    elif "BOND" in asset or "FIXED" in asset:
        kind = "FIXED_INCOME"
    elif not sym:
        kind = "OTHER"
    else:
        kind = "EQUITY"
    underlying = None
    if kind == "OPTION":
        m = re.match(r"^([A-Z]{1,6})\d{6}[CP]\d{8}$", sym)
        underlying = m.group(1) if m else None
    return {
        "symbol": symbol,
        "instrument_class": kind,
        "underlying_symbol": underlying,
        "meaningless_zero_stop": kind == "OPTION",
        "authority": AUTHORITY,
        "financial_action": False,
    }
