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

LQ-20261107-1784 (operator 2026-11-10, "not clear what to do"): the rank showed penny/microcap data
accidents at the top (BDRX +636 %, ENHA +589 %) because it had no floor. Before a name may be RANKED it
must now also pass the floors in ``config/market_risk_policy.yaml`` ``sectors.constituents``:

* ``min_price`` — the latest ``ticker_prices`` close is at least this;
* ``min_avg_dollar_volume_usd`` — the 20-session average of ``market_ohlcv_bars`` close × volume is at
  least this (the only volume owner in the DB). A name whose dollar volume cannot be measured (no bars)
  is kept and counted as unmeasured, never mistaken for proof of illiquidity;
* ``max_abs_rs20`` — a |RS20| above it is a data error (unadjusted history), dropped and counted, never
  ranked;
* ``max_split_diff_pct`` — the ``ticker_prices`` close and the ``market_ohlcv_bars`` close for the same
  session inside the RS window must agree within this; a wider gap is a split/unadjusted-history artifact.

A HELD name is a fact about the book, so it is listed whatever its numbers. When a floor fails it carries
a plain ``flag`` (``no reliable price — review`` / ``below $5.00 — review`` / ``illiquid — review``) and,
for a split/RS-sanity failure, no RS20 fact (an unreliable rank is not shown as one).

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
#: LQ-20261107-1784 floors. The operator owns these numbers in ``sectors.constituents``; these are the fallback.
MIN_PRICE = 5.00
MIN_AVG_DOLLAR_VOLUME_USD = 10_000_000.0
MAX_ABS_RS20 = 100.0
MAX_SPLIT_DIFF_PCT = 5.0
#: Sessions in the dollar-volume average (the same 20 the rank uses).
VOLUME_LOOKBACK_SESSIONS = 20
PRICE_SOURCE = "ticker_prices:daily"
BAR_SOURCE = "market_ohlcv_bars:daily"
SPY = "SPY"


