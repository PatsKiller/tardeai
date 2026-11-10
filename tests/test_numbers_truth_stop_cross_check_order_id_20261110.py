"""LQ-20261107-1796: NT_STOP_CROSS_CHECK compares each working stop order with ITS OWN lifecycle row.

cross_source keyed stop_lifecycle and stop_last_known by (account, symbol). A symbol with several orders (replaced,
cancelled, filled, then the working one) kept whichever row iterated last, so a cancelled order's lifecycle row was
graded against the working stop_last_known row: five false D34 pages on 2026-11-10 at 11:08 ET, each with the same
working order at the same price in both tables. Keyed by order_id, a working order is only ever compared with its
own lifecycle row.

Synthetic accounts, tickers and order ids (the repo is public).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_numbers_truth_audit_20261109 import (  # noqa: E402
    K_AB, S_AB, STOP_AS_OF, H, bundle, codes, run, write_state)

ACCT, SYM = "zz_taxable", "ZQAA"


def _life(oid: str, lifecycle: str, price: float) -> dict:
    return {"account": ACCT, "symbol": SYM, "order_id": oid, "lifecycle": lifecycle, "status": lifecycle,
            "stop_price": price, "qty": 100, "snapshot_at": STOP_AS_OF}


def _slk(oid: str, status: str, price: float) -> dict:
    return {"account": ACCT, "symbol": SYM, "order_id": oid, "status": status, "stop_price": price, "qty": 100,
            "captured_at": STOP_AS_OF}


#: the replaced/cancelled history, then the one working order -- identical in both tables
HISTORY = [("zq-0001", "cancelled", 70.0), ("zq-0002", "cancelled", 72.5), ("zq-0003", "cancelled", 75.0)]
WORKING = ("zq-0004", "working", 80.0)


def _root(tmp_path):
    return write_state(tmp_path, holdings=[H(), H(account="zz_ira", symbol="ZQAB", shares=50)])


def _check(tmp_path, life, slk):
    return run(_root(tmp_path), "holdings.stop_crosscheck", b=bundle(stops=[*life, S_AB], slk=[*slk, K_AB]))


def test_three_cancelled_and_one_working_order_in_both_tables_is_clean(tmp_path):
    """The 11:08 ET false page: every iteration order of the history must leave the working order clean."""
    life = [_life(*h) for h in HISTORY] + [_life(*WORKING)]
    slk = [_slk(*h) for h in HISTORY] + [_slk(*WORKING)]
    for life_order in (life, life[::-1], life[1:] + life[:1]):
        for slk_order in (slk, slk[::-1]):
            rep = _check(tmp_path, life_order, slk_order)
            assert rep["findings"] == [], rep["findings"]


def test_the_working_order_listed_before_a_cancelled_one_is_still_clean(tmp_path):
    """The last-row-wins case exactly: the cancelled row iterates after the working one."""
    rep = _check(tmp_path, [_life(*WORKING), _life("zq-0003", "cancelled", 80.0)], [_slk(*WORKING)])
    assert rep["findings"] == [], rep["findings"]


def test_a_working_order_whose_own_lifecycle_row_is_cancelled_is_one_finding(tmp_path):
    life = [_life(*h) for h in HISTORY] + [_life("zq-0004", "cancelled", 80.0)]
    slk = [_slk(*h) for h in HISTORY] + [_slk(*WORKING)]
    rep = _check(tmp_path, life, slk)
    assert codes(rep) == ["NT_STOP_CROSS_CHECK"]
    f = rep["findings"][0]
    assert "stop_lifecycle says cancelled" in f["detail"] and "zq-0004" in f["detail"]
    assert f["shown"]["order_id"] == "zq-0004" and f["truth"]["order_id"] == "zq-0004"


def test_a_price_disagreement_on_the_same_order_is_one_finding(tmp_path):
    life = [_life(*h) for h in HISTORY] + [_life(*WORKING)]
    slk = [_slk(*h) for h in HISTORY] + [_slk("zq-0004", "working", 79.0)]
    rep = _check(tmp_path, life, slk)
    assert codes(rep) == ["NT_STOP_CROSS_CHECK"]
    assert "vs stop_last_known" in rep["findings"][0]["detail"]


def test_prices_are_never_compared_across_different_orders(tmp_path):
    """A cancelled order at another price must not be graded against the working one."""
    rep = _check(tmp_path, [_life("zq-0003", "cancelled", 75.0), _life(*WORKING)],
                 [_slk("zq-0003", "cancelled", 75.0), _slk(*WORKING)])
    assert rep["findings"] == []


def test_a_working_order_with_no_lifecycle_row_of_its_own_is_one_finding(tmp_path):
    """The symbol has lifecycle history, but none for this order id: still a mismatch, named by order."""
    life = [_life(*h) for h in HISTORY]
    slk = [_slk(*WORKING)]
    rep = _check(tmp_path, life, slk)
    assert codes(rep) == ["NT_STOP_CROSS_CHECK"]
    assert "stop_lifecycle has no row" in rep["findings"][0]["detail"]
    assert "zq-0004" in rep["findings"][0]["detail"]


def test_rows_without_an_order_id_keep_the_symbol_level_check(tmp_path):
    """Legacy rows (no order_id on either side) are still graded: clean when they agree, a finding when not."""
    base = {"account": ACCT, "symbol": SYM, "stop_price": 80.0, "qty": 100}
    life = [dict(base, lifecycle="working", status="working", snapshot_at=STOP_AS_OF)]
    slk = [dict(base, status="working", captured_at=STOP_AS_OF)]
    assert _check(tmp_path, life, slk)["findings"] == []
    assert codes(_check(tmp_path, [dict(life[0], lifecycle="cancelled")], slk)) == ["NT_STOP_CROSS_CHECK"]
