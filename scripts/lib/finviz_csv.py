"""Finviz Elite CSV exports, read by header name with a declared contract. Fail closed.

WHY
---
Finviz export columns belong to a *saved view* (v=152, v=141, ...) that can be
edited on finviz.com. Readers that index columns by position break silently when
the view changes: ``portfolio_technical._finviz_api_batch`` carried two hand
"COL-FIX" edits (47 columns -> 11 -> 15), and ``analyst_consensus_history``
stored ten-year performance as a 1-5 analyst rating for five months (97.9% of
rows) because a positional map rotted. The same reader split rows with
``line.split(",")``, so any quoted company name containing a comma would
shift every column after it.

Units are also a trap: Finviz reports Market Cap in MILLIONS of dollars, Shares
Float / Outstanding in MILLIONS of shares and Average Volume in THOUSANDS of
shares (measured 2026-09-14: HPE Market Cap 74722.99 = $74.7B, Average Volume
21374.39 = 21.4M shares). Enrichment stored them as ``market_cap_b`` and
``avg_vol_m``, a 1,000x mislabel that let a $600M company pass a $50B floor.

WHAT THIS DOES
--------------
* ``csv.DictReader`` -- quoted fields with commas stay one field;
* ``parse_export(text, required=...)`` raises ``FinvizContractError`` when a
  required header is absent (the view changed), instead of mapping garbage;
* ``to_number`` handles '%', 'B/M/K' suffixes, '-' and empty;
* ``normalise_units(row)`` returns explicitly-unitised values
  (``market_cap_usd``, ``avg_volume_shares``, ``float_shares``) so callers never
  guess the scale.

READ-ONLY. No network here; callers fetch. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Optional

#: Finviz CSV unit for each header that is not already a plain number.
#: multiplier converts the exported value to base units (dollars / shares).
UNITS: dict[str, tuple[str, float]] = {
    "Market Cap": ("usd", 1e6),
    "Shares Float": ("shares", 1e6),
    "Shares Outstanding": ("shares", 1e6),
    "Average Volume": ("shares", 1e3),
    "Volume": ("shares", 1.0),
}

#: The headers each saved view must carry for the readers that use it.
VIEW_CONTRACTS: dict[int, tuple[str, ...]] = {
    152: ("Ticker", "Price", "Change", "Volume", "Relative Volume", "Average Volume",
          "Market Cap", "Shares Float", "Gap"),
    141: ("Ticker", "Performance (Week)", "Performance (Month)", "Performance (Quarter)",
          "Performance (Half Year)", "Performance (YTD)", "Performance (Year)",
          "Volatility (Week)", "Volatility (Month)", "Relative Volume", "Price"),
}


class FinvizContractError(ValueError):
    """The export does not carry the headers its reader depends on."""


def parse_export(text: str, *, required: Iterable[str] = (), view: Optional[int] = None) -> list[dict[str, str]]:
    """Rows keyed by header. Raises FinvizContractError when a required header is missing."""
    body = (text or "").lstrip("﻿").strip()
    if not body:
        return []
    reader = csv.DictReader(io.StringIO(body))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    need = list(required) or list(VIEW_CONTRACTS.get(view or -1, ()))
    missing = [h for h in need if h not in headers]
    if missing:
        raise FinvizContractError(
            f"Finviz export{f' v={view}' if view else ''} is missing {missing}; headers are {headers}")
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in raw.items() if k is not None})
    return rows


def to_number(value: Any) -> Optional[float]:
    """'12.5%' -> 12.5, '1.2B' -> 1.2e9, '-' / '' -> None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("$", "")
    if s in ("", "-", "N/A", "nan"):
        return None
    mult = 1.0
    if s.endswith("%"):
        s = s[:-1]
    elif s[-1:] in ("B", "M", "K"):
        mult = {"B": 1e9, "M": 1e6, "K": 1e3}[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def in_base_units(row: dict[str, str], header: str) -> Optional[float]:
    """A unitised header's value in dollars or shares."""
    v = to_number(row.get(header))
    if v is None:
        return None
    return v * UNITS.get(header, ("", 1.0))[1]


def normalise_units(row: dict[str, str]) -> dict[str, Optional[float]]:
    """Explicitly-unitised values for the size fields."""
    return {
        "market_cap_usd": in_base_units(row, "Market Cap"),
        "float_shares": in_base_units(row, "Shares Float"),
        "shares_outstanding": in_base_units(row, "Shares Outstanding"),
        "avg_volume_shares": in_base_units(row, "Average Volume"),
        "volume_shares": in_base_units(row, "Volume"),
    }


def enrichment_market_cap_billions(enrich: dict) -> Optional[float]:
    """Market cap in $B from a Finviz enrichment row.

    The enrichment cache stores Finviz 'Market Cap' under ``market_cap_b`` with
    the export's unit, MILLIONS (AAPL 4842453.75 on 2026-09-14). An explicit
    ``market_cap_usd`` wins when a writer provides one.
    """
    usd = to_number((enrich or {}).get("market_cap_usd"))
    if usd is not None:
        return usd / 1e9
    legacy_millions = to_number((enrich or {}).get("market_cap_b"))
    return None if legacy_millions is None else legacy_millions / 1e3


def enrichment_avg_volume_shares(enrich: dict) -> Optional[float]:
    """Average daily volume in shares from a Finviz enrichment row.

    Stored under ``avg_vol_m`` with the export's unit, THOUSANDS of shares
    (HPE 21374.39 = 21.4M shares on 2026-09-14).
    """
    shares = to_number((enrich or {}).get("avg_volume_shares"))
    if shares is not None:
        return shares
    legacy_thousands = to_number((enrich or {}).get("avg_vol_m"))
    return None if legacy_thousands is None else legacy_thousands * 1e3


__all__ = ["FinvizContractError", "UNITS", "VIEW_CONTRACTS", "enrichment_avg_volume_shares",
           "enrichment_market_cap_billions", "in_base_units", "normalise_units", "parse_export",
           "to_number"]
