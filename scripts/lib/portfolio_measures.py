"""PortfolioMeasures@v1 — the four portfolio measures, computed once where the document is written.

LQ-20261113-3124R. On 2026-11-13 the same book published two different figures under the name "today": the
header's stored-row "1D" and the Portfolio page's re-marked sum, the second being the first plus a whole
**valuation correction** (the broker mark -> live mark re-mark). A reader could not tell a price move from an
account's change in value from a feed correction. The read-only bridge that assigned every dollar is
FINDING-3124R-recon in persistent-state; its production values are deliberately not repeated in this public
repository.

The operator's ruling (2026-11-13 23:10 ET) fixes the accounting semantics:

* **Broker-reported account values and broker evidence are the anchor.** Finviz marks are published ONLY as a
  separate, timestamped estimate next to the anchor. The broker->Finviz adjustment is never added to "today's
  profit".
* **ONE shared calculation feeds both screens** (header and Portfolio): identical account scope, session and
  valuation cutoff.
* **Four distinct measures**, each with its own label, source timestamps and drill-down:

  1. ``account_value`` — "Account value": the positions store's broker marks (cash included). The Finviz
     mark value travels beside it with its timestamp and delta; that delta is a valuation difference, not P&L.
  2. ``price_move_estimate`` — "Estimated price movement of current holdings": Σ over open positions of
     (current broker value - the position's prior-close baseline). The baseline is, per row, the broker's own
     ``prior_close`` (reference close), else the last observed book value before today, else the broker's
     ``broker_day_pl`` when it is not contradicted by its own check. The Finviz-mark estimate is a separate
     field of the same block, timestamped, never summed into the anchor.
  3. ``account_value_change_1d`` — "Account value change since prior close": ending equity - starting equity,
     both on the broker basis, with the internal trade effect (gross proceeds against the prior close of
     what was sold) and the fees paid as their own negative line named in the drill-down. Internal transfers
     cancel in the consolidated total. UNKNOWN unless a prior-close book (cash included) is supplied.
  4. ``verified_daily_pnl`` — "Verified daily P&L" = ending equity - starting equity - net external
     contributions, on matched equity snapshots. It stays UNKNOWN until a stored, signed reconciliation
     exists; this module never computes a number under that label on its own.

"GET never computes": this module is pure and is called by the document's WRITER (the repricer path) which
stores the result under ``holdings.json["measures"]``. The API read path only reads that block. An unknown
measure publishes ``value: None`` with a reason; it never becomes a confident zero (``unknown beats wrong``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

CONTRACT_VERSION = "PortfolioMeasures@v1"
ET = ZoneInfo("America/New_York")

BASIS_STORE = "broker_positions_store"
BASIS_FINVIZ = "finviz_mark_estimate"

LABEL_ACCOUNT_VALUE = "Account value"
LABEL_PRICE_MOVE = "Estimated price movement of current holdings"
LABEL_ACCOUNT_VALUE_CHANGE = "Account value change since prior close"
LABEL_VERIFIED_PNL = "Verified daily P&L"
LABEL_FINVIZ_ESTIMATE = "Finviz mark estimate"

MEASURE_ACCOUNT_VALUE = "account_value"
MEASURE_PRICE_MOVE = "price_move_estimate"
MEASURE_ACCOUNT_VALUE_CHANGE = "account_value_change_1d"
MEASURE_VERIFIED_PNL = "verified_daily_pnl"

PRICE_MOVE_DEFINITION = (
    "Sum over open non-cash positions of (current broker value - that position's prior-close baseline). "
    "The baseline is the broker's own prior_close where the row declares one, else the last observed book "
    "value before today, else the broker's day P&L when its own check does not contradict it. Positions sold "
    "today, cash movements, fees and external deposits/withdrawals are excluded."
)
ACCOUNT_VALUE_CHANGE_DEFINITION = (
    "Ending equity - starting equity on the broker basis, both including cash. It includes realized amounts "
    "from positions sold today, the fees they paid as a separate negative line, any income and any external "
    "flow; internal transfers cancel in the consolidated total. It is the account's change in value, not the "
    "open positions' price move."
)
VERIFIED_PNL_DEFINITION = (
    "Ending equity - starting equity - net external contributions, on matched equity snapshots. Internal "
    "transfers cancel in the consolidated total. A number under this label requires a stored, signed, "
    "per-account reconciliation; the code never computes one from a single observation."
)
VERIFIED_PNL_GAP = (
    "No stored verified reconciliation exists. The candidate (account value change since prior close) is shown "
    "beside the known components, but the verified label stays UNKNOWN: the starting equity must be a matched "
    "observation at the prior close, income and external flows must be sourced, and the reconciliation must be "
    "signed per account. GET never computes a verified figure."
)
FINVIZ_NEVER_ADDED = (
    "A broker->Finviz mark difference is a valuation difference between two feeds, not a move and not P&L. "
    "It is published beside the anchor with its timestamp and never added to any 'today' measure."
)

RECONCILIATION_VERSION = "PortfolioReconciliation@v1"
RECON_TOLERANCE_USD = 0.02
RECON_POLICY = (
    "Signed per account: ending equity - starting equity against the sum of its named components. A residual "
    "is REPORTED, never allocated to a component and never averaged away; a component that is not observed is "
    "null with its reason, not zero. Internal transfers move value between accounts and cancel in the "
    "consolidated total; only the external part of a transfer changes the account's value economically."
)
RECON_STATUSES = ("RECONCILED", "UNEXPLAINED", "PARTIAL", "UNKNOWN")


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _expense(fees: float) -> float:
    """A cost enters the bridge negative; a day with no fee is ``0.0``, never the ``-0.0`` a naive negate makes."""
    value = round(-fees, 2)
    return 0.0 if value == 0 else value


def _cash(row: Mapping[str, Any]) -> bool:
    from .portfolio_positions import is_cash

    return bool(is_cash(row))


def _et_today(now: datetime | None) -> str:
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(ET).date().isoformat()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    return text or None


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    account = row.get("account_key") or row.get("account_id") or row.get("account") or ""
    return str(account), str(row.get("symbol") or "").upper()


def row_store_value(row: Mapping[str, Any]) -> float | None:
    """The row's dollars on the store's own basis (``broker_market_value``; cash by ``broker_shares``).

    A cash row whose broker fields are absent still carries its balance in ``market_value``; cash has no
    quote, so that is a store figure and not a live re-mark. Without this, one cash row with a null
    ``broker_market_value`` made the whole store total UNKNOWN.
    """
    from .portfolio_value_basis import row_store_value as _store_value

    value = _store_value(row)
    if value is None and _cash(row):
        balance = _number(row.get("market_value"))
        if balance is not None:
            return round(balance, 2)
    return value


def row_finviz_value(row: Mapping[str, Any]) -> float | None:
    """The row's dollars at its Finviz mark, for the separate estimate (never the anchor)."""
    if _cash(row):
        return row_store_value(row)
    shares = _number(row.get("broker_shares") if row.get("broker_shares") is not None else row.get("shares"))
    mark = _number(row.get("canonical_mark")
                   if row.get("canonical_mark") is not None
                   else (row.get("current_price") if row.get("current_price") is not None else row.get("price")))
    if shares is not None and shares > 0 and mark is not None and mark > 0:
        return round(shares * mark, 2)
    return None


