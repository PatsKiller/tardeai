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


def holding_day_dollars(row: dict, *, today: str, finviz_day_pct: float | None = None) -> tuple[float, str | None]:
    """Dollar day P/L for one holding.

    A stored 0 next to a Finviz percent is recomputed the same way the header
    does. If that is still 0 and the broker stamped a figure today, use it.
    """
    try:
        from holding_day_change import resolve_holding_day_change
    except ImportError:
        from scripts.lib.holding_day_change import resolve_holding_day_change
    try:
        value = float(row.get("market_value") or 0)
    except (TypeError, ValueError):
        value = 0.0
    try:
        price = float(row.get("current_price") if row.get("current_price") is not None else row.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    day, _pct = resolve_holding_day_change(
        row,
        market_value=value,
        price=price,
        stale_price=price,
        finviz_day_pct=finviz_day_pct,
    )
    day = round(float(day or 0), 2)
    basis = (
        "finviz_day_pct"
        if (finviz_day_pct is not None and abs(float(row.get("day_change") or 0)) < 0.005 and abs(day) >= 0.005)
        else None
    )
    if abs(day) < 0.005 and row.get("broker_day_pl") is not None and et_date(row.get("broker_day_pl_at")) == today:
        try:
            broker = round(float(row.get("broker_day_pl")), 2)
        except (TypeError, ValueError):
            broker = 0.0
        if abs(broker) >= 0.005:
            return broker, "broker_day_pl"
    return day, basis


def shape_book_row(row: dict, *, sector: str, stop, today: str, finviz_day_pct: float | None = None) -> dict:
    try:
        value = round(float(row.get("market_value") or 0), 2)
    except (TypeError, ValueError):
        value = 0.0
    day, basis = holding_day_dollars(row, today=today, finviz_day_pct=finviz_day_pct)
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
