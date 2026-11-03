"""Read confirmed exits from the live stores and feed them to the case builder (spec §3.1, §3.6).

Stop-out detection moves from ``risk_management.json`` status TRIGGERED to **broker-confirmed exits**. This reader uses
the stores the host already keeps, in this order:

1. ``trade_transactions`` — the imported broker fills (action SELL/STOP, symbol, account, price, quantity, trade_date).
2. ``stopped_out_watch`` — the engine's own stop-out rows, which carry ``realized_pnl`` and ``exit_price`` and are the
   only place a realized loss exists today.
3. ``stop_last_known`` — the stop level that fired, when the host did not place the stop (the 10-14 root cause).
4. ``positions_current`` — the residual share count that decides whether the symbol is still held.

Read-only. No order, no broker write, no JSON side-file. A missing store degrades to "unknown" and says so; it never
invents a fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from . import cases as rc
from .policy import Policy

EXIT_ACTIONS = ("SELL", "SOLD", "STOP", "STOPPED", "SELL_TO_CLOSE")


def _as_date(value: Any) -> date:
    """SQLite returns TEXT, Postgres returns date/datetime: one coercion, used everywhere."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass(frozen=True)
class ExitRead:
    fills: list[rc.ExitFill]
    residual_shares: Optional[float]
    pre_exit_weight_pct: Optional[float]
    source: str
    gaps: list[str]


def _query(conn: Any, sql: str, params: tuple = ()) -> tuple[list[tuple], Optional[str]]:
    """Run one read. Returns (rows, error). A missing table is a stated gap, never a silent empty result."""
    text = sql.replace("%s", "?") if "sqlite" in (type(conn).__module__ or "") else sql
    try:
        cur = conn.cursor()
        cur.execute(text, params)
        return list(cur.fetchall()), None
    except Exception as exc:  # noqa: BLE001 - reported as a gap by the caller
        return [], f"{type(exc).__name__}: {exc}"


def _rows(conn: Any, sql: str, params: tuple = ()) -> list[tuple]:
    return _query(conn, sql, params)[0]


def read_confirmed_exits(conn: Any, symbol: str, account: str, *, as_of: Optional[date] = None) -> ExitRead:
    """Collect the exits for one symbol × account, oldest first, with the residual that decides 'held'."""
    gaps: list[str] = []
    fills: list[rc.ExitFill] = []

    watch, watch_err = _query(conn, "SELECT stopped_out_at, exit_price, realized_pnl, stop_price, broker, symbol, account "
                        "FROM stopped_out_watch WHERE upper(symbol)=upper(%s) AND account=%s ORDER BY stopped_out_at",
                  (symbol, account))
    if watch_err:
        gaps.append(f"stopped_out_watch is unavailable ({watch_err})")
    for stopped_at, exit_price, realized, stop_price, broker, _, _ in watch:
        if exit_price in (None, "") or realized in (None, ""):
            gaps.append("a stopped_out_watch row has no exit price or realized P&L")
            continue
        closed_on = _as_date(stopped_at)
        fills.append(rc.ExitFill(symbol=symbol, account=account, exit_date=closed_on,
                                 shares=0.0, price=float(exit_price), realized_pnl=float(realized),
                                 stop_price=(float(stop_price) if stop_price not in (None, "") else None),
                                 broker=str(broker or ""), source="stopped_out_watch"))

    if fills:
        # Shares per exit come from the fills table when it agrees on the date; otherwise the case keeps 0 and the
        # residual rule falls back to the position row rather than inventing a size.
        tx = _rows(conn, "SELECT trade_date, quantity, price FROM trade_transactions "
                         "WHERE upper(symbol)=upper(%s) AND account=%s AND upper(action) IN "
                         "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') ORDER BY trade_date",
                   (symbol, account))
        by_day: dict[date, float] = {}
        for trade_date, quantity, _price in tx:
            day = _as_date(trade_date)
            by_day[day] = by_day.get(day, 0.0) + float(quantity or 0)
        if by_day:
            fills = [rc.ExitFill(**{**f.__dict__, "shares": by_day.get(f.exit_date, f.shares)}) for f in fills]
        else:
            gaps.append("no trade_transactions rows for these exits; share counts are unknown")
    else:
        tx = _rows(conn, "SELECT trade_date, action, quantity, price FROM trade_transactions "
                         "WHERE upper(symbol)=upper(%s) AND account=%s AND upper(action) IN "
                         "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') ORDER BY trade_date",
                   (symbol, account))
        for trade_date, _action, quantity, price in tx:
            day = _as_date(trade_date)
            fills.append(rc.ExitFill(symbol=symbol, account=account, exit_date=day, shares=float(quantity or 0),
                                     price=float(price or 0), realized_pnl=0.0, source="trade_transactions"))
        if tx:
            gaps.append("exits came from trade_transactions only: realized P&L is unknown until stopped_out_watch "
                        "has the row")

    if fills and all(f.stop_price is None for f in fills):
        stops = _rows(conn, "SELECT stop_price, captured_at FROM stop_last_known "
                            "WHERE upper(symbol)=upper(%s) AND account=%s ORDER BY captured_at DESC LIMIT 1",
                      (symbol, account))
        if stops:
            level = stops[0][0]
            fills = [rc.ExitFill(**{**f.__dict__, "stop_price": float(level)}) for f in fills]
        else:
            gaps.append("no stop level known for these exits (the host may not have placed the stop)")

    residual_rows, residual_err = _query(
        conn, "SELECT qty FROM positions_current WHERE upper(symbol)=upper(%s) AND account_key=%s",
        (symbol, account))
    if residual_err:
        # The false-zero class: an unreadable store is "unknown", never "no shares left".
        gaps.append(f"positions_current is unreadable ({residual_err}); the residual is unknown")
        residual: Optional[float] = None
    else:
        residual = sum(float(qty or 0) for (qty,) in residual_rows)

    return ExitRead(fills=fills, residual_shares=residual, pre_exit_weight_pct=None,
                    source="broker-fills", gaps=gaps)


