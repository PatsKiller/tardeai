"""Closed-session resistance intelligence for Re-Entry.

Computes an auditable resistance level from ticker_prices without treating an
intraday cross as a hold. Results are persisted in ui_prefs for the dashboard and
refreshed by the existing 20-minute Watch alert pass.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable

CACHE_KEY = "portfolio.reentry.resistance.v1"
MANDATE_KEY = "portfolio.reentry.mandates.v4"
ROTATION_KEY = "portfolio.reentry.rotation-links.v1"
# Cash sweeps and money-market funds have no tradable price series — a $1.00 NAV
# produces a meaningless "TESTING resistance $1.00" row that crowds the board.
CASH_LIKE = frozenset({
    "CASH", "MMKT", "FCASH", "SPAXX", "FDRXX", "SPRXX", "FZFXX", "SWVXX", "VMFXX",
    "SNVXX", "SNSXX", "FGXX", "FTEXX",
})

TOLERANCE_PCT = 0.5
LOOKBACK = 20
TEST_LOOKBACK = 60


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _pref(ex: Callable[..., Any], key: str) -> dict[str, Any]:
    row = ex("SELECT value FROM ui_prefs WHERE key=%s", (key,), fetch="one") or {}
    return _dict(row.get("value"))


def _f(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _series(ex: Callable[..., Any], symbol: str, days: int = 180) -> list[tuple[dt.date, float]]:
    rows = ex(
        """SELECT price_date, close_price FROM ticker_prices
           WHERE upper(symbol)=%s AND price_date > CURRENT_DATE - %s
             AND close_price IS NOT NULL
           ORDER BY price_date""",
        (symbol.upper(), days), fetch="all",
    ) or []
    by_date: dict[dt.date, float] = {}
    for row in rows:
        date_value = row.get("price_date")
        close = _f(row.get("close_price"))
        if close is None or close <= 0 or date_value is None:
            continue
        if isinstance(date_value, dt.datetime):
            date_value = date_value.date()
        elif not isinstance(date_value, dt.date):
            try:
                date_value = dt.date.fromisoformat(str(date_value)[:10])
            except Exception:
                continue
        by_date[date_value] = close
    return sorted(by_date.items())


def compute_resistance(series: list[tuple[dt.date, float]]) -> dict[str, Any]:
    """Return stable breakout/hold evidence from daily closes.

    An active hold begins only when a close exceeds the prior 20-session maximum
    by more than the tolerance and every later close remains at or above that
    breakout level within tolerance. If no active hold exists, resistance is the
    maximum of the prior 20 closes and hold count remains zero.
    """
    if len(series) < LOOKBACK + 1:
        return {
            "state": "UNAVAILABLE",
            "resistance": None,
            "distance_pct": None,
            "hold_days": None,
            "hold_start": None,
            "tests": None,
            "as_of": series[-1][0].isoformat() if series else None,
            "reason": f"need at least {LOOKBACK + 1} closed sessions",
        }
    dates = [row[0] for row in series]
    closes = [row[1] for row in series]
    latest = closes[-1]
    active_index = None
    active_level = None
    first = max(LOOKBACK, len(series) - TEST_LOOKBACK)
    for index in range(first, len(series)):
        level = max(closes[index - LOOKBACK:index])
        breakout = closes[index] > level * (1 + TOLERANCE_PCT / 100)
        held = all(close >= level * (1 - TOLERANCE_PCT / 100) for close in closes[index:])
        if breakout and held:
            active_index = index
            active_level = level
            break
    if active_level is None:
        resistance = max(closes[-LOOKBACK - 1:-1])
        hold_days = 0
        hold_start = None
    else:
        resistance = active_level
        hold_days = len(series) - active_index
        hold_start = dates[active_index].isoformat()
    distance_pct = (latest - resistance) / resistance * 100 if resistance else None
    if distance_pct is None:
        state = "UNAVAILABLE"
    elif abs(distance_pct) <= TOLERANCE_PCT:
        state = "TESTING"
    elif distance_pct > 0:
        state = "ABOVE"
    else:
        state = "BELOW"
    recent = closes[-TEST_LOOKBACK:]
    tests = sum(1 for close in recent if abs((close - resistance) / resistance * 100) <= TOLERANCE_PCT)
    return {
        "state": state,
        "resistance": round(resistance, 4),
        "current_close": round(latest, 4),
        "distance_pct": round(distance_pct, 3) if distance_pct is not None else None,
        "hold_days": hold_days,
        "hold_start": hold_start,
        "tests": tests,
        "as_of": dates[-1].isoformat(),
        "tolerance_pct": TOLERANCE_PCT,
        "method": "active breakout over prior 20-session max; closed-session hold only",
    }


def compute_support(series: list[tuple[dt.date, float]]) -> dict[str, Any]:
    """Mirror of compute_resistance for the downside.

    An active breakdown begins when a close falls below the prior 20-session minimum
    by more than the tolerance and every later close stays at or below that level
    within tolerance. Absent a breakdown, support is the minimum of the prior 20
    closes. Same closed-session discipline: an intraday undercut is never a break.
    """
    if len(series) < LOOKBACK + 1:
        return {
            "support_state": "UNAVAILABLE",
            "support": None,
            "support_distance_pct": None,
            "support_hold_days": None,
            "support_break_start": None,
            "support_tests": None,
        }
    dates = [row[0] for row in series]
    closes = [row[1] for row in series]
    latest = closes[-1]
    active_index = None
    active_level = None
    first = max(LOOKBACK, len(series) - TEST_LOOKBACK)
    for index in range(first, len(series)):
        level = min(closes[index - LOOKBACK:index])
        breakdown = closes[index] < level * (1 - TOLERANCE_PCT / 100)
        held = all(close <= level * (1 + TOLERANCE_PCT / 100) for close in closes[index:])
        if breakdown and held:
            active_index = index
            active_level = level
            break
    if active_level is None:
        support = min(closes[-LOOKBACK - 1:-1])
        hold_days = 0
        break_start = None
    else:
        support = active_level
        hold_days = len(series) - active_index
        break_start = dates[active_index].isoformat()
    distance_pct = (latest - support) / support * 100 if support else None
    if distance_pct is None:
        state = "UNAVAILABLE"
    elif abs(distance_pct) <= TOLERANCE_PCT:
        state = "TESTING"
    elif distance_pct > 0:
        state = "ABOVE"
    else:
        state = "BROKEN"
    recent = closes[-TEST_LOOKBACK:]
    tests = sum(1 for close in recent if support and abs((close - support) / support * 100) <= TOLERANCE_PCT)
    return {
        "support_state": state,
        "support": round(support, 4) if support else None,
        "support_distance_pct": round(distance_pct, 3) if distance_pct is not None else None,
        "support_hold_days": hold_days,
        "support_break_start": break_start,
        "support_tests": tests,
        "support_method": "active breakdown under prior 20-session min; closed-session break only",
    }


def scrub_series(series: list[tuple[dt.date, float]], deviation: float = 0.65,
                 window: int = 21) -> tuple[list[tuple[dt.date, float]], list[str]]:
    """Drop corrupt bars before any level or momentum is computed.

    ticker_prices contains real garbage: NVDA closed at 0.66, 0.18 and 0.05 on three
    consecutive May sessions, sitting between ~200 closes either side. Support takes the
    minimum of a trailing window, so a single bad tick silently became a "support level"
    of five cents. A bar is dropped when it deviates from the median of its neighbourhood
    by more than the threshold — far past any real session move, and unlike a fixed price
    floor it needs no per-symbol tuning. Genuine crashes shift the rolling median with
    them and survive.
    """
    if len(series) < 5:
        return series, []
    closes = [row[1] for row in series]
    kept: list[tuple[dt.date, float]] = []
    dropped: list[str] = []
    half = max(2, window // 2)
    for index, (date_value, close) in enumerate(series):
        neighbourhood = closes[max(0, index - half):index] + closes[index + 1:index + 1 + half]
        if not neighbourhood:
            kept.append((date_value, close))
            continue
        ordered = sorted(neighbourhood)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        if median > 0 and abs(close / median - 1) > deviation:
            dropped.append(date_value.isoformat())
            continue
        kept.append((date_value, close))
    return kept, dropped


RSI_PERIOD = 14


def compute_rsi(series: list[tuple[dt.date, float]], period: int = RSI_PERIOD) -> dict[str, Any]:
    """Wilder RSI from the same closed-session series the levels use.

    Re-Entry read price and RSI from watchlist_items, but an exited name is usually
    status='removed' there, so the lookup returned no row and the desk showed
    "NO CURRENT COVERAGE" for symbols whose closes were sitting in ticker_prices the
    whole time. Computing it here costs nothing extra — the series is already loaded
    for resistance — and keeps one closed-session definition instead of two.
    """
    if len(series) < period + 1:
        return {"rsi": None, "rsi_as_of": None}
    closes = [row[1] for row in series]
    # Unadjusted corporate actions survive scrubbing (DJTU: +869% sustained after a
    # reverse split). RSI is the most gap-sensitive of the three measures, so an
    # implausible move between genuinely adjacent sessions suppresses the number rather
    # than publishing a confident wrong one. Adjacency matters: AMD has a 28-day hole in
    # ticker_prices, and the bars either side of a coverage hole are not a one-day move.
    for index in range(1, len(closes)):
        previous = closes[index - 1]
        adjacent = (series[index][0] - series[index - 1][0]).days <= 4
        if adjacent and previous > 0 and abs(closes[index] / previous - 1) > 0.40:
            return {
                "rsi": None,
                "rsi_as_of": None,
                "rsi_reason": f"unadjusted price gap on {series[index][0].isoformat()}",
            }
    gains = losses = 0.0
    for index in range(1, period + 1):
        change = closes[index] - closes[index - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    if avg_loss == 0:
        rsi = 100.0 if avg_gain > 0 else 50.0
    else:
        rsi = 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return {"rsi": round(rsi, 2), "rsi_as_of": series[-1][0].isoformat()}


def _symbols(ex: Callable[..., Any]) -> list[str]:
    from lib.reentry_shared_context import mandate_symbols

    symbols = mandate_symbols(_pref(ex, MANDATE_KEY))
    for link in _pref(ex, ROTATION_KEY).values():
        if not isinstance(link, dict):
            continue
        for key in ("sourceSymbol", "destinationSymbol"):
            value = str(link.get(key) or "").upper().strip()
            if value:
                symbols.add(value)
    rows = ex(
        """SELECT DISTINCT upper(symbol) AS symbol FROM trade_transactions
           WHERE trade_date >= CURRENT_DATE - 365
             AND symbol IS NOT NULL
             AND NOT (lower(coalesce(account,'')) LIKE '%paper%'
                      OR lower(coalesce(account,'')) LIKE '%sim%'
                      OR lower(coalesce(account,'')) LIKE '%sandbox%'
                      OR lower(coalesce(account,'')) LIKE '%test%')
             AND (lower(coalesce(action,'')) IN
                    ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
                  OR lower(coalesce(action,'')) LIKE 'sell%')
           ORDER BY 1 LIMIT 1500""",
        fetch="all",
    ) or []
    symbols.update(str(row.get("symbol") or "").upper() for row in rows if row.get("symbol"))
    symbols.update(_holdings_symbols())
    symbols.update(_discovery_symbols(ex))
    return sorted(symbol for symbol in symbols if symbol and symbol not in CASH_LIKE)


def _discovery_symbols(ex: Callable[..., Any]) -> set[str]:
    """Names the Watchlist and Proposals desks actually put on screen.

    Those surfaces now show the same closed-session levels as Portfolio and Re-Entry,
    so their symbols have to be in the cache or the line is simply absent for most
    rows. Scope is deliberately the live board, not the full 11k watchlist history:
    active or recently-seen items, and proposals from the last 30 days. Anything with
    no usable price series is dropped at publish time rather than stored as a stub.
    """
    out: set[str] = set()
    for sql in (
        """SELECT DISTINCT upper(symbol) AS symbol FROM watchlist_items
             WHERE symbol IS NOT NULL
               AND (status = 'active' OR last_seen_at > NOW() - INTERVAL '7 days')
             ORDER BY 1 LIMIT 600""",
        """SELECT DISTINCT upper(symbol) AS symbol FROM paper_trade_proposals
             WHERE symbol IS NOT NULL AND created_at > NOW() - INTERVAL '30 days'
             ORDER BY 1 LIMIT 600""",
    ):
        for row in (ex(sql, fetch="all") or []):
            value = str(row.get("symbol") or "").upper().strip()
            if value.isalpha() and 1 <= len(value) <= 5:
                out.add(value)
    return out


def _holdings_symbols(path: Any = None) -> set[str]:
    """Currently-held tickers.

    Resistance was previously computed for exited symbols only, so the Portfolio
    holdings table had no closed-session level to show for anything still held. The
    method is identical either way — it reads ticker_prices — so the same cache
    serves both desks rather than standing up a second job on the same data.
    """
    import json as _json
    from pathlib import Path as _Path

    path = _Path(path) if path else _Path(__file__).resolve().parents[2] / "data" / "portfolios" / "state" / "holdings.json"
    try:
        rows = _json.loads(path.read_text()).get("holdings") or []
    except Exception:
        return set()
    out: set[str] = set()
    for row in rows:
        symbol = str((row or {}).get("symbol") or "").upper().strip()
        # Cash sweeps and delisted CUSIP placeholders have no tradable price series.
        if (symbol and symbol.isalpha() and 1 <= len(symbol) <= 5
                and symbol not in CASH_LIKE and not (row or {}).get("is_cash")):
            out.add(symbol)
    return out


# The method strings and tolerance are identical on every row, and three support
# fields have no consumer. At ~490 symbols that was ~110 kB of repeated text on a
# payload every desk fetches, so they are hoisted to the payload root instead.
_ROW_TRIM = frozenset({
    "method", "support_method", "tolerance_pct", "support_tests", "support_break_start",
})


def refresh_resistance_cache(ex: Callable[..., Any]) -> dict[str, Any]:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    values: dict[str, Any] = {}
    total_dropped: list[str] = []
    for symbol in _symbols(ex):
        try:
            series, dropped = scrub_series(_series(ex, symbol))
            level = {**compute_resistance(series), **compute_support(series), **compute_rsi(series)}
            if dropped:
                level["dropped_bars"] = len(dropped)
                total_dropped.append(f"{symbol}:{len(dropped)}")
            if level.get("resistance") is None and level.get("support") is None:
                continue  # no usable price series — a stub row renders nothing
            values[symbol] = {k: v for k, v in level.items() if k not in _ROW_TRIM}
        except Exception as error:
            values[symbol] = {
                "state": "UNAVAILABLE",
                "resistance": None,
                "distance_pct": None,
                "hold_days": None,
                "hold_start": None,
                "tests": None,
                "as_of": None,
                "reason": str(error)[:160],
            }
    payload = {
        "version": "reentry_resistance_v1",
        "generated_at": generated_at,
        "symbol_count": len(values),
        "tolerance_pct": TOLERANCE_PCT,
        "method": "active breakout over prior 20-session max; closed-session hold only",
        "support_method": "active breakdown under prior 20-session min; closed-session break only",
        "scrubbed_symbols": len(total_dropped),
        "symbols": values,
    }
    ex(
        """INSERT INTO ui_prefs (key, value, updated_at)
           VALUES (%s,%s::jsonb,NOW())
           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
        (CACHE_KEY, json.dumps(payload)), fetch=None,
    )
    return payload
