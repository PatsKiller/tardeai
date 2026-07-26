#!/usr/bin/env python3
"""Pure account-specific exposure and sizing contracts for Defense/Sectors.

No database, network, broker, order or configuration writes. The caller supplies already
loaded holdings, a fund look-through map and a symbol→sector map. Unknown exposure remains
explicitly unmapped; it is never redistributed across known sectors.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

CONTRACT_VERSION = "defense-account-exposure-v2"


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


def build_account_sizing(
    decisions: dict[str, dict],
    account_equities: dict[str, float],
    configured_pct_band: list[float] | tuple[float, float],
    *,
    minimum_action_pct: float = 1.0,
) -> dict[str, dict]:
    """Convert each eligible account's own capacity into its own action band.

    No account inherits another account's capacity. Missing equity, missing risk evidence,
    ineligibility, or capacity below ``minimum_action_pct`` withholds that account.
    """
    if len(configured_pct_band) != 2:
        raise ValueError("configured_pct_band must contain [low, high]")
    configured_low = max(0.0, float(configured_pct_band[0]))
    configured_high = max(configured_low, float(configured_pct_band[1]))
    out: dict[str, dict] = {}

    for account in sorted(decisions):
        decision = decisions.get(account) or {}
        equity = _number(account_equities.get(account))
        capacity = _number(decision.get("capacity_pct"))
        if not decision.get("eligible") or decision.get("quality") != "ok":
            continue
        if equity <= 0 or capacity < minimum_action_pct:
            continue
        high = min(configured_high, capacity)
        low = min(configured_low, high)
        if high < minimum_action_pct:
            continue
        out[account] = {
            "pct_band": [round(low, 2), round(high, 2)],
            "dollar_band": [round(equity * low / 100), round(equity * high / 100)],
            "account_equity_dollars": round(equity, 2),
            "current_account_weight_pct": decision.get("current_account_weight_pct"),
            "risk_target_pct": decision.get("risk_target_pct"),
            "capacity_pct": decision.get("capacity_pct"),
            "calculation_version": CONTRACT_VERSION,
        }
    return out