def _row_prior_value(row: Mapping[str, Any], prior_rows: Mapping[tuple[str, str], float] | None,
                     prior_source: str | None) -> tuple[float | None, str | None]:
    """One open row's prior-close baseline and the evidence it came from."""
    shares = _number(row.get("broker_shares") if row.get("broker_shares") is not None else row.get("shares"))
    close = _number(row.get("prior_close"))
    if shares is not None and shares > 0 and close is not None and close > 0:
        return round(shares * close, 2), "broker_prior_close"
    observed = (prior_rows or {}).get(_key(row))
    if observed is not None:
        return round(observed, 2), prior_source or "prior_snapshot"
    broker = _number(row.get("broker_day_pl"))
    check = row.get("day_change_broker_check")
    contradicted = isinstance(check, Mapping) and check.get("ok") is False
    value = row_store_value(row)
    if broker is not None and value is not None and not contradicted:
        return round(value - broker, 2), "broker_day_pl"
    return None, None


def _purchase_keys(trades: Iterable[Mapping[str, Any]] | None) -> set[tuple[str, str]]:
    """The ``(account, symbol)`` keys that a **purchase** created inside the interval.

    The prior book is symbol-blind for transfers (``_transfers_block`` carries from/to/amount/type/date, no
    symbol), so "this account holds a symbol the book never held here" alone cannot say whether the position
    was bought or moved in. The day's trades can, for the account they name: a ``BUY`` for that key is a
    purchase, and its start contributes 0.00 (the cash left the account; base was exact on that case -- review
    cc-deepseek-8 2026-11-14 §4, start 15,200.00 / change -5,200.00 where the truth is -200.00).

    Only an exact key match counts, and only ``BUY``. The symbol fallback ``_trades_effect`` uses for a
    label mismatch is deliberately *not* reused: with one SELL of a symbol elsewhere today it would label a
    moved position a purchase and zero the transfer this ticket fixes. An acquisition the ledger calls
    something else (``REINVEST SHARES``, ``JOURNALED SHARES``, ``SECURITY TRANSFER``) therefore keeps the
    estimated basis -- the pre-fix behaviour, disclosed, never silently zeroed.
    """
    bought: set[tuple[str, str]] = set()
    for trade in trades or []:
        if not isinstance(trade, Mapping):
            continue
        if str(trade.get("action") or "").strip().upper() != "BUY":
            continue
        bought.add((str(trade.get("account") or ""), str(trade.get("symbol") or "").upper()))
    return bought


def _row_start_value(row: Mapping[str, Any], prior_rows: Mapping[tuple[str, str], float] | None,
                     prior_source: str | None,
                     book_accounts: set[str],
                     prior_shares: Mapping[tuple[str, str], float] | None = None,
                     bought_today: set[tuple[str, str]] | None = None) -> tuple[float | None, str | None]:
    """The value a still-held row contributes to the prior-close **start** of the change.

    The start is the position **as it stood at the prior close**, not today's position re-marked: the prior
    book's own share count times the row's prior close (lead ruling 06:29Z, option (a); review cc-deepseek-8
    2026-11-14 §5). ``_row_prior_value`` prefers post-trade ``broker_shares x prior_close``, which drops the sold
    shares' prior value on a trim and credits shares an add never held. So when the prior book was read:

    * a keyed row with a prior share count contributes ``prior_shares x prior_close`` -- the same basis measure 2
      uses, so the drill can still close on a day without a share change;
    * with no share count recorded, the book's own value stands (never a re-mark of today's count);
    * a row whose account the book covers but whose symbol it does not was bought inside the interval and
      contributes 0: the purchase moved cash into the position, it did not create value;
    * an account the book does not cover at all (e.g. a renamed account key) falls through to the estimated
      basis, because absence there says nothing about the position.

    "Bought" is decided from the day's trades where they can decide it (``_purchase_keys``): a ``BUY`` for
    this exact key contributes 0.00 even when the symbol is held in another account, because adding to a name
    you already hold elsewhere is an ordinary purchase, not a transfer. Without that trade row the row keeps
    the estimated basis -- a transfer, or a purchase whose ledger label does not match the book key.
    """
    key = _key(row)
    if prior_rows is not None:
        shares = (prior_shares or {}).get(key)
        close = _number(row.get("prior_close"))
        if shares is not None and close is not None and close > 0:
            return round(shares * close, 2), "prior_shares_x_prior_close"
        observed = prior_rows.get(key)
        if observed is not None:
            return round(observed, 2), prior_source or "prior_snapshot"
        if key in (bought_today or set()):
            return 0.0, "bought_today"
        # "Bought inside the interval" needs the symbol to be absent from the book *everywhere*: an internal
        # transfer moves a position to an account the book covers but whose key the book never held, and that
        # position's prior value must not be read as zero (review cc-deepseek-8 rev-8 note 2).
        if key[0] in book_accounts and key[1] not in {k[1] for k in prior_rows}:
            return 0.0, "not_held_at_prior_close"
    return _row_prior_value(row, prior_rows, prior_source)


