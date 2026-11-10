"""Priced realized P&L, and the sells whose cost basis is unknown.

The priced total is only the sells the journal could price. An unknown-basis
sell is counted and its proceeds are named. It is never given a basis, and its
proceeds are never added into the priced total. A read that did not happen is
None, not zero.
"""
from __future__ import annotations


def realized_scope(
    *,
    priced: float | None,
    unpriced_count: int | None,
    unpriced_proceeds: float | None,
    unpriced_known: bool,
) -> dict:
    """Return priced_realized, unpriced_count and unpriced_proceeds.

    ``unpriced_known`` is true only when the unknown-basis aggregate was read.
    A failed read leaves the count and proceeds as None.
    """
    if priced is None:
        priced_out = None
    else:
        priced_out = round(float(priced), 2)
    # A member that was not read stays unknown even when the caller says the
    # aggregate was attempted. Only an actual number, including a measured 0,
    # is published.
    if not unpriced_known or unpriced_count is None or unpriced_proceeds is None:
        count_out = None
        proceeds_out = None
    else:
        count_out = int(unpriced_count)
        proceeds_out = round(float(unpriced_proceeds), 2)
        if count_out < 0:
            raise ValueError("unpriced_count")
    return {
        "priced_realized": priced_out,
        "unpriced_count": count_out,
        "unpriced_proceeds": proceeds_out,
    }
