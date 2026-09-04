#!/usr/bin/env python3
"""Closing lots for exited positions: the eligibility rule IS the safety mechanism.

Phase A left 1,800 duplicate open lots alone because deduplicating them would have
chosen an unverified share count. Asking the transaction history gave a different answer
again: the positions were fully exited, so both the stored total (ARKQ 11,300) and the
deduplicated one (100) were wrong and the truth was zero.

That only holds when two independent authorities agree. Every test here is about the
cases where they do not.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "scripts"))

from close_exited_tax_lots import (  # noqa: E402
    SHARES_IN,
    SHARES_NEUTRAL,
    SHARES_OUT,
    assess,
    close_lots,
    is_open,
    open_total,
    position_index,
    verify_invariants,
)

OPEN_LOT = {
    "symbol": "ARKQ",
    "account": "schwab_taxable",
    "lot_date": "2026-01-15",
    "shares": 100.0,
    "shares_remaining": 100.0,
    "cost_per_share": 132.73,
    "total_cost": 13273.0,
    "action": "buy",
    "closed": False,
}
ACCEPTED = {"schwab_taxable"}
EXITED = {
    ("ARKQ", "schwab_taxable"): [
        {"action": "Buy", "qty": 100.0, "date": "2026-01-15"},
        {"action": "Sell", "qty": 100.0, "date": "2026-07-13"},
    ]
}


class TestEligibility:
    def test_both_authorities_agreeing_is_eligible(self):
        a = assess("ARKQ:schwab_taxable", [dict(OPEN_LOT)], EXITED, {}, ACCEPTED)
        assert a["eligible"] and a["transaction_net"] == 0.0

    def test_a_still_held_position_is_never_eligible(self):
        a = assess("ARKQ:schwab_taxable", [dict(OPEN_LOT)], EXITED, {("ARKQ", "schwab_taxable"): 100.0}, ACCEPTED)
        assert not a["eligible"]
        assert any("still holds" in r for r in a["ineligible_reasons"])

    def test_a_nonzero_transaction_net_is_never_eligible(self):
        txns = {("ARKQ", "schwab_taxable"): [{"action": "Buy", "qty": 100.0, "date": "x"}]}
        a = assess("ARKQ:schwab_taxable", [dict(OPEN_LOT)], txns, {}, ACCEPTED)
        assert not a["eligible"]
        assert any("nets to" in r for r in a["ineligible_reasons"])

    def test_no_transaction_history_is_never_eligible(self):
        """Silence is not evidence of an exit."""
        a = assess("ARKQ:schwab_taxable", [dict(OPEN_LOT)], {}, {}, ACCEPTED)
        assert not a["eligible"]
        assert any("no transaction history" in r for r in a["ineligible_reasons"])

    def test_an_unreadable_account_is_never_eligible(self):
        """An account we could not read is not an account holding nothing."""
        a = assess("ARKQ:schwab_taxable", [dict(OPEN_LOT)], EXITED, {}, set())
        assert not a["eligible"]
        assert any("not read from the broker" in r for r in a["ineligible_reasons"])

    def test_an_unclassified_action_disqualifies(self):
        """A transaction type this tool does not understand must not score as zero."""
        txns = {
            ("ARKQ", "schwab_taxable"): [
                {"action": "Buy", "qty": 100.0, "date": "a"},
                {"action": "Sell", "qty": 100.0, "date": "b"},
                {"action": "Spin-Off Distribution", "qty": 7.0, "date": "c"},
            ]
        }
        a = assess("ARKQ:schwab_taxable", [dict(OPEN_LOT)], txns, {}, ACCEPTED)
        assert not a["eligible"]
        assert a["unclassified_actions"] == ["Spin-Off Distribution"]

    def test_a_transfer_in_is_not_a_sale(self):
        """The first pass scored a Transfer In as an outflow and reported FCNTX at -7,708."""
        assert "transfer in" in SHARES_IN and "transfer in" not in SHARES_OUT
        assert "security transfer" in SHARES_IN

    def test_the_three_action_sets_are_disjoint(self):
        assert not (SHARES_IN & SHARES_OUT)
        assert not (SHARES_IN & SHARES_NEUTRAL)
        assert not (SHARES_OUT & SHARES_NEUTRAL)

    def test_an_unaccepted_account_contributes_no_positions(self):
        snap = {"brokers": {"a": {"accepted": False, "positions": [{"symbol": "X", "qty": 5}]}}}
        assert position_index(snap) == {}


class TestClosure:
    def test_closing_preserves_everything_that_carries_tax_meaning(self):
        out, n = close_lots([dict(OPEN_LOT)])
        assert n == 1
        lot = out[0]
        for f in ("symbol", "account", "lot_date", "shares", "cost_per_share", "total_cost"):
            assert lot[f] == OPEN_LOT[f], f
        assert lot["shares_remaining"] == 0 and lot["closed"] is True
        assert lot["closed_reason"] == "POSITION_EXITED_PER_BROKER_AND_TRANSACTIONS"

    def test_no_lot_is_removed_or_added(self):
        lots = [dict(OPEN_LOT), dict(OPEN_LOT, closed=True, shares_remaining=0)]
        out, _ = close_lots(lots)
        assert len(out) == len(lots)

    def test_already_closed_lots_are_untouched(self):
        closed = dict(OPEN_LOT, closed=True, shares_remaining=0)
        out, n = close_lots([closed])
        assert n == 0 and out[0] == closed

    def test_open_total_becomes_zero(self):
        out, _ = close_lots([dict(OPEN_LOT)] * 113)
        assert open_total(out) == 0.0

    def test_is_open_requires_remaining_shares(self):
        assert is_open(OPEN_LOT)
        assert not is_open(dict(OPEN_LOT, shares_remaining=0))
        assert not is_open(dict(OPEN_LOT, closed=True))


class TestInvariants:
    def test_touching_an_ineligible_record_is_caught(self):
        before = {"A:a": [dict(OPEN_LOT)], "B:b": [dict(OPEN_LOT)]}
        after = {"A:a": [dict(OPEN_LOT)], "B:b": close_lots([dict(OPEN_LOT)])[0]}
        v = verify_invariants(before, after, eligible={"A:a"})
        assert not v["ok"] and any("INELIGIBLE" in p for p in v["problems"])

    def test_a_changed_cost_basis_is_caught(self):
        before = {"A:a": [dict(OPEN_LOT)]}
        after = {"A:a": [dict(OPEN_LOT, shares_remaining=0, closed=True, cost_per_share=1.0)]}
        v = verify_invariants(before, after, eligible={"A:a"})
        assert not v["ok"] and any("cost_per_share changed" in p for p in v["problems"])

    def test_a_removed_lot_is_caught(self):
        v = verify_invariants({"A:a": [dict(OPEN_LOT), dict(OPEN_LOT)]}, {"A:a": [dict(OPEN_LOT)]}, eligible={"A:a"})
        assert not v["ok"] and any("lot count changed" in p for p in v["problems"])

    def test_a_correct_closure_passes(self):
        before = {"A:a": [dict(OPEN_LOT)] * 5, "B:b": [dict(OPEN_LOT)]}
        after = {"A:a": close_lots([dict(OPEN_LOT)] * 5)[0], "B:b": [dict(OPEN_LOT)]}
        assert verify_invariants(before, after, eligible={"A:a"})["ok"]
