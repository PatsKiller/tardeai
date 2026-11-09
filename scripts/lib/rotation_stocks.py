"""Individual-stock candidates under a defensive rotation group (LQ-20261107-1655).

The rotate column of the Home CIO card has always named the sector ETF (XLV / XLP / XLU). The operator
asked for the names under it: for each defensive group the book already holds in that sector, list those
first, then the group's best constituents ranked by relative strength vs SPY over exactly 20 sessions.

Read-only, and reuses the two owners of the facts rather than re-deriving them:

* sector membership — ``symbol_profiles`` (the canonical per-symbol sector lookup; ``instrument_type``
  must be ``stock``), mapped to the market-risk group keys by ``market_risk.lookthrough.SECTOR_TO_GROUP``
  (the same map the look-through join uses, so a held name lands in the same group as its exposure);
* prices and relative strength — ``ticker_prices`` (the stored daily closes the Sectors page's RS is
  computed from; ``sector_signals.relative_strength`` is the exact SPY-session RS20 owner, reused here).
  ``market_ohlcv_bars`` was measured first and covers only ~3 % of the healthcare constituents on the exact
  21-session window, which would have ranked data accidents instead of names; ``ticker_prices`` covers 91 %.

Every row carries the session its close came from. A symbol with no dated close is DROPPED, never filled
in; a name ranked among constituents needs a measured RS20 (a missing SPY session makes the horizon
incomplete, and an incomplete horizon is not a rank). A held name is listed on the strength of the
holding even when its RS20 cannot be measured, but it still needs a dated close.

The numbers are the operator's, not this file's: ``config/market_risk_policy.yaml`` ``sectors.constituents``
carries the group set, ``top_n``, the RS window and the bar lookback (``defaults``). The module constants are
the fallback for a policy that cannot be read — the card draws on the last rule this file knew rather than
failing to render.

Advisory only (MBI_BEHAVIOR = 0): a count of names, a close, a relative-strength figure. Never an order,
a weight, a stop or a broker read.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from lib.home_cio_card import DEFENSIVE_KEYS
from lib.market_risk.lookthrough import SECTOR_TO_GROUP
from lib.sector_signals import relative_strength

#: The market-risk group keys the rotate column covers — one owner: the projection that draws the column.
GROUPS = tuple(DEFENSIVE_KEYS)
#: Calendar days of daily bars read: 21 sessions of RS20 plus a comfortable buffer for holidays.
BAR_LOOKBACK_DAYS = 70
#: Constituents listed after the held names, per group.
TOP_N = 5
#: The RS window the rank uses. It is the owner's (``sector_signals.relative_strength`` rs20); this constant exists
#: so the contract test can pin the number in ``config/market_risk_policy.yaml`` to that behaviour.
RS_WINDOW_SESSIONS = 20
PRICE_SOURCE = "ticker_prices:daily"
SPY = "SPY"


def _positive_int(value: Any) -> int | None:
    """An int from the policy, or None for anything that is not one (a bool is not a count)."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _policy_constituents() -> tuple[Mapping, str | None]:
    """``(the operator's sectors.constituents block, why it could not be read)``.

    A policy that cannot be read must not stop the card drawing: the reason travels back with the empty block, so
    the fallback is a stated unknown (``policy_gap`` in ``defaults()``) and never a confident "the policy says
    nothing". The module constants are then the thresholds — the card draws on the last rule this file knew.
    """
    try:
        from lib.market_risk.policy import load_policy

        block = (load_policy().get("sectors") or {}).get("constituents")
        return (block, None) if isinstance(block, Mapping) else ({}, "policy has no sectors.constituents block")
    except Exception as exc:  # noqa: BLE001 -- a missing/unreadable policy is a fallback, never a card failure
        return {}, f"policy unreadable ({type(exc).__name__})"


