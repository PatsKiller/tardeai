"""Read confirmed exits from the live stores and feed them to the case builder (spec §3.1, §3.6).

Stop-out detection moves from ``risk_management.json`` status TRIGGERED to **broker-confirmed exits**. This reader uses
the stores the host already keeps, in this order:

1. ``stopped_out_watch`` — the engine's own stop-out rows: the exit price, the realized P&L and the stop level.
2. ``trade_transactions`` — the imported broker fills: the share count per exit.
3. ``stop_last_known`` — the stop level that fired, when the host did not place the stop (the 10-14 root cause).
4. ``positions_current`` — the residual share count (approved reader batch 5).
5. ``positions_sync_runs`` — the heartbeat, which dates the positions store. It is not gated, and it is how the
   residual's own clock is known without reading a column outside the approved ``qty`` scope.

Read-only. No order, no broker write, no JSON side-file. Every failure is a stated gap: a missing store, a damaged row
and a delayed fill all say so, and none of them becomes a zero (cx-openai-2 F4/F9/F10/F11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from . import cases as rc
from .policy import _finite

def _as_date(value: Any) -> date:
    """SQLite returns TEXT, Postgres returns date/datetime: one coercion, used everywhere. Garbage raises."""
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
    residual_as_of: Optional[str] = None


def _query(conn: Any, sql: str, params: tuple = ()) -> tuple[list[tuple], Optional[str]]:
    """Run one read. Returns (rows, error). A missing table is a stated gap, never a silent empty result."""
    text = sql.replace("%s", "?") if "sqlite" in (type(conn).__module__ or "") else sql
    try:
        cur = conn.cursor()
        cur.execute(text, params)
        return list(cur.fetchall()), None
    except Exception as exc:  # noqa: BLE001 - reported as a gap by the caller
        return [], f"{type(exc).__name__}: {exc}"


# Literal statements only (ruff S608): every variant a caller can choose is written out in full here, so no SQL text
# is ever assembled from a runtime variable.
_WATCH_SQL = ("SELECT stopped_out_at, exit_price, realized_pnl, stop_price, broker FROM stopped_out_watch "
              "WHERE upper(symbol)=upper(%s) AND account=%s ORDER BY stopped_out_at")
_WATCH_SQL_ASOF = ("SELECT stopped_out_at, exit_price, realized_pnl, stop_price, broker FROM stopped_out_watch "
                   "WHERE upper(symbol)=upper(%s) AND account=%s AND stopped_out_at < %s ORDER BY stopped_out_at")
_TX_SQL = ("SELECT trade_date, quantity FROM trade_transactions "
           "WHERE upper(symbol)=upper(%s) AND account=%s AND upper(action) IN "
           "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') ORDER BY trade_date DESC")
_TX_SQL_ASOF = ("SELECT trade_date, quantity FROM trade_transactions "
                "WHERE upper(symbol)=upper(%s) AND account=%s AND upper(action) IN "
                "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') AND trade_date < %s ORDER BY trade_date DESC")


def read_confirmed_exits(conn: Any, symbol: str, account: str, *, as_of: Optional[date] = None) -> ExitRead:
    """Collect the exits for one symbol × account, oldest first, with the residual that decides 'held'.

    ``as_of`` is honoured: a caller replaying to a past date does not see a later exit (cx-openai-2 F11).
    """
    gaps: list[str] = []
    fills: list[rc.ExitFill] = []

    if as_of is None:
        watch_sql, watch_params = _WATCH_SQL, (symbol, account)
    else:
        # Inclusive of the as_of day: an exit dated as_of belongs to that replay.
        watch_sql = _WATCH_SQL_ASOF
        watch_params = (symbol, account, (as_of + timedelta(days=1)).isoformat())
    watch, watch_err = _query(conn, watch_sql, watch_params)
    if watch_err:
        gaps.append(f"stopped_out_watch is unavailable ({watch_err})")
    for stopped_at, exit_price, realized, stop_price, broker in watch:
        try:
            closed_on = _as_date(stopped_at)
            price = _finite(exit_price)
            if price is None:
                raise ValueError("no exit price")
            stop = _finite(stop_price)
        except (TypeError, ValueError) as exc:
            # One damaged row is excluded and reported; it never aborts the symbol and never becomes a zero fill.
            gaps.append(f"a stopped_out_watch row for {symbol}/{account} is unreadable ({exc}); it is excluded")
            continue
        pnl = _finite(realized)
        if pnl is None:
            gaps.append(f"the {closed_on} stopped_out_watch row carries no usable realized P&L; "
                        "that exit's loss is unknown")
        fills.append(rc.ExitFill(symbol=symbol, account=account, exit_date=closed_on,
                                 shares=None, price=price, realized_pnl=pnl, stop_price=stop,
                                 broker=str(broker or ""), source="stopped_out_watch"))

    if as_of is None:
        tx_sql, tx_params = _TX_SQL, (symbol, account)
    else:
        tx_sql, tx_params = _TX_SQL_ASOF, (symbol, account, (as_of + timedelta(days=1)).isoformat())
    tx, tx_err = _query(conn, tx_sql, tx_params)
    if tx_err:
        gaps.append(f"trade_transactions is unavailable ({tx_err}); share counts are unknown")
    tx_by_day: dict[date, list[float]] = {}
    for trade_date, quantity in tx:
        try:
            day = _as_date(trade_date)
        except (TypeError, ValueError) as exc:
            gaps.append(f"a trade_transactions row for {symbol}/{account} has an unreadable date ({exc}); "
                        "it is excluded")
            continue
        qty = _finite(quantity)
        if qty is None:
            gaps.append(f"a {day} trade_transactions row for {symbol}/{account} has no usable quantity; "
                        "it is excluded")
            continue
        tx_by_day.setdefault(day, []).append(qty)

    if fills:
        # One watch exit on a day can be attributed that day's whole fill total. Two exits on the same day cannot be
        # told apart from a day-level aggregate, so those share counts stay unknown instead of being double-counted
        # (cx-openai-2 F4: two watch rows on one day both received the entire day's 12,000 shares).
        per_day: dict[date, int] = {}
        for fill in fills:
            per_day[fill.exit_date] = per_day.get(fill.exit_date, 0) + 1
        attributed: list[rc.ExitFill] = []
        for fill in fills:
            quantities = tx_by_day.get(fill.exit_date) or []
            if not quantities:
                gaps.append(f"no trade_transactions row for the {fill.exit_date} exit; its share count is unknown")
                attributed.append(fill)
            elif per_day[fill.exit_date] > 1:
                gaps.append(f"{per_day[fill.exit_date]} exits share {fill.exit_date}; per-exit share counts cannot be "
                            "attributed from a day-level total")
                attributed.append(fill)
            else:
                attributed.append(rc.ExitFill(**{**fill.__dict__, "shares": round(sum(quantities), 6)}))
        fills = attributed
        if tx_by_day:
            latest_tx = max(tx_by_day)
            last_exit = max(f.exit_date for f in fills)
            if latest_tx > last_exit:
                # A fill dated after the last stop-out row: the exit list is behind the ledger, so the cluster may be
                # incomplete. Say so rather than pretending the newer fill does not exist (cx-openai-2 F4, delayed fill).
                gaps.append(f"trade_transactions has a {latest_tx} exit with no stopped_out_watch row; "
                            "this cluster may be incomplete")
    elif tx_by_day:
        # Confirmed sells exist but no stopped_out_watch row carries their exit price. A case cannot be built from a
        # sale without a price — and a placeholder 0.0 would make the R1 reclaim threshold zero, i.e. "recovering"
        # always. Report the dates and build nothing for them.
        gaps.append(f"trade_transactions has confirmed exits on {', '.join(str(d) for d in sorted(tx_by_day))} but "
                    "stopped_out_watch has no exit price for them; no case is opened from a sale without a price")

    if fills and all(f.stop_price is None for f in fills):
        stops = _query(conn, "SELECT stop_price, captured_at FROM stop_last_known "
                             "WHERE upper(symbol)=upper(%s) AND account=%s ORDER BY captured_at DESC LIMIT 1",
                       (symbol, account))[0]
        if stops:
            level = _finite(stops[0][0])
            if level is not None:
                fills = [rc.ExitFill(**{**f.__dict__, "stop_price": level}) for f in fills]
            else:
                gaps.append("the last known stop level is not a usable number")
        else:
            gaps.append("no stop level known for these exits (the host may not have placed the stop)")

    residual_rows, residual_err = _query(
        conn, "SELECT qty FROM positions_current WHERE upper(symbol)=upper(%s) AND account_key=%s",
        (symbol, account))
    residual: Optional[float] = None
    if residual_err:
        # The false-zero class: an unreadable store is "unknown", never "no shares left".
        gaps.append(f"positions_current is unreadable ({residual_err}); the residual is unknown")
    else:
        quantities = [_finite(qty) for (qty,) in residual_rows]
        if any(q is None for q in quantities):
            gaps.append("a positions_current row has no usable quantity; the residual is unknown")
        else:
            residual = sum(quantities)

    # The residual must be dated by the store that produced it. positions_current.as_of is outside the approved reader
    # scope (batch 5 reads qty only), so the promotion clock comes from positions_sync_runs, which is the heartbeat and
    # is not gated. Without it, a snapshot older than the exit could pass as today's residual (cx-openai-2 F11).
    residual_as_of: Optional[str] = None
    clock_rows, clock_err = _query(
        conn, "SELECT MAX(finished_at) FROM positions_sync_runs WHERE promoted IS TRUE AND status='complete'")
    if clock_err:
        gaps.append(f"the positions store clock is unavailable ({clock_err}); the residual's age is unknown")
    elif clock_rows and clock_rows[0][0] not in (None, ""):
        residual_as_of = str(clock_rows[0][0])[:10]

    return ExitRead(fills=fills, residual_shares=residual, pre_exit_weight_pct=None,
                    source="broker-fills", gaps=gaps, residual_as_of=residual_as_of)


def consume_symbol(store: rc.CaseStore, conn: Any, symbol: str, account: str, *,
                   today: Optional[date] = None, now: Optional[datetime] = None,
                   as_of: Optional[date] = None) -> Optional[rc.RecoveryCase]:
    """Read one symbol × account and open/refresh its case. Returns None when there is no confirmed exit."""
    read = read_confirmed_exits(conn, symbol, account, as_of=as_of)
    if not read.fills:
        return None
    return rc.consume_fills(store, read.fills, residual_shares=read.residual_shares,
                            pre_exit_weight_pct=read.pre_exit_weight_pct, today=today, now=now,
                            residual_as_of=read.residual_as_of, gaps=read.gaps)


_SYMBOLS_WATCH_SQL = ("SELECT DISTINCT symbol, account FROM stopped_out_watch "
                      "WHERE stopped_out_at IS NOT NULL AND is_active IS NOT FALSE")
_SYMBOLS_WATCH_SQL_SINCE = ("SELECT DISTINCT symbol, account FROM stopped_out_watch "
                            "WHERE stopped_out_at IS NOT NULL AND is_active IS NOT FALSE AND stopped_out_at >= %s")
_SYMBOLS_TX_SQL = ("SELECT DISTINCT symbol, account FROM trade_transactions WHERE upper(action) IN "
                   "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE')")
_SYMBOLS_TX_SQL_SINCE = ("SELECT DISTINCT symbol, account FROM trade_transactions WHERE upper(action) IN "
                         "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') AND trade_date >= %s")


def symbols_with_confirmed_exits(conn: Any, *, since: Optional[date] = None) -> tuple[list[tuple[str, str]], list[str]]:
    """The work list — and the failures that would otherwise look like an empty one.

    A failed enumeration used to return no pairs and no error, so the pass reported "nothing to do" while every
    possible case was being dropped (cx-openai-2 F9). ``since`` is now honoured.
    """
    gaps: list[str] = []
    if since is None:
        rows, watch_err = _query(conn, _SYMBOLS_WATCH_SQL)
        tx, tx_err = _query(conn, _SYMBOLS_TX_SQL)
    else:
        rows, watch_err = _query(conn, _SYMBOLS_WATCH_SQL_SINCE, (since.isoformat(),))
        tx, tx_err = _query(conn, _SYMBOLS_TX_SQL_SINCE, (since.isoformat(),))
    if watch_err:
        gaps.append(f"stopped_out_watch is unavailable ({watch_err}); the work list is incomplete")
    seen = {(str(s).upper(), str(a)) for s, a in rows if s and a}
    if tx_err:
        gaps.append(f"trade_transactions is unavailable ({tx_err}); the work list is incomplete")
    seen |= {(str(s).upper(), str(a)) for s, a in tx if s and a}
    return sorted(seen), gaps


def run(store: rc.CaseStore, conn: Any, *, today: Optional[date] = None,
        now: Optional[datetime] = None, as_of: Optional[date] = None) -> dict[str, Any]:
    """One consumer pass over every symbol × account with a confirmed exit. Idempotent.

    A pass reports ``complete: false`` whenever any source failed or any single case could not be built; one damaged
    case never prevents the others, and a partial pass never reports itself as a clean one (cx-openai-2 F9/F10).
    """
    moments = {
        "today": today or (now or datetime.now(timezone.utc)).date(),
        "now": now or datetime.now(timezone.utc),
    }
    pairs, gaps = symbols_with_confirmed_exits(conn)
    opened, refreshed, failed = [], [], []
    for symbol, account in pairs:
        try:
            read = read_confirmed_exits(conn, symbol, account, as_of=as_of)
            gaps.extend(f"{symbol}/{account}: {gap}" for gap in read.gaps)
            if not read.fills:
                continue
            ordered = sorted(read.fills, key=lambda f: f.exit_date)
            key = rc.case_key(symbol, account,
                              f"{ordered[0].exit_date.isoformat()}..{ordered[-1].exit_date.isoformat()}")
            existed = store.get(key) is not None
            case = rc.consume_fills(store, read.fills, residual_shares=read.residual_shares,
                                    pre_exit_weight_pct=read.pre_exit_weight_pct,
                                    residual_as_of=read.residual_as_of, gaps=read.gaps, **moments)
            (refreshed if existed else opened).append(case.case_key)
        except Exception as exc:  # noqa: BLE001 - one case's failure is isolated and reported, never hidden
            failed.append(f"{symbol}/{account}: {type(exc).__name__}: {exc}")
            gaps.append(f"{symbol}/{account}: the case could not be built ({type(exc).__name__}: {exc})")
    return {"opened": opened, "refreshed": refreshed, "failed": failed, "gaps": gaps,
            "complete": not failed and not any("unavailable" in g for g in gaps),
            "cases": [c.to_dict() for c in store.list()]}
