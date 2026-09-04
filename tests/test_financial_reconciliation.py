#!/usr/bin/env python3
"""Reconciliation must decide from authority, and refuse when authority is silent.

The failure this suite exists to prevent is subtle and expensive: a reconciler that
looks rigorous but is really just picking the newer file. Every test here either proves
a verdict came from the broker, or proves the reconciler declined to invent one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "scripts"))

from lib.financial_reconciliation import (  # noqa: E402
    AUTO_MIGRATABLE,
    BROKER_VERIFIED,
    DERIVED_REBUILT,
    DISPOSITIONS,
    STALE_SUPERSEDED_WITH_PROOF,
    SYNTHETIC_ADVISORY_ONLY,
    UNRESOLVED_OPERATOR_REVIEW,
    BrokerAuthority,
    classify_synthetic_lots,
    is_envelope_key,
    open_lot_total,
    qty_matches,
    reconcile_missing_side_record,
    reconcile_missing_stop_record,
    reconcile_stop_record,
    reconcile_tax_lot_record,
)


def _auth(positions=None, orders=None, accepted=True, account="schwab_taxable"):
    return BrokerAuthority(
        {
            "captured_at_utc": "2026-09-03T22:00:00+00:00",
            "snapshot_sha256": "z" * 64,
            "brokers": {
                account: {
                    "accepted": accepted,
                    "positions_status": "OK" if accepted else "ERROR timeout",
                    "orders_status": "OK",
                    "positions": positions or [],
                    "orders": orders or [],
                }
            },
        }
    )


class TestAuthorityIndex:
    def test_an_unreadable_account_is_refused_not_treated_as_empty(self):
        auth = _auth(accepted=False)
        assert not auth.has_account("schwab_taxable")
        assert "schwab_taxable" in auth.rejected_accounts

    def test_positions_are_keyed_by_account_not_symbol_alone(self):
        auth = _auth(positions=[{"symbol": "SCHD", "qty": 10}], account="schwab_taxable")
        assert auth.position_qty("SCHD", "schwab_taxable") == 10
        assert auth.position_qty("SCHD", "schwab_rollover_ira") is None, (
            "one account's position must never answer for another"
        )

    def test_a_buy_order_is_not_protection(self):
        auth = _auth(
            orders=[
                {
                    "id": "1",
                    "symbol": "X",
                    "side": "buy",
                    "type": "stop",
                    "status": "pending_activation",
                    "stop_price": "1",
                }
            ]
        )
        assert auth.live_protective_orders("X", "schwab_taxable") == []

    def test_a_terminal_order_is_not_protection(self):
        auth = _auth(
            orders=[{"id": "1", "symbol": "X", "side": "sell", "type": "stop", "status": "canceled", "stop_price": "1"}]
        )
        assert auth.live_protective_orders("X", "schwab_taxable") == []


class TestStops:
    def test_the_broker_price_decides_even_when_it_is_the_older_file(self):
        """The decisive case: the served copy wins because the broker says so."""
        orders = [
            {
                "id": "99",
                "symbol": "DIV",
                "side": "sell",
                "type": "stop",
                "status": "awaiting_stop_condition",
                "stop_price": "19.24",
                "qty": "411.0",
            }
        ]
        v = reconcile_stop_record(
            "DIV:schwab_taxable",
            {"broker_order_id": "99", "stop": 19.13, "synced_at": "2026-09-03T00:00:00Z"},
            {"broker_order_id": "99", "stop": 19.24, "synced_at": "2026-08-05T00:00:00Z"},
            _auth(orders=orders),
        )
        assert v["disposition"] == BROKER_VERIFIED
        assert v["canonical_side"] == "served", "the older file won because the broker agrees with it"

    def test_a_price_matching_neither_copy_is_unresolved(self):
        orders = [
            {
                "id": "99",
                "symbol": "DIV",
                "side": "sell",
                "type": "stop",
                "status": "awaiting_stop_condition",
                "stop_price": "20.00",
                "qty": "411.0",
            }
        ]
        v = reconcile_stop_record(
            "DIV:schwab_taxable",
            {"broker_order_id": "99", "stop": 19.13},
            {"broker_order_id": "99", "stop": 19.24},
            _auth(orders=orders),
        )
        assert v["disposition"] == UNRESOLVED_OPERATOR_REVIEW
        assert v["canonical_value"] is None

    def test_an_order_absent_from_the_broker_is_advisory_only(self):
        v = reconcile_stop_record(
            "X:schwab_taxable",
            {"broker_order_id": "404", "stop": 1.0},
            {"broker_order_id": "404", "stop": 2.0},
            _auth(),
        )
        assert v["disposition"] == SYNTHETIC_ADVISORY_ONLY

    def test_a_one_sided_stop_matching_a_live_order_is_broker_verified(self):
        orders = [
            {
                "id": "7",
                "symbol": "ARKX",
                "side": "sell",
                "type": "stop",
                "status": "pending_activation",
                "stop_price": "31.3",
                "qty": "1000.0",
            }
        ]
        v = reconcile_missing_stop_record(
            "ARKX:schwab_taxable",
            {"broker_order_id": "7", "stop": 31.3, "qty": 1000.0},
            "producer",
            _auth(orders=orders),
        )
        assert v["disposition"] == BROKER_VERIFIED and v["canonical_side"] == "producer"

    def test_a_one_sided_stop_whose_order_is_terminal_is_superseded(self):
        orders = [
            {
                "id": "7",
                "symbol": "ARKX",
                "side": "sell",
                "type": "stop",
                "status": "canceled",
                "stop_price": "31.3",
                "qty": "1000.0",
            }
        ]
        v = reconcile_missing_stop_record(
            "ARKX:schwab_taxable",
            {"broker_order_id": "7", "stop": 31.3, "qty": 1000.0},
            "producer",
            _auth(orders=orders),
        )
        assert v["disposition"] == STALE_SUPERSEDED_WITH_PROOF

    def test_a_stop_is_never_routed_through_lot_arithmetic(self):
        """The defect this fixed: a stop has no lots, so lot totals said 'unresolved'."""
        orders = [
            {
                "id": "7",
                "symbol": "V",
                "side": "sell",
                "type": "stop",
                "status": "pending_activation",
                "stop_price": "366.73",
                "qty": "201.0",
            }
        ]
        auth = _auth(positions=[{"symbol": "V", "qty": 201.7963}], orders=orders)
        good = reconcile_missing_stop_record(
            "V:schwab_taxable", {"broker_order_id": "7", "stop": 366.73, "qty": 201.0}, "producer", auth
        )
        bad = reconcile_missing_side_record(
            "stops.json", "V:schwab_taxable", {"broker_order_id": "7", "stop": 366.73, "qty": 201.0}, "producer", auth
        )
        assert good["disposition"] == BROKER_VERIFIED
        assert bad["disposition"] == UNRESOLVED_OPERATOR_REVIEW, (
            "the lot path cannot answer a stop question -- which is why stops must not use it"
        )


class TestTaxLots:
    def test_the_copy_that_reconciles_to_the_position_wins(self):
        auth = _auth(positions=[{"symbol": "SCHD", "qty": 10000.2508}])
        v = reconcile_tax_lot_record(
            "SCHD:schwab_taxable",
            [{"shares_remaining": 10000.2514}],
            [{"shares_remaining": 5000.2514}],
            auth,
        )
        assert v["disposition"] == BROKER_VERIFIED and v["canonical_side"] == "producer"

    def test_both_reconciling_with_different_lots_is_unresolved(self):
        auth = _auth(positions=[{"symbol": "SCHD", "qty": 100.0}])
        v = reconcile_tax_lot_record(
            "SCHD:schwab_taxable",
            [{"shares_remaining": 60.0}, {"shares_remaining": 40.0}],
            [{"shares_remaining": 100.0}],
            auth,
        )
        assert v["disposition"] == UNRESOLVED_OPERATOR_REVIEW
        assert v["canonical_value"] is None, "cost basis must never be guessed"

    def test_neither_reconciling_is_unresolved(self):
        auth = _auth(positions=[{"symbol": "SCHD", "qty": 100.0}])
        v = reconcile_tax_lot_record(
            "SCHD:schwab_taxable", [{"shares_remaining": 1.0}], [{"shares_remaining": 2.0}], auth
        )
        assert v["disposition"] == UNRESOLVED_OPERATOR_REVIEW

    def test_a_one_sided_record_for_a_real_position_is_kept(self):
        """Dropping this record would have discarded lots for a position actually held."""
        auth = _auth(positions=[{"symbol": "SRNE", "qty": 1000.0}])
        v = reconcile_missing_side_record(
            "tax_lots.json", "SRNE:schwab_taxable", [{"shares_remaining": 1000.0}], "served", auth
        )
        assert v["disposition"] == BROKER_VERIFIED and v["canonical_side"] == "served"

    def test_a_one_sided_record_for_a_position_no_longer_held_is_superseded(self):
        v = reconcile_missing_side_record(
            "tax_lots.json", "GONE:schwab_taxable", [{"shares_remaining": 5.0}], "served", _auth()
        )
        assert v["disposition"] == STALE_SUPERSEDED_WITH_PROOF

    def test_closed_lots_do_not_count_toward_the_total(self):
        assert open_lot_total([{"shares_remaining": 5, "closed": True}, {"shares_remaining": 3}]) == 3

    def test_synthetic_lots_are_named_and_never_promoted(self):
        rows = classify_synthetic_lots(
            [
                {"source": "trade_transactions_reconstructed", "cost_per_share": 1.0},
                {"source": "", "cost_per_share": None},
            ]
        )
        assert rows[0]["synthetic_kind"] == "GOVERNED_ESTIMATE"
        assert rows[1]["synthetic_kind"] == "PLACEHOLDER"
        assert rows[1]["basis_state"] == "BASIS_UNVERIFIED", "unproven basis is never zero"

    def test_an_unreadable_account_blocks_the_verdict(self):
        v = reconcile_tax_lot_record(
            "SCHD:schwab_taxable", [{"shares_remaining": 1}], [{"shares_remaining": 2}], _auth(accepted=False)
        )
        assert v["disposition"] == UNRESOLVED_OPERATOR_REVIEW


class TestContract:
    def test_every_disposition_is_one_of_the_seven(self):
        assert len(DISPOSITIONS) == 7

    def test_unresolved_is_never_auto_migratable(self):
        assert UNRESOLVED_OPERATOR_REVIEW not in AUTO_MIGRATABLE
        assert SYNTHETIC_ADVISORY_ONLY not in AUTO_MIGRATABLE, (
            "an advisory record is not broker truth and must not migrate unattended"
        )
        assert BROKER_VERIFIED in AUTO_MIGRATABLE and DERIVED_REBUILT in AUTO_MIGRATABLE

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("_agent_metadata", True),
            ("_freshness_note", True),
            ("generated_at", True),
            ("SCHD:schwab_taxable", False),
            ("DIV", False),
        ],
    )
    def test_envelope_keys_are_recognised(self, key, expected):
        assert is_envelope_key(key) is expected

    def test_quantity_tolerance_scales_with_size(self):
        assert qty_matches(10000.2514, 10000.2508)
        assert not qty_matches(5000.2514, 10000.2508)
        assert qty_matches(0.0001, 0.0001)
        assert not qty_matches(1.0, 2.0)