def _price_move_block(rows: list[Mapping[str, Any]], prior_rows: Mapping[tuple[str, str], float] | None,
                      prior_source: str | None) -> dict[str, Any]:
    total = 0.0
    measured = 0
    unknown: list[dict[str, Any]] = []
    census: dict[str, int] = {}
    per_row: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("is_loan"):
            continue
        if _cash(row):
            census["cash"] = census.get("cash", 0) + 1  # nosemgrep: tq-py-missing-as-zero -- census counter, not a value
            continue
        shares = _number(row.get("broker_shares") if row.get("broker_shares") is not None else row.get("shares"))
        if shares is not None and shares <= 0:
            census["not_held"] = census.get("not_held", 0) + 1  # nosemgrep: tq-py-missing-as-zero -- census counter, not a value
            continue
        current = row_store_value(row)
        prior, source = _row_prior_value(row, prior_rows, prior_source)
        if current is None or prior is None:
            unknown.append({"account": row.get("account_key") or row.get("account"),
                            "symbol": str(row.get("symbol") or "").upper(),
                            "value_usd": current, "reason": source or "no prior-close baseline"})
            census["unmeasured"] = census.get("unmeasured", 0) + 1  # nosemgrep: tq-py-missing-as-zero -- census counter
            continue
        move = round(current - prior, 2)
        measured += 1
        total += move
        # nosemgrep: tq-py-missing-as-zero -- census counter, not a value
        census[source or "unmeasured"] = census.get(source or "unmeasured", 0) + 1
        per_row.append({"account": row.get("account_key") or row.get("account"),
                        "symbol": str(row.get("symbol") or "").upper(),
                        "current_usd": current, "prior_usd": prior, "move_usd": move,
                        "baseline_source": source, "prior_close": _number(row.get("prior_close"))})
    status = "UNKNOWN" if not measured else ("PARTIAL" if unknown else "MEASURED")
    return {"value": round(total, 2) if measured else None, "status": status, "measured_rows": measured,
            "unknown_rows": len(unknown), "unknown": unknown[:20], "row_basis_census": census,
            "rows": per_row[:60], "gap": (None if not unknown else
                                          {"reason": "some open rows have no prior-close baseline",
                                           "unknown": unknown[:20]})}


def _finviz_estimate(rows: list[Mapping[str, Any]], doc: Mapping[str, Any],
                     prior_rows: Mapping[tuple[str, str], float] | None = None,
                     prior_source: str | None = None) -> dict[str, Any]:
    """The Finviz-mark estimate of the open rows' move, separate from the anchor and timestamped."""
    from .holding_day_change import resolve_holding_day_change

    total = 0.0
    measured = 0
    broker_nav: list[dict[str, Any]] = []
    broker_not_added: list[dict[str, Any]] = []
    unmeasured: list[dict[str, Any]] = []
    marks_at: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("is_loan") or _cash(row):
            continue
        shares = _number(row.get("shares", row.get("quantity")))
        if shares is not None and shares <= 0:
            continue
        for stamp in (row.get("canonical_mark_ingested_at"), row.get("quote_inserted_at")):
            if stamp:
                marks_at.append(str(stamp))
        raw_value = _number(row.get("market_value"))
        raw_price = _number(row.get("current_price") if row.get("current_price") is not None else row.get("price"))
        if raw_value is None and raw_price is None:
            # No mark at all: the row cannot contribute to the estimate, and it is counted as unmeasured
            # rather than passed through as a confident zero.
            unmeasured.append({"account": row.get("account_key") or row.get("account"),
                               "symbol": str(row.get("symbol") or "").upper(),
                               "reason": "no market value and no price on the row"})
            continue
        value = raw_value if raw_value is not None else 0.0
        price = raw_price if raw_price is not None else 0.0
        day, _pct = resolve_holding_day_change(dict(row), market_value=value, price=price,
                                               stale_price=price, finviz_day_pct=None)
        day = _number(day)
        broker = _number(row.get("broker_day_pl"))
        stamp = row.get("broker_day_pl_at")
        if day is not None and abs(day) >= 0.005:
            total += day
            measured += 1
            if broker is not None and abs(broker) >= 0.005:
                # Disclosed, never added: the row already carries a Finviz-mark day change, so its broker NAV
                # term is a second opinion on the same session, not a component to sum.
                broker_not_added.append({"symbol": str(row.get("symbol") or "").upper(),
                                         "value_usd": round(broker, 2), "reported_at": stamp,
                                         "why": "row already carries a Finviz-mark day change"})
            continue
        if broker is not None and abs(broker) >= 0.005 and stamp:
            # A NAV-based fund has no Finviz day change; its broker-reported daily change is disclosed here
            # as a broker NAV term, not silently folded into the Finviz estimate. The broker's ``at`` stamp is
            # a response time, not the NAV time: the day the step belongs to is dated by the observation pair
            # (the prior-close book value -> the current value), which is what ``prior_observed_usd`` shows.
            prior_observed = (prior_rows or {}).get(_key(row))
            broker_nav.append({"symbol": str(row.get("symbol") or "").upper(), "value_usd": round(broker, 2),
                               "reported_at": stamp, "prior_observed_usd": prior_observed,
                               "prior_observed_source": prior_source if prior_observed is not None else None,
                               "current_usd": row_store_value(row),
                               "reported_at_is": "broker response time, not the NAV publication time"})
    broker_nav_total = round(sum(r["value_usd"] for r in broker_nav), 2)
    marks_at.sort()
    out = {"label": LABEL_FINVIZ_ESTIMATE, "basis": BASIS_FINVIZ,
           "value": round(total, 2) if measured else None,
           "measured_rows": measured, "marks_at": marks_at[-1] if marks_at else None,
           "unmeasured_rows": len(unmeasured), "unmeasured": unmeasured[:20],
           "broker_nav_rows": broker_nav, "broker_nav_total": broker_nav_total if broker_nav else None,
           "broker_day_pl_not_added": broker_not_added,
           "total_with_broker_nav": (round(total + broker_nav_total, 2) if measured else None),
           "note": FINVIZ_NEVER_ADDED}
    stored = _number((doc.get("portfolio_totals") or {}).get("day_change"))
    out["stored_aggregate_day_change"] = stored
    return out