def defaults() -> dict[str, Any]:
    """The contract's thresholds: groups, ranked top_n, RS window, bar lookback.

    ``config/market_risk_policy.yaml`` ``sectors.constituents`` is the operator-owned home of these numbers;
    the module constants are used only when a value is absent or not a positive int. ``policy_gap`` names why the
    policy could not be read (``None`` when it was), so a fallback is visible rather than silent.
    """
    block, policy_gap = _policy_constituents()
    groups = tuple(g for g in (block.get("groups") or ()) if isinstance(g, str) and g in SECTOR_TO_GROUP.values())
    return {
        "groups": groups or GROUPS,
        "top_n": _positive_int(block.get("top_n")) or TOP_N,
        "rs_window_sessions": _positive_int(block.get("rs_window_sessions")) or RS_WINDOW_SESSIONS,
        "bar_lookback_days": _positive_int(block.get("bar_lookback_days")) or BAR_LOOKBACK_DAYS,
        "held_first": bool(block.get("held_first", True)),
        "drop_untraceable": bool(block.get("drop_untraceable", True)),
        "policy_gap": policy_gap,
    }


def sectors_by_group(groups: Iterable[str] | None = None) -> dict[str, tuple[str, ...]]:
    """{group: sector labels that map to it}, from the look-through map (one owner, not a second copy)."""
    keys = tuple(groups) if groups is not None else defaults()["groups"]
    inv: dict[str, list[str]] = {}
    for label, key in SECTOR_TO_GROUP.items():
        if key in keys:
            inv.setdefault(key, []).append(label)
    return {k: tuple(sorted(v)) for k, v in inv.items()}


def group_of(sector: Any, groups: Iterable[str] | None = None) -> str | None:
    """The defensive group a sector label belongs to, or None (a theme, a fund category, a blank)."""
    keys = tuple(groups) if groups is not None else defaults()["groups"]
    key = SECTOR_TO_GROUP.get(str(sector or "").strip().lower())
    return key if key in keys else None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _series(rows: Iterable[Mapping] | None) -> dict[str, dict[str, float]]:
    """{symbol: {session: close}}. Duplicate sessions keep the highest close (the owner's GROUP BY does too)."""
    out: dict[str, dict[str, float]] = {}
    for r in rows or []:
        sym = str((r or {}).get("symbol") or "").upper()
        day = str((r or {}).get("session") or "")[:10]
        close = _num((r or {}).get("close"))
        if not sym or not day or close is None or close <= 0:
            continue
        by_day = out.setdefault(sym, {})
        # no stand-in for an absent session: the first close is the one kept, a later higher one replaces it
        prev = by_day.get(day)
        if prev is None or close > prev:
            by_day[day] = close
    return out


