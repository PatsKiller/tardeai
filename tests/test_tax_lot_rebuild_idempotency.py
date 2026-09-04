#!/usr/bin/env python3
"""Rebuilding tax lots twice must not produce twice the lots.

The defect this pins: build_tax_lots() seeded itself with the PREVIOUS run's output and
then replayed the whole transaction history on top, appending a new lot for every buy.
Run N held N copies. tax_lots.json reached 98% duplicates -- 12,870 of 13,139 rows --
with AMD:schwab_taxable holding 113 identical lots, one per run.

Nothing detected it for a long time because the duplicates were mostly CLOSED lots with
zero shares remaining, so every quantity check still reconciled against the broker. The
store was wrong in a way that no total could reveal.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "scripts"))

from portfolio_tax import build_tax_lots  # noqa: E402

TXNS = [
    {
        "symbol": "AMD",
        "account": "schwab_taxable",
        "txn_type": "buy",
        "quantity": 100,
        "price": 160.63,
        "date": "2025-09-30",
    },
    {
        "symbol": "AMD",
        "account": "schwab_taxable",
        "txn_type": "buy",
        "quantity": 50,
        "price": 170.00,
        "date": "2025-10-15",
    },
    {
        "symbol": "NVDA",
        "account": "schwab_roth",
        "txn_type": "buy",
        "quantity": 10,
        "price": 900.0,
        "date": "2025-11-01",
    },
]


def _count(lots):
    return {k: len(v) for k, v in lots.items()}


class TestRebuildIsIdempotent:
    def test_a_second_rebuild_does_not_duplicate(self):
        first = build_tax_lots(TXNS)
        second = build_tax_lots(TXNS, existing_lots=first)
        assert _count(second) == _count(first), f"rebuild duplicated lots: {_count(first)} -> {_count(second)}"

    def test_ten_rebuilds_stay_flat(self):
        """The defect grew linearly, so one repeat could look like rounding."""
        lots = build_tax_lots(TXNS)
        baseline = _count(lots)
        for _ in range(10):
            lots = build_tax_lots(TXNS, existing_lots=lots)
        assert _count(lots) == baseline, f"grew over 10 rebuilds: {baseline} -> {_count(lots)}"

    def test_the_lots_are_identical_not_merely_equal_in_count(self):
        first = build_tax_lots(TXNS)
        second = build_tax_lots(TXNS, existing_lots=first)
        assert second == first


class TestKeysWithoutTransactionsSurvive:
    """Dropping the seed entirely would lose lots the transactions cannot reproduce."""

    def test_a_key_with_no_transactions_is_carried_forward(self):
        imported = {
            "LEGACY:fidelity_rollover_ira": [
                {
                    "symbol": "LEGACY",
                    "account": "fidelity_rollover_ira",
                    "lot_date": "2019-01-02",
                    "shares": 500.0,
                    "shares_remaining": 500.0,
                    "cost_per_share": 12.0,
                    "total_cost": 6000.0,
                    "action": "buy",
                    "closed": False,
                }
            ]
        }
        out = build_tax_lots(TXNS, existing_lots=imported)
        assert "LEGACY:fidelity_rollover_ira" in out
        assert out["LEGACY:fidelity_rollover_ira"] == imported["LEGACY:fidelity_rollover_ira"]

    def test_a_key_with_transactions_is_rebuilt_not_appended(self):
        stale = {
            "AMD:schwab_taxable": [
                {
                    "symbol": "AMD",
                    "account": "schwab_taxable",
                    "lot_date": "1999-01-01",
                    "shares": 1.0,
                    "shares_remaining": 1.0,
                    "cost_per_share": 1.0,
                    "total_cost": 1.0,
                    "action": "buy",
                    "closed": False,
                }
            ]
        }
        out = build_tax_lots(TXNS, existing_lots=stale)
        dates = {lot["lot_date"] for lot in out["AMD:schwab_taxable"]}
        assert "1999-01-01" not in dates, "a key the transactions cover must be rebuilt from them"
        assert len(out["AMD:schwab_taxable"]) == 2

    def test_a_sell_only_key_is_still_covered(self):
        """A key whose only transaction is a sell is still transaction-covered."""
        txns = TXNS + [
            {
                "symbol": "OLD",
                "account": "schwab_taxable",
                "txn_type": "sell",
                "quantity": 5,
                "price": 10.0,
                "date": "2025-12-01",
            }
        ]
        stale = {
            "OLD:schwab_taxable": [
                {
                    "symbol": "OLD",
                    "account": "schwab_taxable",
                    "lot_date": "1999-01-01",
                    "shares": 5.0,
                    "shares_remaining": 5.0,
                    "cost_per_share": 1.0,
                    "total_cost": 5.0,
                    "action": "buy",
                    "closed": False,
                }
            ]
        }
        out = build_tax_lots(txns, existing_lots=stale)
        assert not any(lot["lot_date"] == "1999-01-01" for lot in out.get("OLD:schwab_taxable", []))
