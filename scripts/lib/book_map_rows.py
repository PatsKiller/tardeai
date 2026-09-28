"""Shape one holdings row for the home book map.

Cash is not a tile. A zero day_change is replaced by today's broker_day_pl
when that stamp exists. A row with no price and no value is unpriced.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def et_date(ts) -> str | None:
    if not ts:
        return None
    text = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET).date().isoformat()


def cash_total(holdings) -> float:
    total = 0.0
    for row in holdings or []:
        if row.get("is_cash"):
            try:
                total += float(row.get("market_value") or 0)
            except (TypeError, ValueError):
                continue
    return round(total, 2)


def shape_book_row(row: dict, *, sector: str, stop, today: str) -> dict:
    try:
        value = round(float(row.get("market_value") or 0), 2)
    except (TypeError, ValueError):
        value = 0.0
    try:
        day = round(float(row.get("day_change") or 0), 2)
    except (TypeError, ValueError):
        day = 0.0
    basis = None
    if day == 0 and row.get("broker_day_pl") is not None and et_date(row.get("broker_day_pl_at")) == today:
        try:
            day = round(float(row.get("broker_day_pl")), 2)
            basis = "broker_day_pl"
        except (TypeError, ValueError):
            day = 0.0
            basis = None
    price = row.get("current_price")
    if price is None:
        price = row.get("price")
    unpriced = value == 0 and price is None
    out = {
        "symbol": str(row.get("symbol") or "").upper(),
        "account": row.get("account"),
        "value": value,
        "day_change": day,
        "day_change_pct": row.get("day_change_pct"),
        "weight_pct": row.get("portfolio_pct"),
        "sector": sector or "Unclassified",
        "stop": stop,
        "delisted": bool(row.get("delisted")) or None,
        "unpriced": unpriced,
    }
    if basis:
        out["day_change_basis"] = basis
    return out
