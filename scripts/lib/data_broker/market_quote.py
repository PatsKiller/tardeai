"""Market Quote Batch — Data Broker read model for batch symbol pricing.

Batch-reads market_quotes (primary, Alpaca-repriced) through the ``latest_quote`` projection, with a
bounded live fallback for symbols that have no fresh stored row. Normalized for enrichment sweep
consumers. Replaces direct market_quotes SQL + yfinance fallback in watchlist_enrichment_sweep.py._price().

2026-10-10 (operator decision, CONSOLIDATION_PLAN.md §D.6/§D.7):

- The first pass reads :mod:`lib.data_broker.latest_quote` (one index probe per symbol) instead of
  ``DISTINCT ON (upper(symbol))``, which could not use the (symbol, fetched_at) index and
  sequentially scanned the append-only table on every call (96 ms vs 0.08 ms for five symbols).
- The live fallback was dead by accident: ``_best_quote`` passed ``max_age_seconds=`` to a
  ``get_best_quote(symbol)`` that took one argument, and the TypeError was swallowed, so a miss
  returned nothing. It now calls the quote-only mode of ``get_best_quote`` (stored quote first,
  then providers in chain order, stopping at the first fresh answer — never the four-provider
  fan-out), at most ``LIVE_FALLBACK_MAX_PER_BATCH`` symbols per call, each under a real 5 s bound
  (the executor no longer waits for a stalled provider on exit).
"""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

#: A batch that misses more symbols than this answers the rest from the store or not at all. The
#: fallback was dead (0 provider calls) until 2026-10-10; this keeps a bulk page from turning into
#: hundreds of sequential provider calls now that it works.
LIVE_FALLBACK_MAX_PER_BATCH = 10
LIVE_FALLBACK_TIMEOUT_S = 5.0

#: The operator price rule (2026-11-07): a live price is the Finviz cache when it is younger than
#: ``portfolio_positions.price_stale_after_s``, else a fresh broker quote — and never a stored print
#: older than this. One constant, one reader (:func:`fresh_price`), so no lane re-derives it.
PRICE_MAX_AGE_S = 30 * 60

#: Providers whose quote is a delayed display price, never a price to plan or decide on. The
#: operator rule (2026-11-07) says never yfinance; the quote-only waterfall asks it third, so a
#: symbol whose brokers are silent would otherwise come back "priced" from a delayed feed.
DISALLOWED_PRICE_PROVIDERS = frozenset({"yfinance", "yahoo"})