def _positive_int(value: Any) -> int | None:
    """An int from the policy, or None for anything that is not one (a bool is not a count)."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _positive_number(value: Any) -> float | None:
    """A positive number from the policy, or None (a bool is not a number)."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


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
    """The contract's thresholds: groups, ranked top_n, RS window, bar lookback, and the LQ-1784 floors.

    ``config/market_risk_policy.yaml`` ``sectors.constituents`` is the operator-owned home of these numbers;
    the module constants are used only when a value is absent or not a positive number. ``policy_gap`` names why the
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
        # LQ-20261107-1784: the NO-FALSE-POSITIVES floors. Zero is not a threshold here — a 0 floor would
        # silently disable the check, so a non-positive value falls back to the module constant.
        "min_price": _positive_number(block.get("min_price")) or MIN_PRICE,
        "min_avg_dollar_volume_usd": (_positive_number(block.get("min_avg_dollar_volume_usd"))
                                      or MIN_AVG_DOLLAR_VOLUME_USD),
        "max_abs_rs20": _positive_number(block.get("max_abs_rs20")) or MAX_ABS_RS20,
        "max_split_diff_pct": _positive_number(block.get("max_split_diff_pct")) or MAX_SPLIT_DIFF_PCT,
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


def _bar_series(rows: Iterable[Mapping] | None) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """``({symbol: {session: close}}, {symbol: {session: volume}})`` from ``market_ohlcv_bars`` daily rows.

    A bar without a positive close is not a bar. Volume is kept only when it is a number, so an absent
    volume leaves the dollar volume unmeasured instead of being read as zero.
    """
    closes: dict[str, dict[str, float]] = {}
    volumes: dict[str, dict[str, float]] = {}
    for r in rows or []:
        sym = str((r or {}).get("symbol") or "").upper()
        day = str((r or {}).get("session") or "")[:10]
        close = _num((r or {}).get("close"))
        if not sym or not day or close is None or close <= 0:
            continue
        prior = closes.setdefault(sym, {}).get(day)
        if prior is None or close > prior:
            closes[sym][day] = close
        vol = _num((r or {}).get("volume"))
        if vol is not None and vol >= 0:
            prior_v = volumes.setdefault(sym, {}).get(day)
            if prior_v is None or vol > prior_v:
                volumes[sym][day] = vol
    return closes, volumes


def _avg_dollar_volume(bar_closes: Mapping[str, float] | None, bar_volumes: Mapping[str, float] | None,
                       sessions: int = VOLUME_LOOKBACK_SESSIONS) -> float | None:
    """The mean close × volume over the last ``sessions`` daily bars, or None when it cannot be measured."""
    shares = set(bar_closes or {}) & set(bar_volumes or {})
    days = sorted(shares)[-max(1, int(sessions)):]
    if not days:
        return None
    return sum(bar_closes[d] * bar_volumes[d] for d in days) / len(days)


def _split_mismatch(series: Iterable[tuple[str, float]], bar_closes: Mapping[str, float] | None,
                    window_sessions: int, max_pct: float) -> tuple[bool, float]:
    """``(the two sources disagree beyond tolerance inside the RS window, the worst gap %)``.

    A split (or any unadjusted-history artifact) makes the stored close and the bar close for the SAME
    session disagree. Only the sessions that feed the rank are compared: an old split outside the window
    has already been absorbed by the 20-session return and is not a reason to drop a live name.
    """
    window = list(series)[-(max(1, int(window_sessions)) + 1):]
    worst = 0.0
    for day, close in window:
        bar = (bar_closes or {}).get(day)
        if bar is None or bar <= 0 or close <= 0:
            continue
        worst = max(worst, abs(close / bar - 1.0) * 100.0)
    return worst > max_pct, worst


def _floor_failures(symbol: str, close: float, rs20: float | None, series: Iterable[tuple[str, float]],
                    bar_closes: Mapping[str, Mapping[str, float]] | None,
                    bar_volumes: Mapping[str, Mapping[str, float]] | None, *,
                    min_price: float, min_adv: float, max_abs_rs20: float,
                    max_split_pct: float, rs_window: int) -> tuple[list[str], float | None]:
    """``([every floor a name fails], its measured 20-session dollar volume or None)``.

    The order of the list is the display priority of the held flag: an unreliable price (split / data
    error) outranks a cheap or illiquid one, because it is the stronger statement.
    """
    failed: list[str] = []
    if close < min_price:
        failed.append("below_price")
    if rs20 is not None and abs(rs20) > max_abs_rs20:
        failed.append("rs_sanity")
    split, _worst = _split_mismatch(series, (bar_closes or {}).get(symbol), rs_window, max_split_pct)
    if split:
        failed.append("split_mismatch")
    adv = _avg_dollar_volume((bar_closes or {}).get(symbol), (bar_volumes or {}).get(symbol))
    if adv is not None and adv < min_adv:
        failed.append("below_liquidity")
    return failed, adv


def _held_flag(failed: Iterable[str], min_price: float) -> str | None:
    """The plain words a held name carries when a floor fails (the book owns it, so it is still shown)."""
    keys = set(failed)
    if keys & {"rs_sanity", "split_mismatch"}:
        return "no reliable price — review"
    if "below_price" in keys:
        return f"below ${min_price:,.2f} — review"
    if "below_liquidity" in keys:
        return "illiquid — review"
    return None


def _filter_note(excluded: Mapping[str, int], unmeasured: int, labels: Mapping[str, str]) -> str | None:
    """The one-line count of names the floors removed, and of names kept with unmeasured volume."""
    parts = [f"{n} {labels[k]}" for k, n in excluded.items() if n]
    if not parts and not unmeasured:
        return None
    note = f"Excluded: {', '.join(parts)}." if parts else ""
    if unmeasured:
        note = (note + f" {unmeasured} kept with unmeasured dollar volume.").strip()
    return note or None


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

    # LQ-20261107-1784: the volume owner. The split guard and the dollar-volume floor both compare against
    # this store, so its failure is a named gap; a name whose liquidity cannot be measured is kept and
    # counted (unmeasured is not illiquid), never dropped on the strength of a failed read.
    volume_closes: dict[str, dict[str, float]] = {}
    volume_volumes: dict[str, dict[str, float]] = {}
    volume_gap = None
    try:
        vol_rows = db_query(
            "SELECT upper(symbol) AS symbol, bar_time::date AS session, max(close) AS close, "
            "max(volume) AS volume FROM market_ohlcv_bars "
            "WHERE timeframe = 'daily' AND upper(symbol) = ANY(%s) AND close IS NOT NULL "
            "AND bar_time > CURRENT_DATE - %s "
            "GROUP BY upper(symbol), bar_time::date ORDER BY upper(symbol), bar_time::date",
            (symbols, int(days)),
        )
        if vol_rows is None:
            volume_gap = "volume history unavailable"
    except Exception as exc:  # noqa: BLE001 -- same rule: the gap names the cause
        vol_rows, volume_gap = None, f"volume history unavailable ({type(exc).__name__})"
    volume_closes, volume_volumes = _bar_series(vol_rows)

    min_price = thresholds["min_price"]
    min_adv = thresholds["min_avg_dollar_volume_usd"]
    max_abs_rs20 = thresholds["max_abs_rs20"]
    max_split_pct = thresholds["max_split_diff_pct"]
    rs_window = thresholds["rs_window_sessions"]
    labels_for = {
        "below_price": f"under ${min_price:,.2f}",
        "below_liquidity": f"under ${min_adv / 1_000_000:,.1f}M/day",
        "rs_sanity": f"|RS20| > {max_abs_rs20:g} (data error)",
        "split_mismatch": f"prices disagree by > {max_split_pct:g}% (split artifact)",
    }

    out: dict[str, dict] = {}
    for group, group_labels in sectors_by_group(groups).items():
        members = {sym for sym, meta in universe.items() if meta["group"] == group}
        members |= {sym for sym, g in held_group.items() if g == group}
        rows: list[dict] = []
        measured = 0
        excluded = {k: 0 for k in labels_for}
        unmeasured_liquidity = 0
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
            is_held = sym in held_group
            failed, adv = _floor_failures(sym, close, signal.get("rs20"), series, volume_closes, volume_volumes,
                                          min_price=min_price, min_adv=min_adv, max_abs_rs20=max_abs_rs20,
                                          max_split_pct=max_split_pct, rs_window=rs_window)
            if failed and not is_held:
                for key in failed:
                    excluded[key] += 1
                continue
            if adv is None:
                unmeasured_liquidity += 1
            rank_trusted = not ({"rs_sanity", "split_mismatch"} & set(failed))
            row = {
                "symbol": sym,
                "source_id": f"{PRICE_SOURCE}:{sym}",
                "rs_source_id": f"ticker_prices:rs20_vs_spy:{sym}",
                "sector": held_sector.get(sym) or (universe.get(sym) or {}).get("sector"),
                "held": is_held,
                "held_value_usd": round(held_value[sym], 2) if sym in held_value else None,
                "close": close,
                "close_as_of": series[-1][0],
                # a split / RS-sanity failure means the rank itself is untrustworthy: do not carry it
                "rs20": signal.get("rs20") if rank_trusted else None,
                "rs20_as_of": signal.get("as_of") if rank_trusted else None,
            }
            if is_held and failed:
                # the holding is a fact about the book: still listed, plainly flagged
                row["flag"] = _held_flag(failed, min_price)
            rows.append(row)
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
        filter_note = _filter_note(excluded, unmeasured_liquidity, labels_for)
        gap = None
        if not picked:
            gap = bars_gap or volume_gap or profile_gap or filter_note or "no constituent with a measured close"
        out[group] = {
            "sector": list(group_labels),
            "source_id": PRICE_SOURCE,
            "bar_source_id": BAR_SOURCE,
            "as_of": spy_series[-1][0] if spy_series else None,
            "universe": len(members - skip),
            "measured": measured,
            "rows": picked,
            "gap": gap,
            "excluded": {k: n for k, n in excluded.items() if n},
            "unmeasured_liquidity": unmeasured_liquidity or None,
            "filter_note": filter_note,
            # LQ-20261107-1784: the floor the list was drawn under, so the card's caption names the operator's
            # number rather than a copy of it that goes stale when the contract changes.
            "min_price": min_price,
        }
    return out