def _trades_effect(closed: Mapping[str, Any], trades: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """The realized trade effect of positions closed today: gross proceeds - prior-close value, plus fees.

    The fee is NOT netted into the effect and NOT given a sign that makes the account close. It is reported
    separately (``fees``, positive) and published as its own negative component, so a day whose store has not
    booked the commission yet shows a 0.47 residual instead of a component bent to absorb it.
    """
    by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for trade in trades or []:
        if not isinstance(trade, Mapping):
            continue
        symbol = str(trade.get("symbol") or "").upper()
        by_key[(str(trade.get("account") or ""), symbol)] = trade
        by_symbol.setdefault(symbol, []).append(trade)
    effect = 0.0
    fees = 0.0
    rows_out: list[dict[str, Any]] = []
    complete = True
    unvalued = 0
    for account, rows in (closed or {}).items():
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            qty = _number(row.get("sold_qty"))
            prev = _number(row.get("prev_close"))
            stored_day = _number(row.get("day_change"))
            # An unread share count is not a zero share count: without it the prior-close value of what was
            # sold is unknown, so the row falls through to its stored figure or is left incomplete.
            prior = round(qty * prev, 2) if prev is not None and qty is not None else None
            trade = by_key.get((str(account), symbol))
            if trade is None and len(by_symbol.get(symbol, [])) == 1:
                # The ledger's account label and the document's account key need not be the same string.
                # One trade for this symbol today is unambiguous; two are not, and are left unmatched.
                trade = by_symbol[symbol][0]
            gross = _number((trade or {}).get("amount")) if trade is not None else None
            fee_reported = _number((trade or {}).get("fees")) if trade is not None else None
            fee = fee_reported if fee_reported is not None else 0.0
            if trade is not None and fee_reported is None and gross is not None and prior is not None:
                # The commission is unread, so the net is an upper bound; the effect is disclosed and the
                # row is marked incomplete rather than presented as a reconciled number.
                complete = False
            if gross is not None and prior is not None:
                # Before its cost: what the sale did to the book is gross proceeds against the prior close, and
                # the commission is the fee component's own negative line. Net is published for the drill-down.
                net = round(gross - fee, 2)
                contribution = round(gross - prior, 2)
                source = "trade_gross_proceeds_minus_prior_close"
                fees += fee
            elif stored_day is not None:
                contribution = round(stored_day, 2)       # gross: the stored figure excludes fees
                source = "closed_today_stored_gross"
                net = None
                complete = False
            else:
                # No prior close and no stored day change: this row cannot be valued at all, so its own
                # commission was never read. It is counted, not forgotten -- the day's fee total must not claim
                # to be complete over a closed row nobody could read (review cc-deepseek-8 rev-7 delta C1).
                complete = False
                unvalued += 1
                continue
            effect += contribution
            rows_out.append({"account": account, "symbol": symbol, "sold_qty": qty, "prior_close": prev,
                             "prior_usd": prior, "gross_proceeds_usd": gross, "net_proceeds_usd": net,
                             "fees_usd": fee or None, "contribution_usd": contribution,
                             # A stored figure is gross by construction; a matched trade's fee is read unless
                             # the ledger left the column out. Per row, so a row outside the interval cannot
                             # make the interval's fees unknown (and vice versa).
                             "fee_complete": bool(trade is not None and fee_reported is not None
                                                  and source == "trade_gross_proceeds_minus_prior_close"),
                             "net_effect_usd": round(net - prior, 2) if net is not None else None,
                             "source": source})
    return {"value": round(effect, 2), "fees": round(fees, 2), "complete": complete, "rows": rows_out,
            # The closed rows the valuation pass dropped (producer: {"day_change": null, "reason":
            # "no_prev_close"}). Their commissions were never read, so they are counted here and the interval's
            # fee is not published as a complete number while any exist.
            "unvalued_rows": unvalued}


def _close_scope(trade: Mapping[str, Any], prior_rows: Mapping[tuple[str, str], float] | None,
                 trades: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Which closed rows the measured interval actually contains, decided per row.

    A row's sale enters ``start`` only when the prior-close book still holds its position: then the sale happened
    after that book was captured, and ``start`` does not contain it. When the book no longer holds it the exit is
    already reflected, and adding the row again counts the whole sale twice (LQ-3124R F1: the live change read
    -27,791.20 for a -4,446.74 move on 2026-11-14 00:37 ET). Keyed on the position, not on a date, so a book
    captured before a same-day sale still keeps it.

    The components differ from ``start`` by one case: a position bought and sold inside the interval never sat in
    the prior book, yet its realized gain is in the ending equity and is a real component of the change. So a row
    is a component when its position was held at the prior close OR its symbol traded inside the interval. An
    exit from before the book leaves both -- it is published with ``prior_usd: null`` and a reason.
    """
    prior = prior_rows or {}
    book_observed = prior_rows is not None
    traded = {str(t.get("symbol") or "").upper() for t in trades or [] if isinstance(t, Mapping)}
    rows: list[dict[str, Any]] = []
    for item in trade.get("rows") or []:
        row = dict(item)
        symbol = str(row.get("symbol") or "").upper()
        in_book = (str(row.get("account") or ""), symbol) in prior
        row["held_at_prior_close"] = in_book if book_observed else None
        # No book at all: the rule cannot say the exit is already reflected, so the row is kept (the old
        # behaviour) and the row says so -- dropping it would silently lose the sale from an estimated start.
        row["counted_in_start"] = bool(row.get("prior_usd") is not None
                                       and (in_book or not book_observed))
        row["counted_in_components"] = bool(not book_observed or in_book or symbol in traded)
        if book_observed and not in_book and symbol in traded:
            row["not_added_reason"] = ("the prior-close book never held this position, so start must not add it; "
                                       "the gain is the interval's own trade and is counted in the components")
        elif book_observed and not in_book:
            row["not_added_reason"] = ("the prior-close book no longer holds this position, so the change "
                                       "already reflects the exit; adding it again would double the sale")
        elif not book_observed:
            row["not_added_reason"] = ("no prior-close book was read, so this row's position cannot be matched "
                                       "to it; the row is kept and the start stays an estimate")
        rows.append(row)
    # Completeness of the set (the panel's own question) is not the same as completeness of the fees this
    # interval carries: a stored-gross row from before the book leaves the day's fee complete at 0.00, while the
    # panel still has to say the set was read gross.
    in_scope = [r for r in rows if r.get("counted_in_components")]
    fees_incomplete = any(not r.get("fee_complete") for r in in_scope)
    # A row dropped before it reached ``rows`` still had a commission nobody read: the fee total is complete
    # only when every closed row of the day was valued (review cc-deepseek-8 rev-7 delta C1).
    unvalued_rows = int(trade.get("unvalued_rows") or 0)  # nosemgrep: tq-py-missing-as-zero -- a count of dropped rows, not a value: absence means the trades pass counted none
    return {
        "rows": rows,
        "start_add": round(sum(float(r["prior_usd"]) for r in rows if r["counted_in_start"]), 2),
        "effect": round(sum(float(r["contribution_usd"]) for r in rows if r["counted_in_components"]), 2),
        # A row whose fee_complete is true has read its commission; a read zero is published as None by
        # `fee or None`, so 0.0 here is the read value, never a missing one (fees_complete guards the total).
        "fees": round(sum(float(r.get("fees_usd") or 0.0)  # nosemgrep: tq-py-missing-as-zero -- read zero, guarded by fees_complete
                          for r in rows if r["counted_in_components"]), 2),
        "complete": trade.get("complete"),
        "fees_complete": not fees_incomplete and not unvalued_rows,
        "unvalued_rows": unvalued_rows,
        "accounted": any(r["counted_in_components"] for r in rows),
    }


def _account_of(row: Mapping[str, Any]) -> str:
    return str(row.get("account_key") or row.get("account_id") or row.get("account") or "")


def _split_accounts(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if isinstance(row, Mapping) and not row.get("is_loan"):
            out.setdefault(_account_of(row), []).append(row)
    return out


def _transfers_block(transfers: Iterable[Mapping[str, Any]] | None,
                     accounts: Iterable[str]) -> dict[str, Any]:
    """Classify today's transfers: an internal one has both ends inside the book and cancels in the total.

    ``amount`` is the magnitude the source recorded; the sign is the direction (into the book is positive).
    An end that is unset or names an account outside the book is external: it changes the book's equity.
    """
    inside = {str(a) for a in accounts}
    internal: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    for item in transfers or []:
        if not isinstance(item, Mapping):
            continue
        amount = _number(item.get("amount"))
        if amount is None:
            # An unread amount is not a zero transfer: the movement is unknown and is listed as such.
            unread.append({"from_account": item.get("from_account"), "to_account": item.get("to_account"),
                           "reason": "the transfer amount was not read"})
            continue
        amount = abs(amount)
        if not amount:
            continue
        from_acct = str(item.get("from_account") or "")
        to_acct = str(item.get("to_account") or "")
        both = bool(from_acct and to_acct and from_acct in inside and to_acct in inside)
        record = {"from_account": from_acct or None, "to_account": to_acct or None,
                  "amount_usd": round(amount, 2), "transfer_type": item.get("transfer_type"),
                  "transfer_date": _iso(item.get("transfer_date")), "internal": both}
        if both:
            internal.append(record)
        else:
            # Signed for the book: money arriving is positive, money leaving is negative.
            arriving = to_acct in inside and from_acct not in inside
            record["signed_usd"] = round((1.0 if arriving else -1.0) * amount, 2)
            external.append(record)
    return {"internal": internal, "external": external, "unread": unread,
            # "Read the ledger and found no external flow" is 0.00; "did not read it" is null; and one unread
            # amount makes the net an understatement, so it is null too.
            "external_net_usd": (None if transfers is None or unread else
                                 round(sum(r["signed_usd"] for r in external), 2))}


def _reconciliation(rows: list[Mapping[str, Any]], *, prior_rows: Mapping[tuple[str, str], float] | None,
                    prior_source: str | None, prior_as_of: Any, closed: Mapping[str, Any],
                    trades: Iterable[Mapping[str, Any]] | None, income: Any, external_flows: Any,
                    transfers: Mapping[str, Any] | None, transfers_observed: bool = False,
                    transfers_unread: int = 0,
                    prior_shares: Mapping[tuple[str, str], float] | None = None,
                    bought_today: set[tuple[str, str]] | None = None) -> dict[str, Any]:
    """The signed per-account bridge, published as evidence — never as an invented final P&L number."""
    per_account: list[dict[str, Any]] = []
    book_accounts = {k[0] for k in (prior_rows or {})}
    for account, acct_rows in _split_accounts(rows).items():
        end = 0.0
        end_unknown: list[str] = []
        start = 0.0
        start_unknown: list[str] = []
        move = 0.0
        move_unknown: list[str] = []
        for row in acct_rows:
            symbol = str(row.get("symbol") or "").upper()
            value = row_store_value(row)
            if value is None:
                end_unknown.append(symbol)
            else:
                end += value
            if _cash(row):
                observed = (prior_rows or {}).get(_key(row))
                before = observed if observed is not None else value
                if observed is None:
                    start_unknown.append(f"{symbol}: prior cash not observed; carried at face")
                if before is not None:
                    start += before
                continue
            prior, _source = _row_start_value(row, prior_rows, prior_source, book_accounts, prior_shares,
                                              bought_today)
            if prior is None:
                start_unknown.append(f"{symbol}: no prior-close baseline")
            else:
                start += prior
                # The move keeps its own fill-aware basis (the review's option (a) leaves the price-move block
                # alone): a share change there is a flow, not a re-mark. The two bases differ only on a day
                # with a share change, and the difference shows up as a disclosed residual.
                move_prior, _move_source = _row_prior_value(row, prior_rows, prior_source)
                if value is not None and move_prior is not None:
                    move += value - move_prior
            if value is None:
                move_unknown.append(symbol)
        acct_closed = (closed or {}).get(account) if isinstance(closed, Mapping) else None
        trade = _trades_effect({account: acct_closed or []}, trades)
        scope = _close_scope(trade, prior_rows, trades)
        start += scope["start_add"]
        flows = external_flows.get(account) if isinstance(external_flows, Mapping) else external_flows
        inc = income.get(account) if isinstance(income, Mapping) else income
        # Internal movements net inside the book: they move value between accounts, so only the direction
        # changes this account's cash, and the consolidated total cancels them. "Read, found none" is 0.00;
        # "not read" is None.
        internal = sum((r["amount_usd"] if r.get("to_account") == account else -r["amount_usd"])
                       for r in (transfers or {}).get("internal", [])
                       if account in (r.get("to_account"), r.get("from_account")))
        if flows is None and transfers_observed and not transfers_unread:
            flows = sum(r["signed_usd"] for r in (transfers or {}).get("external", [])
                        if account in (r.get("to_account"), r.get("from_account")))
        components = {
            "price_move": round(move, 2) if not move_unknown else None,
            # 0.00 means "no closed row belongs to this interval" (a stored exit from before the book, or no
            # sale at all); None means a closed row existed and could not be valued.
            "closed_today_trade_effect": (scope["effect"] if scope["rows"]
                                          else (0.0 if not acct_closed else None)),
            # The commission is an expense: it enters the bridge negative, and it is never netted into the
            # trade effect. A store that has not booked it yet leaves a residual that is reported.
            "fees_today": _expense(scope["fees"]) if scope["fees_complete"] else None,
            "income_today": _number(inc),
            "external_flows_today": _number(flows),
            "internal_transfers_today": (round(internal, 2)
                                         if transfers_observed and not transfers_unread else None),
        }
        unobserved = [k for k, v in components.items() if v is None]
        if end_unknown:
            unobserved.append("end_equity")
        if start_unknown:
            unobserved.append("start_equity")
        resolved = (not start_unknown and not move_unknown and end_unknown == []
                    and components["closed_today_trade_effect"] is not None)
        explained = round(sum(v for v in components.values() if v is not None), 2)
        delta = round(end - start, 2) if resolved else None
        # The signed residual is only published when every component was read; the arithmetic over the ones
        # that WERE read is always published beside it under its own name, so a missing source is named rather
        # than absorbed into the identity.
        known_residual = round(delta - explained, 2) if delta is not None else None
        residual = known_residual if known_residual is not None and not unobserved else None
        if not resolved:
            status = "UNKNOWN"
        elif unobserved:
            status = "PARTIAL"
        elif residual is not None and abs(residual) <= RECON_TOLERANCE_USD:
            status = "RECONCILED"
        else:
            status = "UNEXPLAINED"
        per_account.append({
            "account": account,
            "start_equity": {"value_usd": round(start, 2) if resolved else None,
                             "source": prior_source, "as_of": _iso(prior_as_of)},
            "end_equity": {"value_usd": round(end, 2) if not end_unknown else None,
                           "source": "the positions store's broker marks"},
            "delta_usd": delta,
            "components": components,
            "explained_usd": explained,
            "residual": {"value_usd": residual, "within_tolerance": (residual is not None
                                                                     and abs(residual) <= RECON_TOLERANCE_USD),
                         "known_components_residual_usd": known_residual,
                         "tolerance_usd": RECON_TOLERANCE_USD,
                         "provisional": bool(unobserved),
                         "unknown_components": unobserved,
                         "policy": "reported, never allocated"},
            "unobserved": unobserved,
            "start_unknown": start_unknown,
            "end_unknown": end_unknown,
            "status": status,
        })
    total_start = sum(a["start_equity"]["value_usd"] for a in per_account
                      if a["start_equity"]["value_usd"] is not None)
    total_end = sum(a["end_equity"]["value_usd"] for a in per_account
                    if a["end_equity"]["value_usd"] is not None)
    all_resolved = all(a["delta_usd"] is not None for a in per_account) and bool(per_account)
    total_delta = round(total_end - total_start, 2) if all_resolved else None
    total_explained = round(sum(a["explained_usd"] for a in per_account), 2)
    total_residual = round(total_delta - total_explained, 2) if total_delta is not None else None
    # A consolidated residual is only a signed statement when every component of every account was read. With
    # one component unobserved (income, say) the exact arithmetic over the known components can still come out
    # to 0.00 and read as "reconciled" to anyone who screenshots it. So the signed value is withheld as
    # `null`, published as `provisional`, and the unknown components are named — unknown beats a wrong zero.
    total_unknown = sorted({k for a in per_account for k in a["unobserved"]})
    total_provisional = bool(total_unknown) or not all_resolved
    statuses = {a["status"] for a in per_account}
    if not per_account or "UNKNOWN" in statuses:
        total_status = "UNKNOWN" if not per_account else "PARTIAL"
    elif "PARTIAL" in statuses or any(a["unobserved"] for a in per_account):
        total_status = "PARTIAL"
    elif "UNEXPLAINED" in statuses:
        total_status = "UNEXPLAINED"
    else:
        total_status = "RECONCILED"
    return {
        "contract_version": RECONCILIATION_VERSION,
        "policy": RECON_POLICY,
        "accounts": per_account,
        "total": {
            "start_equity_usd": round(total_start, 2) if all_resolved else None,
            "end_equity_usd": round(total_end, 2) if all_resolved else None,
            "delta_usd": total_delta, "explained_usd": total_explained if all_resolved else None,
            "residual": {"value_usd": None if total_provisional else total_residual,
                         "known_components_residual_usd": total_residual,
                         "within_tolerance": (not total_provisional and total_residual is not None
                                              and abs(total_residual) <= RECON_TOLERANCE_USD),
                         "tolerance_usd": RECON_TOLERANCE_USD,
                         "provisional": total_provisional,
                         "unknown_components": total_unknown,
                         "policy": "reported, never allocated"},
            "accounts_reconciled": sum(1 for a in per_account if a["status"] == "RECONCILED"),
            "accounts_total": len(per_account),
            "status": total_status,
        },
        "internal_transfers": (transfers or {}).get("internal", []),
        "external_flows_net_usd": (transfers or {}).get("external_net_usd", external_flows
                                                        if not isinstance(external_flows, Mapping) else None),
        "note": ("this is coverage and signed evidence, not a verified P&L: the verified label stays UNKNOWN "
                 "until a stored reconciliation is signed off"),
    }


def portfolio_measures(doc: Mapping[str, Any] | None, *, prior_snapshot: Mapping[str, Any] | None = None,
                       trades: Iterable[Mapping[str, Any]] | None = None,
                       income: float | None = None, external_flows: float | None = None,
                       transfers: Iterable[Mapping[str, Any]] | None = None,
                       now: datetime | None = None) -> dict[str, Any]:
    """The four measures for one written book.

    ``doc`` is the holdings document being written (broker marks; ``closed_today``; Finviz marks on the
    rows). ``prior_snapshot`` is the observed book at the prior close: ``{"as_of", "source", "rows":
    {(account, symbol): value}, "shares": {(account, symbol): qty}}`` read by the writer from its own store;
    without it the prior-close measures stay UNKNOWN. ``trades`` are the day's trades (net amount and fees); ``income``/``external_flows`` are
    known values or None (unknown). Pure: no I/O, no DB, no clock reads beyond ``now``.
    """
    at = now or datetime.now(timezone.utc)
    doc = doc or {}
    rows = [r for r in (doc.get("holdings") or []) if isinstance(r, Mapping)]
    prior_rows = None
    prior_shares = None
    prior_as_of = prior_source = None
    if isinstance(prior_snapshot, Mapping):
        raw = prior_snapshot.get("rows")
        if isinstance(raw, Mapping):
            prior_rows = {tuple(k) if isinstance(k, (tuple, list)) else (str(k), ""): _number(v)
                          for k, v in raw.items()}
        raw_shares = prior_snapshot.get("shares")
        if isinstance(raw_shares, Mapping):
            prior_shares = {tuple(k) if isinstance(k, (tuple, list)) else (str(k), ""): _number(v)
                            for k, v in raw_shares.items()}
        prior_as_of = prior_snapshot.get("as_of")
        prior_source = prior_snapshot.get("source") or "prior_snapshot"
    # Which rows a purchase created inside the interval -- built once so the change's start and the signed
    # bridge cannot disagree about a row (review cc-deepseek-8 2026-11-14 C1).
    bought_today = _purchase_keys(trades)

    # 1. account value: the broker anchor, with the Finviz estimate beside it.
    total = 0.0
    unvalued: list[dict[str, Any]] = []
    finviz_total = 0.0
    finviz_unvalued = 0
    marks_at: list[str] = []
    for row in rows:
        value = row_store_value(row)
        if value is None:
            unvalued.append({"account": row.get("account_key") or row.get("account"),
                             "symbol": str(row.get("symbol") or "").upper()})
        else:
            total += value
        fv = row_finviz_value(row)
        if fv is None:
            finviz_unvalued += 1
        else:
            finviz_total += fv
        stamp = row.get("canonical_mark_ingested_at")
        if stamp:
            marks_at.append(str(stamp))
    account_value = {
        "measure": MEASURE_ACCOUNT_VALUE, "label": LABEL_ACCOUNT_VALUE, "basis": BASIS_STORE,
        "value": round(total, 2) if not unvalued else None,
        "status": "MEASURED" if not unvalued else ("PARTIAL" if total else "UNKNOWN"),
        "as_of": _iso(doc.get("as_of") or doc.get("generated_at")
                      or (doc.get("portfolio_totals") or {}).get("as_of")),
        "rows": len([r for r in rows if not r.get("is_loan")]),
        "gap": (None if not unvalued else {"reason": "at least one row has no broker value",
                                           "unvalued_rows": unvalued[:20]}),
        "finviz_estimate": {
            "label": LABEL_FINVIZ_ESTIMATE, "basis": BASIS_FINVIZ,
            "value": round(finviz_total, 2) if not finviz_unvalued else None,
            "marks_at": sorted(marks_at)[-1] if marks_at else None,
            "delta": (round(finviz_total - total, 2)
                      if not finviz_unvalued and not unvalued else None),
            "note": FINVIZ_NEVER_ADDED,
        },
    }

    # 2. estimated price movement of the current holdings, broker anchor first.
    move = _price_move_block(rows, prior_rows, prior_source)
    price_move = {
        "measure": MEASURE_PRICE_MOVE, "label": LABEL_PRICE_MOVE, "definition": PRICE_MOVE_DEFINITION,
        "basis": BASIS_STORE, "value": move["value"], "status": move["status"],
        "as_of": account_value["as_of"], "coverage": {
            "measured_rows": move["measured_rows"], "unknown_rows": move["unknown_rows"],
            "unknown": move["unknown"], "row_count": len([r for r in rows if not r.get("is_loan")])},
        "row_basis_census": move["row_basis_census"], "rows": move["rows"], "gap": move["gap"],
        "finviz_estimate": _finviz_estimate(rows, doc, prior_rows, prior_source),
    }
    if isinstance(price_move["finviz_estimate"], Mapping):
        fin_total = price_move["finviz_estimate"].get("total_with_broker_nav")
        price_move["finviz_estimate"]["delta_vs_broker"] = (
            round(price_move["value"] - fin_total, 2)
            if price_move["value"] is not None and fin_total is not None else None)
        price_move["finviz_estimate"]["delta_note"] = FINVIZ_NEVER_ADDED

    # 3. account value change since the prior close: two equities on the broker basis.
    closed = (doc.get("closed_today") or {}) if isinstance(doc.get("closed_today"), Mapping) else {}
    trade = _trades_effect(closed, trades)
    # Which of those rows the interval actually contains -- one decision, applied to both the start and the
    # components (review 2026-11-14: a stale same-date book and a same-session round trip are different cases).
    scope = _close_scope(trade, prior_rows, trades)
    start = 0.0
    start_unknown: list[dict[str, Any]] = []
    if account_value["value"] is None:
        start = None
    else:
        book_accounts = {k[0] for k in (prior_rows or {})}
        for row in rows:
            if row.get("is_loan"):
                continue
            if _cash(row):
                value = row_store_value(row)
                observed = (prior_rows or {}).get(_key(row))
                before = observed if observed is not None else value
                if observed is None:
                    start_unknown.append({"account": row.get("account_key") or row.get("account"),
                                          "symbol": "CASH", "reason": "prior cash not observed; carried at face"})
                if before is not None:
                    start += before
                continue
            prior, _source = _row_start_value(row, prior_rows, prior_source, book_accounts, prior_shares,
                                              bought_today)
            if prior is None:
                start_unknown.append({"account": row.get("account_key") or row.get("account"),
                                      "symbol": str(row.get("symbol") or "").upper(),
                                      "reason": "no prior-close baseline"})
            else:
                start += prior
        for item in scope["rows"]:
            if item.get("counted_in_start"):
                start += item["prior_usd"]
        start = round(start, 2)
    change_value = None
    if account_value["value"] is not None and start is not None and not start_unknown:
        change_value = round(account_value["value"] - start, 2)
    change_status = ("MEASURED" if change_value is not None
                     else ("PARTIAL" if account_value["value"] is not None and start and start_unknown
                           else "UNKNOWN"))
    # The internal/external split of the day's transfers is needed by BOTH measure 3's drill-down and the
    # signed bridge below, so it is built once here: two views of one day must not disagree about it.
    accounts = list(_split_accounts(rows))
    transfer_block = _transfers_block(transfers, accounts)
    external_net = (external_flows if external_flows is not None
                    else (transfer_block["external_net_usd"] if transfers is not None else None))
    # Every component of the identity, with fixed signs: the trade effect is gross of its fee, and the fee is
    # its own negative line. `reconciles` is a statement only when all of them were read; otherwise it is null
    # with the unread ones named, because "false" would claim a contradiction the code cannot see.
    drill_parts = {
        "price_move_estimate": price_move["value"],
        "closed_today_trade_effect": scope["effect"] if scope["rows"] or not closed else None,
        "fees_today": _expense(scope["fees"]) if scope["fees_complete"] else None,
        "income_today": income,
        "external_flows_today": external_net,
    }
    drill_unobserved = [k for k, v in drill_parts.items() if v is None]
    account_change = {
        "measure": MEASURE_ACCOUNT_VALUE_CHANGE, "label": LABEL_ACCOUNT_VALUE_CHANGE,
        "definition": ACCOUNT_VALUE_CHANGE_DEFINITION, "basis": BASIS_STORE,
        "value": change_value, "status": change_status,
        "start": {"equity_usd": start, "as_of": _iso(prior_as_of), "source": prior_source,
                  "note": ("prior-close baselines: the prior book's own share count valued at each row's "
                           "broker prior_close (the book's observed value where that price is unknown), so a "
                           "trim or an add never moves the start's count; cash from the same observation")},
        "end": {"equity_usd": account_value["value"], "as_of": account_value["as_of"],
                "source": "the positions store's broker marks"},
        "drill_down": {
            **drill_parts,
            "closed_today_rows": scope["rows"],
            "closed_today_complete": scope["complete"],
            "reconciles": (None if change_value is None or drill_unobserved else
                           abs(sum(drill_parts.values()) - change_value) <= RECON_TOLERANCE_USD),
            "reconciles_unobserved": drill_unobserved,
        },
        "gap": (None if change_value is not None else
                {"reason": ("no matched prior-close equity including cash: the starting equity must be an "
                            "observed book at the prior close, never derived as total - change"),
                 "start_unknown": start_unknown[:20]}),
    }

    # 3b. the signed per-account bridge and the coverage of every source behind it.
    reconciliation = _reconciliation(rows, prior_rows=prior_rows, prior_source=prior_source,
                                     prior_as_of=prior_as_of, closed=closed, trades=trades, income=income,
                                     external_flows=external_flows, transfers=transfer_block,
                                     transfers_observed=transfers is not None,
                                     transfers_unread=len(transfer_block["unread"]),
                                     prior_shares=prior_shares, bought_today=bought_today)
    coverage = {
        "prior_close_book": {
            "observed": prior_rows is not None,
            "source": prior_source, "as_of": _iso(prior_as_of),
            "rows": len(prior_rows or {}),
            "reason": (None if prior_rows is not None else
                       "no prior-close book was read; the prior-close measures stay UNKNOWN"),
        },
        "trades_today": {
            "observed": trades is not None, "source": "trade_transactions",
            "rows": len([t for t in (trades or []) if isinstance(t, Mapping)]),
            "unmatched_closed_rows": sum(1 for a in reconciliation["accounts"]
                                         for c in (a["components"],) if c["closed_today_trade_effect"] is None),
            "reason": (None if trades is not None else
                       "the day's trades were not read; a sold position's effect is stored-gross or unknown"),
        },
        "fees": {
            "observed": trades is not None,
            "source": "trade_transactions.fees",
            "unknown_trades": sum(1 for a in reconciliation["accounts"]
                                  if a["components"]["fees_today"] is None),
        },
        "income": {
            "observed": income is not None, "source": "operator-supplied known value" if income is not None
            else None,
            "reason": (None if income is not None else
                       "no income source is bound: the dividend ledger dates no payment, so income is "
                       "UNKNOWN rather than zero"),
        },
        "transfers_today": {
            "observed": transfers is not None, "source": "account_transfers",
            "rows": len(transfer_block["internal"]) + len(transfer_block["external"]),
            "internal": len(transfer_block["internal"]), "external": len(transfer_block["external"]),
            "unread": len(transfer_block["unread"]),
            "reason": (None if transfers is not None and not transfer_block["unread"] else
                       ("the transfers ledger was not read; external contributions stay UNKNOWN and the "
                        "verified P&L cannot be signed" if transfers is None else
                        f"{len(transfer_block['unread'])} transfer row(s) had no readable amount; those "
                        "movements are UNKNOWN")),
        },
        "nav_dated_rows": price_move["finviz_estimate"].get("broker_nav_rows", []),
        "note": ("coverage is what was actually read for this book; an unobserved source is null with its "
                 "reason and is never treated as zero"),
    }

    # 4. verified daily P&L: only ever a stored, verified reconciliation.
    stored = doc.get("verified_reconciliation") if isinstance(doc.get("verified_reconciliation"), Mapping) else {}
    verified_value = _number((stored or {}).get("value")) if (stored or {}).get("verified") else None
    verified = {
        "measure": MEASURE_VERIFIED_PNL, "label": LABEL_VERIFIED_PNL,
        "definition": VERIFIED_PNL_DEFINITION, "value": verified_value,
        "status": "VERIFIED" if verified_value is not None else "UNKNOWN",
        "as_of": _iso((stored or {}).get("as_of")),
        "source": (stored or {}).get("source"),
        "candidate": change_value,
        "known_components": {
            "price_move_estimate": price_move["value"],
            "closed_today_trade_effect": scope["effect"] if scope["rows"] or not closed else None,
            "fees_today": _expense(scope["fees"]) if scope["fees_complete"] else None,
            "income_today": income,
            "external_flows_today": external_net,
            "internal_transfers_today": reconciliation["internal_transfers"],
            "reconciliation_status": reconciliation["total"]["status"],
            "reconciliation_residual_usd": reconciliation["total"]["residual"]["value_usd"],
            "reconciliation_residual_provisional": reconciliation["total"]["residual"]["provisional"],
            "reconciliation_unknown_components": reconciliation["total"]["residual"]["unknown_components"],
            "reconciliation_known_components_residual_usd":
                reconciliation["total"]["residual"]["known_components_residual_usd"],
            "note": ("internal transfers cancel in the consolidated total; a component that is None is "
                     "UNKNOWN and is never treated as zero; the fee is its own negative line beside the "
                     "gross trade effect"),
        },
        "gap": (None if verified_value is not None else
                {"reason": VERIFIED_PNL_GAP, "requires": "stored signed per-account reconciliation"}),
    }

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": _iso(at),
        "as_of": account_value["as_of"],
        "session": doc.get("session") or doc.get("as_of"),
        "basis": {"applied": BASIS_STORE,
                  "why": ("broker-reported account values and broker evidence are the accounting anchor "
                          "(operator Q1, 2026-11-13); Finviz marks are published only as estimates")},
        "measures": {
            "account_value": account_value,
            "price_move_estimate": price_move,
            "account_value_change_1d": account_change,
            "verified_daily_pnl": verified,
        },
        "labels": {
            "account_value": LABEL_ACCOUNT_VALUE,
            "price_move_estimate": LABEL_PRICE_MOVE,
            "account_value_change_1d": LABEL_ACCOUNT_VALUE_CHANGE,
            "verified_daily_pnl": LABEL_VERIFIED_PNL,
        },
        "finviz_estimates_are_separate": True,
        "reconciliation": reconciliation,
        "source_coverage": coverage,
    }


def measures_absent(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """The read-path contract when the document carries no written measures block.

    GET never computes: a document written before the writer materialized the measures publishes UNKNOWN
    measures with a reason, not a fresh calculation on every request.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "UNKNOWN",
        "materialized": False,
        "as_of": None,
        "gap": {"reason": ("this holdings document was written before the measures were materialized; the "
                           "writer must run once before the four measures are published (GET never computes)")},
        "measures": {MEASURE_ACCOUNT_VALUE: {"label": LABEL_ACCOUNT_VALUE, "value": None,
                                             "status": "UNKNOWN", "measure": MEASURE_ACCOUNT_VALUE},
                     MEASURE_PRICE_MOVE: {"label": LABEL_PRICE_MOVE, "value": None, "status": "UNKNOWN",
                                          "measure": MEASURE_PRICE_MOVE},
                     MEASURE_ACCOUNT_VALUE_CHANGE: {"label": LABEL_ACCOUNT_VALUE_CHANGE, "value": None,
                                                    "status": "UNKNOWN",
                                                    "measure": MEASURE_ACCOUNT_VALUE_CHANGE},
                     MEASURE_VERIFIED_PNL: {"label": LABEL_VERIFIED_PNL, "value": None, "status": "UNKNOWN",
                                            "measure": MEASURE_VERIFIED_PNL}},
        "labels": {"account_value": LABEL_ACCOUNT_VALUE, "price_move_estimate": LABEL_PRICE_MOVE,
                   "account_value_change_1d": LABEL_ACCOUNT_VALUE_CHANGE,
                   "verified_daily_pnl": LABEL_VERIFIED_PNL},
    }
