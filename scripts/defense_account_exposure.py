#!/usr/bin/env python3
"""Pure account-specific effective sector exposure contract for Defense/Sectors.

No database, network, broker, order or configuration writes. The caller supplies already
loaded holdings, a fund look-through map and a symbol→sector map. Unknown exposure remains
explicitly unmapped; it is never redistributed across known sectors.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

CONTRACT_VERSION = "defense-account-exposure-v1"


def _number(value: Any) -> float:
    try:
        n = float(value)
        return n if n > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def account_sector_exposure(
    holdings: Iterable[dict],
    fund_lookthrough: dict[str, dict],
    sector_by_symbol: dict[str, str | None],
) -> dict[str, dict]:
    """Return account equity and effective sector dollars/percentages.

    Fund ``weights`` are expected as fractions (0.25 = 25%). Any missing fund weight is
    recorded as unmapped rather than forced into a sector. Direct instruments use the
    caller's canonical symbol→sector mapping. Cash rows should be omitted by the caller;
    a defensive check excludes rows marked ``is_cash``.
    """
    totals: dict[str, float] = defaultdict(float)
    sectors: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    unmapped: dict[str, float] = defaultdict(float)

    for raw in holdings:
        if raw.get("is_cash"):
            continue
        account = str(raw.get("account") or "").strip()
        symbol = str(raw.get("symbol") or "").strip().upper()
        value = _number(raw.get("value", raw.get("market_value")))
        if not account or not symbol or value <= 0:
            continue
        totals[account] += value

        fund = fund_lookthrough.get(symbol) or {}
        weights = fund.get("weights") if isinstance(fund, dict) else None
        if isinstance(weights, dict) and weights:
            mapped_fraction = 0.0
            for sector, raw_weight in weights.items():
                weight = max(0.0, min(1.0, _number(raw_weight)))
                if not sector or weight <= 0:
                    continue
                sectors[account][str(sector)] += value * weight
                mapped_fraction += weight
            unmapped[account] += value * max(0.0, 1.0 - min(mapped_fraction, 1.0))
            continue

        sector = sector_by_symbol.get(symbol) or raw.get("sector")
        if sector:
            sectors[account][str(sector)] += value
        else:
            unmapped[account] += value

    out: dict[str, dict] = {}
    for account in sorted(totals):
        equity = totals[account]
        sector_rows = {
            sector: {
                "dollars": round(dollars, 2),
                "pct": round(dollars / equity * 100, 4) if equity else None,
            }
            for sector, dollars in sorted(sectors[account].items())
        }
        mapped_dollars = sum(row["dollars"] for row in sector_rows.values())
        unmapped_dollars = round(unmapped[account], 2)
        out[account] = {
            "account_equity_dollars": round(equity, 2),
            "sectors": sector_rows,
            "mapped_dollars": round(mapped_dollars, 2),
            "mapped_pct": round(mapped_dollars / equity * 100, 4) if equity else None,
            "unmapped_dollars": unmapped_dollars,
            "unmapped_pct": round(unmapped_dollars / equity * 100, 4) if equity else None,
            "calculation_version": CONTRACT_VERSION,
        }
    return out


def sector_weight_for_account(exposure: dict[str, dict], account: str, sector: str) -> float | None:
    """Return an account's effective sector percentage or ``None`` when not evidenced."""
    row = ((exposure.get(account) or {}).get("sectors") or {}).get(sector)
    if not row or row.get("pct") is None:
        return None
    return float(row["pct"])
