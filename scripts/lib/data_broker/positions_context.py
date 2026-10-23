"""Positions Context — Data Broker read model for "if I own it" (Investment Command Center, operator 2026-10-08).

Per symbol, aggregated across accounts: shares, market value, average cost, cost basis, unrealized gain/loss,
portfolio weight — read through lib/portfolio_positions (the one accessor for the holdings_accounts store), plus
the last sell date from the broker ledger trade_transactions (drives "recently sold").

Realized gain/loss and days held are NOT derived here: a FIFO over trade_transactions mixed pre/post-split prices
and transfer-reset lot dates (SCHD showed +$138,787 realized, 2026-10-08). Their authority is positions_store
(position_lots / realized_lots, which reproduce the broker); they stay "pending" until that reader is approved.

The positions_store tables (positions_current / position_lots / realized_lots) are SHADOW until the operator approves
each phase-3 reader batch (config/data_source_authority.json) — this module does not read them.
Zero provider calls. Read-only.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_positions_context(db_query, symbols: list[str], *, today: date | None = None,
                          holdings_path: Optional[Path] = None,
                          quotes: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, dict[str, Any]]:
    """Per symbol across accounts. Positions come through lib/portfolio_positions (the ONE accessor: price from
    the data-broker quote at read time, never a stored current_price; value = shares × price; P&L = value − cost)."""
    try:
        from scripts.lib import portfolio_positions as pp
    except ImportError:  # pragma: no cover - flat import layout
        from lib import portfolio_positions as pp  # type: ignore
    syms = sorted({str(s).upper().strip() for s in symbols if s and str(s).strip()})
    if not syms:
        return {}
    out: dict[str, dict[str, Any]] = {}
    doc = pp.load_store(holdings_path)
    as_of = doc.get("as_of") or doc.get("data_as_of")
    total_value = _f((doc.get("portfolio_totals") or {}).get("total_value"))
    quotes = quotes or {}
    for r in doc.get("holdings") or []:
        s = str(r.get("symbol") or "").upper()
        qty = _f(r.get("shares", r.get("quantity")))
        if s not in syms or not qty or qty <= 0 or pp.is_cash(r):
            continue
        mark = pp.resolve_mark(r, quote=quotes.get(s))
        vp = pp.value_and_pl(r, mark)
        o = out.setdefault(s, {"shares": 0.0, "market_value": 0.0, "cost_basis": 0.0, "cost_known": True,
                               "accounts": [], "as_of": as_of, "mark": mark,
                               "source": "lib.portfolio_positions (holdings_accounts store)"})
        o["shares"] += qty
        o["market_value"] += vp.get("market_value") or 0.0
        cb = vp.get("cost_basis")
        if cb is None and pp.per_share_cost(r) is not None:
            cb = pp.per_share_cost(r) * qty
        if cb is None:
            o["cost_known"] = False
        else:
            o["cost_basis"] += cb
        o["accounts"].append(r.get("account") or r.get("account_id"))
    for s, o in out.items():
        o["market_value"] = round(o["market_value"], 2)
        if o["cost_known"] and o["cost_basis"]:
            o["avg_cost"] = round(o["cost_basis"] / o["shares"], 4)
            o["unrealized_pl"] = round(o["market_value"] - o["cost_basis"], 2)
            o["unrealized_pl_pct"] = round(o["unrealized_pl"] / o["cost_basis"] * 100, 2)
        else:
            o["avg_cost"] = o["unrealized_pl"] = o["unrealized_pl_pct"] = None
        # weight = market value ÷ portfolio total value (portfolio_pct rows are inconsistent in scale)
        o["weight_pct"] = round(o["market_value"] / total_value * 100, 3) if total_value else None
    # ledger: last sell date only (recently sold) — see the module docstring for why realized is not derived here
    try:
        rows = db_query(
            """SELECT upper(symbol) AS s, max(trade_date) AS last_sell FROM trade_transactions
                WHERE upper(symbol) = ANY(%s) AND lower(action) LIKE 'sell%%' GROUP BY 1""", (syms,)) or []
    except Exception:
        rows = []
    for r in rows:
        o = out.setdefault(r["s"], {"shares": 0.0, "source": "trade_transactions"})
        ls = r.get("last_sell")
        o["last_sell_date"] = ls.isoformat() if hasattr(ls, "isoformat") else (str(ls)[:10] if ls else None)
    for o in out.values():
        o["realized_pl"] = None
        o["days_held"] = None
        o["pending"] = {"realized_pl": "positions_store realized_lots reader awaits operator phase-3 approval",
                        "days_held": "positions_store position_lots reader awaits operator phase-3 approval"}
    for o in out.values():
        o["owned"] = bool(o.get("shares"))
    _mark_sold_after_snapshot(db_query, doc, out, today=today)
    return out


SOLD_AFTER_SNAPSHOT_LOOKBACK_DAYS = 7


def _ts(v: Any):
    from datetime import datetime, timezone  # noqa: PLC0415
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, date):                # a bare date: midnight UTC (a conservative, early snapshot time)
        dt = datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    else:
        try:
            dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _mark_sold_after_snapshot(db_query, doc: dict[str, Any], out: dict[str, dict[str, Any]], *,
                              today: date | None = None) -> None:
    """NAVN (silo audit 2026-10-23): a broker sync that no-ops for an account leaves its holdings in the file, and every
    CIO held check reads them. For each owned symbol, a broker SELL fill newer than the snapshot of the accounts that
    hold it is an observed contradiction. It is MARKED (``sold_after_snapshot`` + both facts), never resolved here:
    ``owned`` stays what the holdings store says (§26.5, §0 rule 5).

    Snapshot time per account = ``account_summaries[acct].state_as_of`` (else the file's ``positions_built_at``). A
    TIMED snapshot marks any later sale. Most accounts stamp a DATE (midnight), which cannot order a same-day sale, so
    a date-only snapshot marks (a) a sale on a later calendar day than the snapshot, or (b) a same-day sale when the
    account has not synced since (snapshot date before today), the sales cover the listed shares, nothing was bought
    back, and the listed position was opened inside the lookback (the NAVN shape: bought 10-19, sold 10-22 15:59,
    sync no-op until 10-23 09:07). Known blind spot of (b): an older position topped up in the window and then cut by
    exactly the top-up reads as covered — the mark is a conflict SHOWN for review, never a resolution."""
    owned = sorted(s for s, o in out.items() if o.get("owned"))
    if not owned:
        return
    try:
        rows = db_query(
            """SELECT upper(symbol) AS s, lower(action) AS action, trade_time, trade_date, quantity
                 FROM trade_transactions
                WHERE upper(symbol) = ANY(%s) AND (lower(action) LIKE 'sell%%' OR lower(action) LIKE 'buy%%')
                  AND trade_date > current_date - %s ORDER BY trade_time""",
            (owned, SOLD_AFTER_SNAPSHOT_LOOKBACK_DAYS)) or []
    except Exception:
        return
    summaries = doc.get("account_summaries") or {}
    built = str(doc.get("positions_built_at") or "")
    fallback = _ts(built.replace(" ET", ""))
    if fallback is not None and built.endswith(" ET"):
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        fallback = fallback.replace(tzinfo=ZoneInfo("America/New_York"))
    fallback = fallback or _ts(doc.get("as_of"))
    for s in owned:
        o = out[s]
        snaps = [_ts((summaries.get(a) or {}).get("state_as_of")) for a in (o.get("accounts") or [])]
        snaps = [t for t in snaps if t is not None] or ([fallback] if fallback else [])
        if not snaps:
            continue
        snap = min(snaps)
        date_only = (snap.hour, snap.minute, snap.second, snap.microsecond) == (0, 0, 0, 0)
        fills = [(r, _ts(r.get("trade_time")) or _ts(r.get("trade_date"))) for r in rows if r.get("s") == s]
        sells = [(r, t) for r, t in fills if t is not None and t > snap and str(r.get("action")).startswith("sell")]
        if not sells:
            continue
        qty = sum(abs(_f(r.get("quantity")) or 0.0) for r, _ in sells)
        last = max(t for _, t in sells)
        rebought = any(t is not None and t > last and str(r.get("action")).startswith("buy") for r, t in fills)
        covers = bool(o.get("shares")) and qty >= float(o.get("shares") or 0) - 1e-9
        if date_only:
            later_day = last.date() > snap.date()
            bought_in_window = sum(abs(_f(r.get("quantity")) or 0.0) for r, t in fills
                                   if t is not None and str(r.get("action")).startswith("buy"))
            opened_in_window = bought_in_window >= float(o.get("shares") or 0) - 1e-9
            stale_same_day = (snap.date() < (today or date.today()) and covers and not rebought and opened_in_window)
            if not (later_day or stale_same_day):
                continue
        o["sold_after_snapshot"] = {
            "snapshot_as_of": snap.isoformat(), "snapshot_resolution": "date" if date_only else "time",
            "snapshot_source": "holdings_accounts state_as_of", "sell_fills": len(sells), "sell_quantity": qty,
            "last_sell_at": last.isoformat(), "rebought_after": rebought, "sell_source": "trade_transactions",
            "held_shares": o.get("shares"), "covers_position": covers,
        }
