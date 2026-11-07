"""Price evidence for a stop alert: a mark is never shown bare.

Operator price rule (2026-11-07): a live price comes from the Finviz cache
(``finviz_quote_cache.json``, fresh = ``last_fetched`` <= 30 min); if Finviz is down or stale, a fresh
Schwab / Alpaca / moomoo quote; never yfinance, never a stored DB price older than 30 min.

So every stop alert carries the mark's **price, source and as_of**, and a mark that is undated or past
``positions.price_stale_after_s`` is labelled STALE — never presented as the live price. LQ-20261107-03:
``stop_lifecycle_monitor`` and ``stop_drift_alert`` built their alerts from stored prices with no provenance.

The mark itself is never re-derived here: ``portfolio_positions.resolve_mark`` is the one rule, and these
helpers only carry and render what it returned. Pure functions over the values handed in — no DB, no
broker, no I/O of their own beyond the shared holdings/quote readers the callers already trusted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

#: The evidence fields every stop-alert record and payload carries alongside ``current_price``.
MARK_FIELDS = ("price_source", "price_as_of", "price_age_s", "price_stale")

_AUTO = object()   # default argument: read the shared Finviz cache / data-broker backup


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None   # NaN -> None


def mark_fields(mark: dict | None) -> dict:
    """The four price-evidence fields for an alert, from a ``resolve_mark()`` result (None = unknown)."""
    mark = mark if isinstance(mark, dict) else {}
    stale = mark.get("stale")
    return {
        "price_source": mark.get("source") or None,
        "price_as_of": mark.get("as_of") or None,
        "price_age_s": mark.get("age_s"),
        "price_stale": None if stale is None else bool(stale),
    }


def age_text(age_s: Any) -> Optional[str]:
    """A human age ('45s', '12m', '3.2h', '2.0d'); None when the age is unknown or negative."""
    s = _f(age_s)
    if s is None or s < 0:
        return None
    if s < 90:
        return f"{int(round(s))}s"
    if s < 5400:
        return f"{int(round(s / 60))}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def price_line(price: Any, source: Any, as_of: Any, age_s: Any = None, stale: Any = None) -> str:
    """One-line mark evidence for an alert message.

    A fresh mark reads ``mark $204.64 (finviz, as of 2026-11-07T14:45:00Z)``. A mark that is stale,
    undated, or of unknown freshness reads ``mark $204.64 STALE (stored_mark, as of 2026-11-06T16:00:00Z,
    22.7h old — not live)``. A missing price says UNKNOWN; an alert never invents one.
    """
    px = _f(price)
    if px is None or px <= 0:
        return "mark UNKNOWN (no priced source: Finviz, broker quote and stored mark all unavailable)"
    # A sub-dollar mark keeps four decimals: SRNE is $0.0003, and "$0.00" would put an invented zero in an alert.
    shown = f"${px:,.4f}" if px < 1 else f"${px:,.2f}"
    src = str(source or "unknown source")
    when = str(as_of) if as_of else "no timestamp"
    if stale is False:
        return f"mark {shown} ({src}, as of {when})"
    # Anything we cannot prove fresh is stale: "unknown" must never read as "live".
    age = age_text(age_s)
    why = f"{age} old" if age else ("undated" if not as_of else "age unknown")
    return f"mark {shown} STALE ({src}, as of {when}, {why} — not live)"


def labelled_mark(price: Any, source: Any, as_of: Any, *, now: Optional[datetime] = None,
                  cfg: dict | None = None) -> dict:
    """A mark for a value that did not come from ``resolve_mark`` (e.g. a research advisory's snapshot
    price), labelled with its source + as_of and aged by the same ``price_stale_after_s`` rule. A price
    with no timestamp is stale by definition — it can never be shown as live.
    """
    from lib.portfolio_positions import _age_s, load_config
    cfg = cfg or load_config()
    age = _age_s(as_of, now or datetime.now(timezone.utc))
    stale = age is None or age > float(cfg["price_stale_after_s"])
    return {"price": _f(price), "source": source, "as_of": str(as_of) if as_of else None,
            "age_s": None if age is None else round(age), "stale": stale}


def holdings_marks(document: dict | None = None, *, finviz: Any = _AUTO, quotes: Any = _AUTO,
                   now: Optional[datetime] = None) -> list[dict]:
    """Every held row, marked by ``resolve_mark()`` and carrying its price evidence.

    Holdings are DB-first — ``holdings_document.load_document()`` (holdings.json is its stated fallback).
    The mark is the operator's rule: the Finviz live cache first, a fresh Schwab/Alpaca/moomoo quote
    second (the data broker's batch, read only for symbols Finviz cannot serve fresh), a stored mark last.
    Cash rows are skipped (no stop rests on cash), and a row with no price is dropped rather than marked 0.

    Each result: ``symbol, account, shares, broker_shares, cost_basis, price, price_source, price_as_of,
    price_age_s, price_stale, held`` (``held`` is the source row). Never raises: an unreadable store
    returns [] so the caller's alert path stays closed instead of inventing a price.
    """
    try:
        from lib.holdings_document import load_document
        from lib.portfolio_positions import finviz_cache, is_cash, resolve_mark
    except Exception:  # noqa: BLE001 -- no shared readers, no marks
        return []
    try:
        doc = document if isinstance(document, dict) else load_document()
    except Exception:  # noqa: BLE001 -- load_document states its own fallback; a raise means no document
        return []
    rows = [r for r in (doc.get("holdings") or []) if isinstance(r, dict)]
    fv = finviz_cache() if finviz is _AUTO else finviz
    fv = fv if isinstance(fv, dict) else {}
    backup = _backup_quotes(fv, rows, now) if quotes is _AUTO else quotes
    backup = backup if isinstance(backup, dict) else {}

    out: list[dict] = []
    for r in rows:
        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
        if not sym or is_cash(r):
            continue
        fv_row = fv.get(sym) if isinstance(fv.get(sym), dict) else None
        mark = resolve_mark(r, quote=backup.get(sym), finviz=fv_row, now=now)
        if not mark.get("price"):
            continue
        shares = _f(r.get("shares", r.get("qty")))
        bsh = _f(r.get("broker_actual_shares"))
        out.append({
            "symbol": sym,
            "account": str(r.get("account") or ""),
            "shares": shares,
            "broker_shares": bsh,
            "cost_basis": _f(r.get("cost_basis")),
            "price": mark["price"],
            **mark_fields(mark),
            "held": r,
        })
    return out


def _backup_quotes(finviz: dict, rows: list[dict], now: Optional[datetime]) -> dict:
    """Fresh Schwab/Alpaca/moomoo marks for held symbols the Finviz cache cannot serve (down or stale).

    Read-only, through the shared data broker's ``get_price_batch`` — no new fetcher and no live broker
    call (``skip_live=True``). {} when Finviz covers every held symbol or the database is unavailable;
    the caller then labels each stored mark stale.
    """
    try:
        from lib.data_broker.market_quote import get_price_batch
        from lib.holdings_document import default_db_query
        from lib.portfolio_positions import _age_s, load_config
        db = default_db_query()
        if db is None:
            return {}
        limit = float(load_config()["price_stale_after_s"])
        at = now or datetime.now(timezone.utc)
        need = set()
        for r in rows:
            sym = str(r.get("symbol") or r.get("ticker") or "").upper()
            if not sym or r.get("is_cash"):
                continue
            age = _age_s((finviz.get(sym) or {}).get("as_of"), at) if isinstance(finviz.get(sym), dict) else None
            if age is None or age > limit:
                need.add(sym)
        if not need:
            return {}
        return get_price_batch(db, sorted(need), skip_live=True) or {}
    except Exception:  # noqa: BLE001 -- the backup is an overlay; without it the mark is stale-labelled
        return {}