def consume_symbol(store: rc.CaseStore, conn: Any, symbol: str, account: str, *,
                   today: Optional[date] = None, now: Optional[datetime] = None) -> Optional[rc.RecoveryCase]:
    """Read one symbol × account and open/refresh its case. Returns None when there is no confirmed exit."""
    read = read_confirmed_exits(conn, symbol, account)
    if not read.fills:
        return None
    return rc.consume_fills(store, read.fills, residual_shares=read.residual_shares,
                            pre_exit_weight_pct=read.pre_exit_weight_pct, today=today, now=now)


def symbols_with_confirmed_exits(conn: Any, *, since: Optional[date] = None) -> list[tuple[str, str]]:
    """The work list: symbol × account pairs that have at least one confirmed exit."""
    rows = _rows(conn, "SELECT DISTINCT symbol, account FROM stopped_out_watch "
                       "WHERE stopped_out_at IS NOT NULL AND is_active IS NOT FALSE ORDER BY symbol, account")
    seen = {(str(s).upper(), str(a)) for s, a in rows if s and a}
    tx = _rows(conn, "SELECT DISTINCT symbol, account FROM trade_transactions "
                     "WHERE upper(action) IN ('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') "
                     "ORDER BY symbol, account")
    seen |= {(str(s).upper(), str(a)) for s, a in tx if s and a}
    return sorted(seen)


def run(store: rc.CaseStore, conn: Any, *, today: Optional[date] = None,
        now: Optional[datetime] = None) -> dict[str, Any]:
    """One consumer pass over every symbol × account with a confirmed exit. Idempotent."""
    moments = {
        "today": today or (now or datetime.now(timezone.utc)).date(),
        "now": now or datetime.now(timezone.utc),
    }
    opened, refreshed, gaps = [], [], []
    for symbol, account in symbols_with_confirmed_exits(conn):
        before = None
        read = read_confirmed_exits(conn, symbol, account)
        gaps.extend(f"{symbol}/{account}: {gap}" for gap in read.gaps)
        if not read.fills:
            continue
        case = rc.consume_fills(store, read.fills, residual_shares=read.residual_shares,
                                pre_exit_weight_pct=read.pre_exit_weight_pct, **moments)
        before = store.get(case.case_key)
        (refreshed if before and before.opened_at != case.opened_at else opened).append(case.case_key)
    return {"opened": opened, "refreshed": refreshed, "gaps": gaps,
            "cases": [c.to_dict() for c in store.list()]}