def _ensure_scripts_path() -> None:
    scripts = str(PROJECT_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _best_quote(symbol: str, max_age_s: int = 900) -> dict[str, Any] | None:
    """Fallback for one symbol without a fresh stored row: quote-only ``get_best_quote``.

    Quote-only mode reads the stored quote first and asks providers in chain order only while the
    answer is stale, stopping at the first fresh one (no fan-out). Bounded by
    ``LIVE_FALLBACK_TIMEOUT_S``: the broker waterfall reaches Schwab/Yahoo, which can stall for
    10+ seconds on delisted/CUSIP symbols; on timeout the worker is abandoned, not awaited.
    The stored read is skipped (``skip_stored=True``): the caller has just read the store and the
    symbol was stale or missing there. The caller's DB handle never crosses into the worker thread.
    """
    _ensure_scripts_path()

    from market_quote_provider import quote_only_enabled

    if not quote_only_enabled():
        return None  # kill switch: the fallback is off, as it was (by accident) before 2026-10-10

    def _fetch():
        from market_quote_provider import get_best_quote
        return get_best_quote(symbol, max_age_seconds=max_age_s, skip_stored=True) or {}

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        q = ex.submit(_fetch).result(timeout=LIVE_FALLBACK_TIMEOUT_S)
    except Exception:
        return None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    price = q.get("price") if q.get("price") is not None else q.get("last_price")
    if price is None:
        return None
    if str(q.get("provider") or "").strip().lower() in DISALLOWED_PRICE_PROVIDERS:
        # A delayed display quote is not a price under the operator rule. Returning None is the
        # honest answer: the caller then says "no current quote" instead of pricing off it.
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    return {
        "price": price,
        "chg_pct": q.get("change_percent") or q.get("chg_pct") or q.get("day_change_pct"),
        "as_of": q.get("quote_timestamp") or q.get("as_of") or q.get("fetched_at"),
        "provider": q.get("provider"),
        "stale": bool(q.get("stale")),
    }


def _extended_batch(db_query, symbols: list[str], window_s: float,
                    now: Any = None) -> dict[str, dict[str, Any]]:
    """Newest extended-hours mark per symbol from ``market_quotes_extended`` (LQ-20261107-1264 AMENDMENT 1).

    ``market_quotes`` holds the regular session only, so a name that moved after 16:00 read "now —" on the cards even
    while the after-hours/overnight lane had printed it. This reads the second store and returns the newest row per
    symbol, with the session name and a ready-to-render label. Read-only and fail-soft: a broken read is an empty map,
    never an exception in the caller's request thread.
    """
    from datetime import datetime, timezone

    from lib.session_now import mark_label

    if not symbols:
        return {}
    now = now or datetime.now(timezone.utc)
    try:
        rows = db_query(
            """SELECT DISTINCT ON (symbol) symbol, session, price, change_pct, reference_basis, bar_end, feed
                 FROM market_quotes_extended
                WHERE symbol = ANY(%s) AND bar_end >= %s
                ORDER BY symbol, bar_end DESC""",
            (symbols, now - __import__("datetime").timedelta(seconds=window_s)),
            "all",
        )
    except Exception:  # noqa: BLE001 -- the read failed; the caller is told so instead of being handed "none stored"
        # An empty map would read as "nothing printed after-hours", which is a DIFFERENT fact from "I could not look".
        # The caller marks its rows ``extended_unknown`` so the card can say the off-hours view is unavailable.
        return {"__unknown__": True}
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        sym, session, price, chg, basis, bar_end, feed = row
        if price is None or bar_end is None:
            continue
        level_only = not basis or str(basis).startswith("none_level_only") or chg is None
        out[str(sym).upper()] = {
            "price": float(price),
            "chg_pct": None if level_only else float(chg),
            "as_of": str(bar_end),
            "session": str(session),
            "feed": str(feed),
            "level_only": bool(level_only),
            "label": mark_label(session, bar_end, price, None if level_only else chg),
            "source": f"data_broker.market_quotes_extended:{feed}:{session}",
        }
    return out


def get_price_batch(db_query, symbols: list[str], max_age_hours: int = 12,
                    *, skip_live: bool = False, finviz_first: bool = True) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {price, chg_pct, as_of, source}} for a batch.

    Primary: the newest market_quotes row per symbol (latest_quote projection), kept when it is
    within ``max_age_hours``.
    Fallback: quote-only get_best_quote for symbols without a fresh row, at most
    ``LIVE_FALLBACK_MAX_PER_BATCH`` per call.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
        max_age_hours: max age of market_quotes rows to consider fresh.
        skip_live: when True, skip the get_best_quote live-API fallback entirely.
            Use for bulk-symbol pages (decision desk, watchlists) where blocking
            on 250+ Schwab/Yahoo calls would wedge the request thread.
    """
    from lib.data_broker.latest_quote import get_latest_quotes

    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}

    window_s = float(max_age_hours) * 3600.0
    latest = get_latest_quotes(db_query, symbols, max_age_seconds=window_s)

    out: dict[str, dict[str, Any]] = {}
    for sym in latest.get("fresh") or []:
        row = latest["symbols"][sym]
        out[sym] = {
            "price": row["price"],
            "chg_pct": row["chg_pct"],
            "as_of": row["as_of"],
            "source": f"data_broker.market_quotes:{row.get('provider') or 'market_quotes'}",
        }

    # Finviz first (operator 2026-11-07: live prices come from Finviz, not a DB row). A cache row younger than
    # positions.price_stale_after_s (30 min) replaces the market_quotes row; an older one never does, so a Finviz
    # outage falls back to the Schwab/Alpaca/moomoo rows above. Data-truth audit 2026-11-07: market_quotes served
    # PFE 27.56 from 16:45 ET while Finviz at 23:30 ET said 29.39.
    if finviz_first:
        try:
            from datetime import datetime, timedelta, timezone
            from lib import portfolio_positions as _pp
            _fv, _lim, _now = _pp.finviz_cache(), float(_pp.load_config()["price_stale_after_s"]), datetime.now(timezone.utc)
            for sym in symbols:
                fv = _fv.get(sym)
                age = _pp._age_s(fv.get("as_of"), _now) if fv else None
                if fv and age is not None and age <= _lim:
                    prev = out.get(sym) or {}
                    # The cache spells its stamp "2026-11-07 01:30:01 ET"; `as_of` leaves this function as an ISO
                    # instant, which is what every reader here expects. A strict consumer rejects the ET spelling
                    # outright (CIO ask research's make_fact raised "fact without as_of" on the first live run,
                    # 2026-11-07), so the overlay would have served its price and then lost the fact.
                    out[sym] = {"price": fv["price"], "chg_pct": prev.get("chg_pct"),
                                "as_of": (_now - timedelta(seconds=age)).isoformat(),
                                "source": "finviz_quote_cache"}
        except Exception:  # noqa: BLE001 -- the cache is an overlay; without it the DB rows above stand
            pass

    # LQ-20261107-1264 AMENDMENT 1: the newest mark wins, whichever store printed it. The regular-session (or Finviz)
    # row above is kept when it is newer; an after-hours / overnight / futures-open print replaces it when it is newer.
    from datetime import datetime as _dt

    ext_marks = _extended_batch(db_query, symbols, window_s)
    if ext_marks.pop("__unknown__", False):
        # the off-hours store could not be read: say so on every mark already found, never by silently keeping the
        # older regular-session row as though it were the newest print
        for row in out.values():
            row["extended_unknown"] = True
    for sym, ext in ext_marks.items():
        cur = out.get(sym)
        if cur is not None:
            try:
                if _dt.fromisoformat(str(cur["as_of"])) >= _dt.fromisoformat(str(ext["as_of"])):
                    continue
            except (TypeError, ValueError):
                continue  # an unparsable existing stamp is not evidence it is newer
        out[sym] = {**ext, "chg_pct": ext.get("chg_pct")}


    # Second pass: quote-only broker waterfall, only for missing symbols, bounded per batch.
    if not skip_live:
        missing = [s for s in symbols if s not in out][:LIVE_FALLBACK_MAX_PER_BATCH]
        for sym in missing:
            q = _best_quote(sym, max_age_s=int(max(900, window_s)))
            if q and not q.get("stale"):
                out[sym] = {
                    "price": q["price"],
                    "chg_pct": q.get("chg_pct"),
                    "as_of": q.get("as_of"),
                    "source": f"data_broker.market_quote:get_best_quote:{q.get('provider') or 'unknown'}",
                }
    return out


def quote_age_seconds(as_of) -> float | None:
    """Seconds since a quote's own stamp, or None when it cannot be read.

    Accepts an epoch number, an ISO string (``Z`` allowed), or a datetime; a naive stamp is UTC.
    Junk returns None, which every caller treats as "cannot date this quote" — an undated price is
    exactly what the operator rule forbids.
    """
    from datetime import datetime, timezone

    # None means "cannot date this quote", which every caller treats as no quote.
    # nosemgrep: tq-py-broad-except-returns-default -- an unstampable quote is refused, never treated as fresh
    try:
        if isinstance(as_of, (int, float)):
            stamp = datetime.fromtimestamp(float(as_of), timezone.utc)
        elif isinstance(as_of, str):
            stamp = datetime.fromisoformat(as_of.strip().replace("Z", "+00:00"))
        elif isinstance(as_of, datetime):
            stamp = as_of
        else:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
    except Exception:  # noqa: BLE001 -- an unreadable stamp cannot be aged
        return None


def fresh_price(db_query, symbol: str, *, max_age_s: float = PRICE_MAX_AGE_S,
                skip_live: bool = False) -> dict[str, Any] | None:
    """The symbol's current price under the operator rule (2026-11-07), or None.

    A ``finviz_quote_cache`` answer is taken outright — :func:`get_price_batch` only overlays the
    cache when it is younger than ``portfolio_positions.price_stale_after_s``. Any other answer is
    kept only when its own ``as_of`` is within ``max_age_s``; a stored print of any age, or an
    undated one, is None.

    None means "no price right now", and every caller must say so rather than fall back to a
    historical close or a stored row — that fallback is the defect this function exists to remove.
    """
    # nosemgrep: tq-py-broad-except-returns-default -- None means "no price right now"; the caller's skip is the safe direction
    try:
        quote = (get_price_batch(db_query, [symbol.upper()], max_age_hours=1,
                                 skip_live=skip_live, finviz_first=True) or {}).get(symbol.upper())
    except Exception:  # noqa: BLE001 -- a failed read is no price
        return None
    if not quote or quote.get("price") is None:
        return None
    if str(quote.get("source") or "") == "finviz_quote_cache":
        return quote
    src = str(quote.get("source") or "").lower()
    if any(bad in src for bad in DISALLOWED_PRICE_PROVIDERS):
        # "Finviz, never yfinance" binds a stored row too: market_quotes holds yfinance-sourced
        # rows (measured 2026-11-07: V 422.65, source yfinance), and a recent one is still a
        # delayed display print, not a price to plan or decide on.
        return None
    age = quote_age_seconds(quote.get("as_of"))
    if age is None or age > max_age_s:
        return None
    return quote
