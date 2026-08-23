"""SeasonalityState@v1 computed from verified daily close history."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


SCHEMA = "SeasonalityState@v1"
AUTHORITY = "READ_ONLY_ADVISORY"


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"sample_count": 0, "mean_return_pct": None, "median_return_pct": None, "win_rate_pct": None, "dispersion_pct": None, "worst_return_pct": None}
    return {
        "sample_count": len(values),
        "mean_return_pct": round(statistics.fmean(values), 4),
        "median_return_pct": round(statistics.median(values), 4),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "dispersion_pct": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "worst_return_pct": round(min(values), 4),
    }


def _max_drawdown(closes: list[float]) -> float | None:
    peak = 0.0
    worst = 0.0
    for close in closes:
        peak = max(peak, close)
        if peak:
            worst = min(worst, (close / peak - 1.0) * 100.0)
    return round(worst, 4) if closes else None


def compute_symbol_seasonality(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    valid: list[tuple[datetime, float, str]] = []
    for row in bars:
        when = _dt(row.get("bar_time") or row.get("date"))
        close = _float(row.get("close"))
        if when and close is not None and close > 0:
            valid.append((when, close, str(row.get("source") or "unknown")))
    valid.sort(key=lambda item: item[0])
    dedup: dict[date, tuple[datetime, float, str]] = {item[0].date(): item for item in valid}
    daily = sorted(dedup.values(), key=lambda item: item[0])
    month_ends: dict[tuple[int, int], tuple[datetime, float, str]] = {}
    quarter_ends: dict[tuple[int, int], tuple[datetime, float, str]] = {}
    for item in daily:
        when = item[0]
        month_ends[(when.year, when.month)] = item
        quarter_ends[(when.year, (when.month - 1) // 3 + 1)] = item

    monthly_returns: dict[int, list[float]] = defaultdict(list)
    month_values = sorted(month_ends.values(), key=lambda item: item[0])
    for previous, current in zip(month_values, month_values[1:]):
        monthly_returns[current[0].month].append((current[1] / previous[1] - 1.0) * 100.0)
    quarterly_returns: dict[int, list[float]] = defaultdict(list)
    quarter_values = sorted(quarter_ends.values(), key=lambda item: item[0])
    for previous, current in zip(quarter_values, quarter_values[1:]):
        quarter = (current[0].month - 1) // 3 + 1
        quarterly_returns[quarter].append((current[1] / previous[1] - 1.0) * 100.0)

    monthly = {str(month): _stats(monthly_returns.get(month, [])) for month in range(1, 13)}
    quarterly = {f"Q{quarter}": _stats(quarterly_returns.get(quarter, [])) for quarter in range(1, 5)}
    years = (daily[-1][0] - daily[0][0]).days / 365.25 if len(daily) > 1 else 0.0
    min_month_sample = min((row["sample_count"] for row in monthly.values()), default=0)
    if len(daily) < 40:
        quality = "UNAVAILABLE"
    elif years < 5 or min_month_sample < 3:
        quality = "THIN"
    else:
        quality = "VERIFIED"
    return {
        "symbol": symbol.upper(),
        "truth_quality": quality,
        "source": sorted({item[2] for item in daily}),
        "first_bar": daily[0][0].isoformat() if daily else None,
        "last_bar": daily[-1][0].isoformat() if daily else None,
        "daily_bar_count": len(daily),
        "history_years": round(years, 2),
        "max_drawdown_pct": _max_drawdown([item[1] for item in daily]),
        "monthly": monthly,
        "quarterly": quarterly,
        "conditional_regime_slices": {"state": "UNAVAILABLE_SAMPLE", "rows": []},
    }


def build_seasonality_state(
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    benchmark: str = "SPY",
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = evaluated_at or datetime.now(timezone.utc)
    instruments = {
        symbol.upper(): compute_symbol_seasonality(symbol, bars)
        for symbol, bars in sorted(bars_by_symbol.items())
    }
    benchmark_state = instruments.get(benchmark.upper())
    if not benchmark_state:
        quality = "UNAVAILABLE"
    elif benchmark_state["truth_quality"] != "VERIFIED":
        quality = benchmark_state["truth_quality"]
    elif any(row["truth_quality"] != "VERIFIED" for row in instruments.values()):
        quality = "PARTIAL"
    else:
        quality = "VERIFIED"
    payload = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "generated_at": now.isoformat(),
        "benchmark": benchmark.upper(),
        "truth_quality": quality,
        "instruments": instruments,
        "instrument_count": len(instruments),
        "method": "daily_closes_to_month_and_quarter_end_returns",
        "seasonality_is_authority": False,
        "llm_generated_statistics": False,
    }
    payload["version"] = "seasonality_" + hashlib.sha256(
        json.dumps({"benchmark": benchmark.upper(), "instruments": instruments}, sort_keys=True).encode()
    ).hexdigest()[:16]
    return payload


def load_daily_bars(conn, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    import psycopg2.extras

    normalized = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    if not normalized:
        return {}
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT DISTINCT ON (symbol, bar_time) symbol, bar_time, close, source, created_at
        FROM market_ohlcv_bars
        WHERE timeframe = 'daily' AND symbol = ANY(%s)
        ORDER BY symbol, bar_time, created_at DESC
    """, (normalized,))
    out: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in normalized}
    for row in cur.fetchall():
        out[str(row["symbol"]).upper()].append(dict(row))
    return out
