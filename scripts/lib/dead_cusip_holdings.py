"""Apply the operator ignore rule to a read-side holdings document.

The predicate is ``security_identity.is_dead_cusip_holding`` (LQ-20261107-1417).
This module does not change that predicate and does not write the position store.
An ignored row is left out of a copy a reader returns. The broker row stays in the store.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _predicates():
    try:
        from scripts.lib.security_identity import is_cusip_like, is_dead_cusip_holding
    except ImportError:  # scripts/ is on sys.path for cron and some readers
        from lib.security_identity import is_cusip_like, is_dead_cusip_holding
    return is_cusip_like, is_dead_cusip_holding


def is_cusip_like(value: str) -> bool:
    pred, _dead = _predicates()
    return bool(pred(value))


def is_dead_cusip_holding(row: Mapping[str, Any] | None) -> bool:
    _cusip, pred = _predicates()
    return bool(pred(row))


def _keep(row: Any) -> bool:
    return not (isinstance(row, Mapping) and is_dead_cusip_holding(row))


def without_dead_cusip_holdings(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """Shallow copy of ``doc`` with dead CUSIP rows removed from holding lists.

    Lists filtered: ``holdings``, ``positions``, and ``accounts[].holdings``.
    Other keys stay the same objects. A non-mapping input becomes ``{}``.
    """
    if not isinstance(doc, Mapping):
        return {}
    out: dict[str, Any] = dict(doc)
    for key in ("holdings", "positions"):
        rows = out.get(key)
        if isinstance(rows, list):
            out[key] = [row for row in rows if _keep(row)]
    accounts = out.get("accounts")
    if isinstance(accounts, list):
        rebuilt: list[Any] = []
        for acct in accounts:
            if isinstance(acct, Mapping) and isinstance(acct.get("holdings"), list):
                acct = dict(acct)
                acct["holdings"] = [row for row in acct["holdings"] if _keep(row)]
            rebuilt.append(acct)
        out["accounts"] = rebuilt
    return out
