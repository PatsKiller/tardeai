"""What kind of instrument an option underlying is (operator 2026-09-27).

Why: PUR was offered as a cash-secured-put "wheel" underlying; symbol_profiles labels it
a stock, but its own description says it "seeks to achieve two times (200%)" the daily
return. A daily-reset leveraged fund decays over any holding period, so it is not a
wheel/income underlying, and company financials do not apply to any ETF.

classify() -> OPERATING_COMPANY | ETF | LEVERAGED_FUND, from instrument_type, quote_type
and the profile description (the description wins over a wrong type label).
"""
from __future__ import annotations

import re
from typing import Any, Optional

_LEVERAGED = re.compile(
    r"\b(two|three|2|3)\s*(times|x)\b|\(?\b(200|300|-100|-200|-300)\s*%|\bdaily\b.*\b(leverag|inverse)|"
    r"\b(bull|bear)\s+[23]x\b|\bultra(pro)?\b|\b[23]x\s+(shares|etf|long|short)\b|\binverse\b",
    re.I)
_FUND = re.compile(r"\b(exchange traded fund|etf|index fund|the fund)\b", re.I)


def classify(instrument_type: Any = None, quote_type: Any = None, description: Any = None) -> str:
    it, qt, desc = str(instrument_type or "").lower(), str(quote_type or "").upper(), str(description or "")
    is_fund = it in ("etf", "fund", "mutual_fund", "etn") or qt in ("ETF", "MUTUALFUND") or bool(_FUND.search(desc))
    if is_fund and _LEVERAGED.search(desc):
        return "LEVERAGED_FUND"
    if is_fund:
        return "ETF"
    return "OPERATING_COMPANY"


PROFILE_SQL = "SELECT instrument_type, quote_type, description_1s FROM symbol_profiles WHERE symbol=%s LIMIT 1"


def classify_symbol(symbol: str, execute) -> Optional[str]:
    try:
        r = execute(PROFILE_SQL, (symbol.upper(),), fetch="one")
    except Exception:  # noqa: BLE001
        return None
    if not r:
        return None
    r = dict(r)
    return classify(r.get("instrument_type"), r.get("quote_type"), r.get("description_1s"))