def read(db_query: Callable[..., Any], *, held: Iterable[Mapping] | None = None,
         exclude: Iterable[str] | None = None, limit: int | None = None,
         days: int | None = None) -> dict[str, dict]:
    """Build the per-group constituent rows. ``db_query(sql, params)`` returns dict rows, or None on failure.

    ``held`` rows carry ``symbol``, ``sector`` and a dollar value (``value_usd`` or ``market_value``).
    ``exclude`` drops symbols that are already a row of their own (the group ETFs). A group with nothing
    measurable still returns a block with ``rows: []`` and a ``gap`` that names why. ``limit`` and ``days``
    default to ``config/market_risk_policy.yaml`` ``sectors.constituents`` (see ``defaults``); an explicit
    argument wins, so a caller can ask for more names without editing the operator's file.
    """
    thresholds = defaults()
    groups = thresholds["groups"]
    limit = thresholds["top_n"] if limit is None else limit
    days = thresholds["bar_lookback_days"] if days is None else days
    labels = sorted({label for group_labels in sectors_by_group(groups).values() for label in group_labels})
    skip = {str(s).upper() for s in (exclude or ())} | {SPY}

    universe: dict[str, dict] = {}
    try:
        profiles = db_query(
            "SELECT upper(symbol) AS symbol, sector FROM symbol_profiles "
            "WHERE instrument_type = 'stock' AND lower(sector) = ANY(%s)",
            (labels,),
        )
        profile_gap = None if profiles is not None else "sector membership unavailable"
    except Exception as exc:  # noqa: BLE001 -- a failed read is reported as a gap, never as an empty sector
        profiles, profile_gap = None, f"sector membership unavailable ({type(exc).__name__})"
    for r in profiles or []:
        sym = str((r or {}).get("symbol") or "").upper()
        group = group_of((r or {}).get("sector"), groups)
        if sym and group:
            universe[sym] = {"group": group, "sector": str((r or {}).get("sector"))}

    held_value: dict[str, float] = {}
    held_group: dict[str, str] = {}
    held_sector: dict[str, str] = {}
    for h in held or []:
        if not isinstance(h, Mapping) or h.get("is_cash"):
            continue
        sym = str(h.get("symbol") or "").upper()
        group = group_of(h.get("sector"), groups)
        if not sym or not group or sym in skip:
            continue
        value = _num(h.get("value_usd") if h.get("value_usd") is not None else h.get("market_value"))
        held_group[sym] = group
        held_sector[sym] = str(h.get("sector"))
        # only a known value is stored: an unreadable holding is listed, but never sorted as a zero
        if value is None:
            continue
        prior = held_value.get(sym)
        if prior is None or value > prior:
            held_value[sym] = value

    # SPY is the benchmark: always read, never a candidate row (``members - skip`` drops it below).
    symbols = sorted(set(universe) | set(held_group) | {SPY})
    bars_gap = None
    try:
        bars = db_query(
            "SELECT upper(symbol) AS symbol, price_date AS session, max(close_price) AS close FROM ticker_prices "
            "WHERE upper(symbol) = ANY(%s) AND close_price > 0 AND price_date > CURRENT_DATE - %s "
            "GROUP BY upper(symbol), price_date ORDER BY upper(symbol), price_date",
            (symbols, int(days)),
        )
        if bars is None:
            bars_gap = "price history unavailable"
    except Exception as exc:  # noqa: BLE001 -- same rule: the gap names the cause
        bars, bars_gap = None, f"price history unavailable ({type(exc).__name__})"
    closes = _series(bars)
    spy_series = sorted(closes.get(SPY, {}).items())

    out: dict[str, dict] = {}
    for group, group_labels in sectors_by_group(groups).items():
        members = {sym for sym, meta in universe.items() if meta["group"] == group}
        members |= {sym for sym, g in held_group.items() if g == group}
        rows: list[dict] = []
        measured = 0
        for sym in sorted(members - skip):
            series = sorted(closes.get(sym, {}).items())
            if not series:
                continue  # untraceable: no dated close, dropped
            close = round(series[-1][1], 2)
            if close <= 0:
                continue  # a sub-cent print is not a usable close, and a share count from it would be noise
            signal = relative_strength(series, spy_series) if spy_series else {"rs20": None, "as_of": None}
            if signal.get("rs20") is not None:
                measured += 1
            rows.append({
                "symbol": sym,
                "source_id": f"{PRICE_SOURCE}:{sym}",
                "rs_source_id": f"ticker_prices:rs20_vs_spy:{sym}",
                "sector": held_sector.get(sym) or (universe.get(sym) or {}).get("sector"),
                "held": sym in held_group,
                "held_value_usd": round(held_value[sym], 2) if sym in held_value else None,
                "close": close,
                "close_as_of": series[-1][0],
                "rs20": signal.get("rs20"),
                "rs20_as_of": signal.get("as_of"),
            })
        kept = [r for r in rows if r["held"]]
        # a held name with a known value leads, by value; a held name whose value could not be read still
        # leads the sector (the ticket says held first) but sorts after the known ones, never as a zero
        known = sorted((r for r in kept if r["held_value_usd"] is not None),
                       key=lambda r: (-r["held_value_usd"], r["symbol"]))
        unknown = sorted((r for r in kept if r["held_value_usd"] is None), key=lambda r: r["symbol"])
        kept = known + unknown
        ranked = [r for r in rows if not r["held"] and r["rs20"] is not None]
        ranked.sort(key=lambda r: (-r["rs20"], r["symbol"]))
        picked = kept + ranked[:max(0, int(limit))]
        gap = None
        if not picked:
            gap = bars_gap or profile_gap or "no constituent with a measured close"
        out[group] = {
            "sector": list(group_labels),
            "source_id": PRICE_SOURCE,
            "as_of": spy_series[-1][0] if spy_series else None,
            "universe": len(members - skip),
            "measured": measured,
            "rows": picked,
            "gap": gap,
        }
    return out
