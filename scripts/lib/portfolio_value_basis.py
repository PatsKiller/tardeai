"""The positions-store basis for the served account and portfolio totals (LQ-20261107-1732).

The Overview payload's financial facts come from ``cio_truth.overview_payload``, which re-marks every
holding row at a live quote on the read (Finviz cache, else a data-broker backup quote). That is the
right number for the holdings table, and it is deliberately *not* the custodian's number: two quote
feeds disagree row by row, and one frozen or mis-scaled quote moves the re-marked sum by hundreds of
dollars on a $1.26M book. Measured 2026-11-09 19:03 ET: ``portfolio_value`` 1,256,753.20 against
``positions_current`` 1,256,416.32, of which 295.10 was one row (SRNE: 1,000 shares marked at an
Alpaca backup quote of 0.2954 where the broker carries ~$0.0003/share, the 1000x-scaling trap).

A total is the custodian's statement about the account, not an estimate of it, so the number carried
under the total's own names must be the store's basis — the same basis the numbers-truth audit
grades against (DSN-20261109 REV 2: the DB is the system of record; a total is the sum of the
``positions_current`` rows). The live re-mark stays on the payload beside it, named and with its
delta, so no real move is hidden: a reader can see both figures and which one is the total.

This module does not decide which quote a row should carry. It only publishes the basis split; the
per-row mark defects (SRNE's frozen 1000x quote) remain the row-level findings they already are.
"""
from __future__ import annotations

from typing import Any, Mapping

STORE_BASIS = "positions_store"
LIVE_MARK_BASIS = "live_mark"


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def row_store_value(row: Mapping[str, Any]) -> float | None:
    """The row's dollars on the positions store's own basis, or None when the row cannot say.

    Non-cash rows carry the broker's own mark as ``broker_market_value``. A cash row's dollars are
    its share count (the store's cash rows carry the balance in ``broker_shares``); the broker value
    is the fallback when the count is absent.
    """
    market_value = _number(row.get("broker_market_value"))
    if row.get("is_cash"):
        shares = _number(row.get("broker_shares"))
        if shares is not None:
            return round(shares, 2)
        return round(market_value, 2) if market_value is not None else None
    return round(market_value, 2) if market_value is not None else None


def store_totals(portfolio: Mapping[str, Any] | None) -> dict[str, Any]:
    """Per-account and total dollars from the store's own row values.

    ``total`` is None unless *every* row could be valued: a partial sum under the total's name
    would be a short total presented as the whole book.
    """
    rows = list((portfolio or {}).get("holdings") or [])
    by_account: dict[str, float] = {}
    cash_by_account: dict[str, float] = {}
    unvalued: list[dict[str, Any]] = []
    for row in rows:
        account = row.get("account_id") or row.get("account")
        value = row_store_value(row)
        if not account or value is None:
            unvalued.append({"account": account, "symbol": row.get("symbol")})
            continue
        by_account[account] = round(by_account[account] + value, 2) if account in by_account else value
        if row.get("is_cash"):
            cash_by_account[account] = (round(cash_by_account[account] + value, 2)
                                        if account in cash_by_account else value)
    return {
        "total": round(sum(by_account.values()), 2) if rows and not unvalued else None,
        "by_account": by_account,
        "cash": round(sum(cash_by_account.values()), 2) if rows and not unvalued else None,
        "cash_by_account": cash_by_account,
        "unvalued": unvalued,
        "row_count": len(rows),
    }


def store_document(portfolio: Mapping[str, Any] | None, st: Mapping[str, Any],
                   as_of: Any = None) -> dict[str, Any]:
    """A holdings document whose rows and totals are the store's basis, for the total contract.

    Position counts, labels and every other row field come through unchanged; only the dollars each
    row and the document total carry are replaced, so the contract's header, its by-account sum and
    its row sum are all the same basis.
    """
    rows = []
    for row in (portfolio or {}).get("holdings") or []:
        value = row_store_value(row)
        rows.append({**row, "market_value": value if value is not None else row.get("market_value")})
    return {
        "holdings": rows,
        "portfolio_totals": {
            "as_of": as_of,
            "total_value": (st or {}).get("total"),
            "total_cash": (st or {}).get("cash"),
            "broker_market_value_total": (st or {}).get("total"),
        },
        "document_source": "positions_current",
    }


