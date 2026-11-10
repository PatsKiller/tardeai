"""Instrument-type normalization. OCC options are not unknown equities."""
from __future__ import annotations

import re
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

#: Instrument classes that cannot carry a resting stop order at the broker. LQ-1739 defines this
#: pair; LQ-20261107-1740 (the CIO brief) is its first reader. Identical on both branches by
#: design — whichever folds second resolves to one copy, never a second classifier.
STOPLESS_ASSET_TYPES = frozenset({"MUTUAL_FUND"})


def is_stopless_asset(asset_type: str | None) -> bool:
    """True when a broker cannot carry a resting stop for this instrument. Unknown/None -> False."""
    return classify_instrument("", asset_type=asset_type)["instrument_class"] in STOPLESS_ASSET_TYPES


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


# ── stop eligibility (LQ-20261107-1739) ─────────────────────────────────────────────────────────────────────────
# A mutual fund trades once a day at NAV: the broker has no intraday session in which a resting stop could work, so
# "held with no working stop" is not a coverage gap for it. Classified from the holding's OWN asset_type through the
# same classifier above — never a symbol list, and never a symbol-shape guess.
STOPLESS_ASSET_TYPES = frozenset({"MUTUAL_FUND"})


def is_stopless_asset(asset_type: Any) -> bool:
    """True when the broker cannot carry a resting stop for this instrument. Unknown/None -> False (eligible)."""
    return classify_instrument("", asset_type=asset_type)["instrument_class"] in STOPLESS_ASSET_TYPES
