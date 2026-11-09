"""Key levels (§4.2, §4.6 key_levels): supports and resistances per cash index, with their basis stated.

The anchor is a real cash close ($SPX, $NDX, $RUT, $DJI, $COMPX) from a Schwab or Finviz print, stored with
its as_of. An index with no cash close is ``not_measured``. An ETF close times a fixed factor is never an
anchor, and ETF bars are never rescaled onto the index.
"""

from __future__ import annotations

from typing import Any, Sequence

# Policy index key -> the symbol the Schwab lane writes.
CASH_SYMBOL = {"SPX": "$SPX", "NDX": "$NDX", "RUT": "$RUT", "DJI": "$DJI", "COMPX": "$COMPX"}
_BANNED = ("yfinance", "yahoo")


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _sma(values: Sequence[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _pick(
    candidates: list[tuple[str, float]], anchor: float, *, above: bool, scale: float, count: int = 3
) -> list[dict[str, Any]]:
    seen: set[float] = set()
    out: list[dict[str, Any]] = []
    ordered = sorted(candidates, key=lambda c: c[1], reverse=not above)
    for source, value in ordered:
        if above and value <= anchor:
            continue
        if not above and value >= anchor:
            continue
        if abs(value - anchor) / anchor < 1e-4:
            continue
        scaled = value * scale  # candidates live on the proxy's scale; the level is stated on the index's
        rounded = round(scaled, 2)
        if rounded in seen:
            continue
        seen.add(rounded)
        out.append({"level": rounded, "source": source, "distance_pct": round((value / anchor - 1.0) * 100.0, 2)})
        if len(out) >= count:
            break
    return out


def _banned(feed: Any) -> bool:
    text = str(feed or "").lower()
    return any(name in text for name in _BANNED)


def _cash_quote(bundle: Any, symbol: str) -> dict[str, Any] | None:
    """Latest allowed extended print for one cash index. No provider call."""
    chosen: dict[str, Any] | None = None
    for row in getattr(bundle, "extended", None) or []:
        if str(row.get("symbol") or "") != symbol:
            continue
        price = _f(row.get("price"))
        if price is None or price <= 0 or _banned(row.get("feed")):
            continue
        stamp = str(row.get("bar_end") or row.get("bar_start") or "")
        if chosen is None or stamp >= str(chosen.get("_stamp")):
            chosen = {
                "price": price,
                "as_of": stamp or None,
                "source": str(row.get("feed") or ""),
                "session": row.get("session"),
                "_stamp": stamp,
            }
    return chosen


def _cash_bars(bundle: Any, symbol: str) -> list[dict[str, Any]]:
    """Daily cash bars only. An ETF series is not a stand-in."""
    out = []
    for bar in (getattr(bundle, "bars", None) or {}).get(symbol) or []:
        if _banned(bar.get("source")):
            continue
        close = _f(bar.get("close"))
        if close is None or close <= 0:
            continue
        out.append(bar)
    return out


def _not_measured(index: str) -> dict[str, Any]:
    return {
        "support": [],
        "resistance": [],
        "basis": "not_measured",
        "anchor": None,
        "proxy": None,
        "as_of": None,
        "source": None,
        "session": None,
        "note": f"{index} cash level not measured",
    }


def key_levels(
    bundle: Any, policy: dict[str, Any], *, sessions: int = 5
) -> dict[str, dict[str, Any]]:
    cfg = policy["levels"]
    names = list(cfg["indices"])
    for extra in ("DJI", "COMPX"):
        if extra not in names:
            names.append(extra)
    out: dict[str, dict[str, Any]] = {}
    for index in names:
        symbol = CASH_SYMBOL.get(index, f"${index}")
        quote = _cash_quote(bundle, symbol)
        bars = _cash_bars(bundle, symbol)
        if quote is None and not bars:
            out[index] = _not_measured(index)
            continue
        if quote is not None:
            anchor = float(quote["price"])
            as_of = quote.get("as_of")
            source = str(quote.get("source") or "")
            session = quote.get("session")
        else:
            anchor = float(bars[-1]["close"])
            as_of = str(bars[-1].get("as_of") or bars[-1].get("date"))
            source = str(bars[-1].get("source") or "")
            session = None
        support: list[dict[str, Any]] = []
        resistance: list[dict[str, Any]] = []
        note = f"{index} anchor is the cash close"
        if len(bars) >= 2:
            closes = [float(b["close"]) for b in bars]
            highs = [_f(b.get("high")) for b in bars]
            lows = [_f(b.get("low")) for b in bars]
            candidates: list[tuple[str, float]] = []
            if any(v is not None for v in highs[-sessions:]) and any(v is not None for v in lows[-sessions:]):
                hi = max(v for v in highs[-sessions:] if v is not None)
                lo = min(v for v in lows[-sessions:] if v is not None)
                candidates += [("prior_week_high", hi), ("prior_week_low", lo)]
            for n, label in ((50, "dma50"), (200, "dma200")):
                v = _sma(closes, n)
                if v is not None:
                    candidates.append((label, v))
            step = float((cfg.get("round_number_step") or {}).get(index) or 0)
            tol = float(cfg.get("round_number_tolerance_pct") or 0) / 100.0
            if step > 0:
                for mult in (int(anchor / step) * step, (int(anchor / step) + 1) * step):
                    if mult > 0 and abs(mult - anchor) / anchor <= tol:
                        candidates.append(("round_number", mult))
            support = _pick(candidates, anchor, above=False, scale=1.0)
            resistance = _pick(candidates, anchor, above=True, scale=1.0)
            note = f"{index} levels computed on cash daily bars"
        else:
            note = f"{index} cash close only; support and resistance are not measured"
        out[index] = {
            "support": support,
            "resistance": resistance,
            "basis": "cash",
            "anchor": round(anchor, 2),
            "proxy": None,
            "as_of": as_of,
            "source": source,
            "session": session,
            "note": note,
        }
    return out


def what_would_change_view(band: str | None, levels: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The §4.2 triggers: the levels and readings that would move the stance, each with its current status."""
    spx = levels.get("SPX") or {}
    sup = (spx.get("support") or [{}])[0].get("level")
    res = (spx.get("resistance") or [{}])[0].get("level")
    triggers = [
        {"trigger": "SPX closes below the nearest stated support", "threshold": sup, "status": "armed" if sup else "no level"},
        {"trigger": "SPX closes above the nearest stated resistance", "threshold": res, "status": "armed" if res else "no level"},
        {"trigger": "VIX closes below 20 with breadth above 50%", "threshold": 20.0, "status": "armed"},
        {"trigger": "HY OAS widens more than 50 bp over 20 sessions", "threshold": 50.0, "status": "armed"},
        {"trigger": "MRE tier changes", "threshold": None, "status": "armed"},
    ]
    if band in ("RISK_OFF", "DEFENSIVE"):
        triggers.append({"trigger": "two consecutive evaluations in NEUTRAL-or-better", "threshold": 2,
                         "status": "not yet"})
    return triggers


__all__ = ["key_levels", "what_would_change_view", "CASH_SYMBOL"]