def _live_by_account(portfolio: Mapping[str, Any] | None) -> dict[str, float | None]:
    return {r.get("account_id"): _number(r.get("total_usd"))
            for r in (portfolio or {}).get("accounts") or []}


def publish_store_totals(out: dict[str, Any], portfolio: Mapping[str, Any] | None) -> dict[str, Any]:
    """Publish the store basis under the totals' names and keep the live re-mark beside them.

    Degrades to the live-mark total — with ``totals_basis.basis == "live_mark"`` and the reason —
    when any row has no broker value, so a caller that has never seen a broker-marked document
    keeps the behaviour it had and says which basis it is showing.
    """
    live_total = _number((portfolio or {}).get("total_usd"))
    live_by = _live_by_account(portfolio)
    st = store_totals(portfolio)
    basis = {
        "basis": STORE_BASIS if st["total"] is not None else LIVE_MARK_BASIS,
        "store_total": st["total"],
        "live_mark_total": live_total,
        "store_minus_live_mark_usd": (round(st["total"] - live_total, 2)
                                      if st["total"] is not None and live_total is not None else None),
        "live_mark_basis": "the holdings rows re-marked at their live quote on this read",
        "row_count": st["row_count"],
        "unvalued_rows": st["unvalued"],
        "source": "positions_current",
    }
    out["totals_basis"] = basis
    if st["total"] is None:
        basis["reason"] = ("at least one row carries no broker value, so a complete store total "
                           "cannot be published; the re-marked rows remain the total")
        return out

    total = st["total"]
    out["portfolio_value"] = total
    out["derived_total_value"] = total

    pricing = out.get("pricing")
    if isinstance(pricing, dict):
        pricing["canonical_total_value"] = total
        pricing["derived_total_value"] = total
        pricing["live_mark_total_value"] = live_total

    today_by_account = out.get("today_by_account")
    if isinstance(today_by_account, dict):
        for account, row in today_by_account.items():
            if not isinstance(row, dict):
                continue
            live = live_by.get(account)
            store = st["by_account"].get(account)
            if store is not None:
                row["value"] = store
            row["live_value"] = live

    aggregate = out.get("portfolio_aggregate")
    if isinstance(aggregate, dict):
        aggregate["aggregate_value"] = total
        aggregate["live_mark_aggregate_value"] = live_total
        for row in aggregate.get("accounts") or []:
            if not isinstance(row, dict):
                continue
            account = row.get("account")
            store = st["by_account"].get(account)
            if store is None:
                continue
            row["live_total_value"] = live_by.get(account)
            row["total_value"] = store
            row["display_value"] = store

    contract = out.get("portfolio_total")
    if isinstance(contract, dict):
        _patch_contract(contract, store_document(portfolio, st, as_of=contract.get("as_of")),
                        live_total, live_by, st)
    return out


def _patch_contract(contract: dict[str, Any], document: dict[str, Any], live_total: float | None,
                    live_by: Mapping[str, float | None], st: Mapping[str, Any]) -> None:
    """Rebuild the LQ-1611 total contract on the store basis, keeping the re-mark as an alternative."""
    from .portfolio_total_contract import build_portfolio_total

    rebuilt = build_portfolio_total(document)
    for key in ("value", "basis", "basis_label", "row_sum", "row_sum_unusable", "by_account",
                "by_account_sum", "agree", "findings", "alternatives"):
        if key in rebuilt:
            contract[key] = rebuilt[key]
    contract["basis"] = STORE_BASIS
    contract["basis_label"] = "the positions store's own broker marks — the custodian's statement"
    alternatives = [a for a in contract.get("alternatives") or [] if a.get("name") != "live_mark_total"]
    published = contract.get("value")
    alternatives.append({
        "name": "live_mark_total",
        "value": live_total,
        "delta": (round(published - live_total, 2)
                  if published is not None and live_total is not None else None),
        "basis": LIVE_MARK_BASIS,
        "why": "the same rows re-marked at a live quote on this read; the difference from the total "
               "is the quote drift since the last broker sync, expected between syncs and not an error "
               "— a row whose drift is a defect (a frozen or mis-scaled quote) is a row-level finding",
    })
    contract["alternatives"] = alternatives
    contract["live_mark_total"] = live_total
    contract["store_basis_by_account"] = dict(st.get("by_account") or {})
