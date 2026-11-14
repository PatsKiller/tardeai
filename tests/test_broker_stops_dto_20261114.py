"""S2 broker — the canonical DTO carries the stop read receipt and the planned facet (PR-003/PR-017).

These pin the two facts the pages were missing, at the layer the route serves:

* ``holdings_payload`` publishes ``stops_read`` — when the broker stop read happened, so a NO STOP row
  is a *negative observation* and not an absence of evidence;
* ``stop_for`` publishes ``planned: {level, source, as_of}`` as its own facet, so a planned level
  (dated when it was set) never borrows an observed read's clock nor counts as protection.

Fixtures are synthetic (the repo is public).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import cio_truth  # noqa: E402

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
READ_AT = "2026-11-14T14:58:10Z"


def _stops(**over):
    s = {"rows": [], "active_count": 1, "pending_count": 0, "unprotected_count": 1, "awaiting_fill_count": 0,
         "last_broker_read_at": READ_AT, "last_broker_read_label": "14:58 ET", "as_of": READ_AT,
         "age_hours": 0.4, "stale": False, "stale_after_hours": 0.5, "partial_observation_as_of": None,
         "gap": None}
    s.update(over)
    return s


def _doc(stops=None, stop_rows=None):
    return {
        "stops": _stops(rows=list(stop_rows or []), **{}) if stops is None else stops,
        "portfolio": {
            "holdings": [
                {"account_id": "acct-a", "symbol": "AAA", "shares": 10, "price": 10.0, "market_value": 100.0,
                 "cost_basis_broker": 90.0, "is_cash": False},
                {"account_id": "acct-a", "symbol": "CASH", "is_cash": True, "market_value": 50.0},
            ],
            "total_usd": 150.0, "cash_usd": 50.0, "position_count": 1,
            "position_counts": {"position_count": 1, "held_count": 1, "below_100": 0, "unpriced": 0,
                                "counted": 1, "min_position_usd": 100, "source": "positions_current"},
            "positions_as_of": "2026-11-14T14:41:02Z", "valuation_as_of": "2026-11-14T14:45:00Z",
            "quote_as_of": READ_AT, "clock_provenance": None,
            "source": "broker_positions_store", "as_of": "2026-11-14T14:41:02Z", "stale": False, "gap": None,
        },
        "measures": {"measures": {
                         "account_value": {"measure": "account_value", "value": 150.0, "status": "MEASURED",
                                           "as_of": "2026-11-14T14:45:00Z"},
                         "price_move_estimate": {"measure": "price_move_estimate", "value": -1.0,
                                                 "status": "MEASURED", "coverage": {"measured_rows": 1,
                                                                                    "unknown_rows": 0,
                                                                                    "row_count": 1}},
                         "account_value_change_1d": {"measure": "account_value_change_1d", "value": -1.0,
                                                     "status": "MEASURED"},
                         "verified_daily_pnl": {"measure": "verified_daily_pnl", "status": "UNKNOWN",
                                                "value": None}},
                     "materialized_at": "2026-11-14T14:45:00Z", "reconciliation": None,
                     "source_coverage": {}},
    }


def test_the_holdings_payload_carries_the_stop_read_receipt():
    """PR-003: the receipt travels with the rows; the payload's own keys are unchanged."""
    out = cio_truth.holdings_payload({}, document=_doc(), now=NOW)
    receipt = out["stops_read"]
    assert receipt["status"] == "READ"
    assert receipt["last_broker_read_at"] == READ_AT
    assert receipt["last_broker_read_label"] == "14:58 ET"
    assert receipt["counts"]["active_count"] == 1
    assert out["total_value"] == 150.0 and out["count"] == 2  # the rest of the payload is untouched


def test_an_unprotected_row_beside_a_read_is_a_negative_observation():
    """The row says no stop; the receipt says the broker was read. Both facts, one payload.

    A row with no recorded stop carries NO stop fields at all (only ``protection_state``), which is
    why the receipt has to be published beside the rows: without it, "no stop" and "no read" are the
    same shape on the wire.
    """
    out = cio_truth.holdings_payload({}, document=_doc(), now=NOW)
    row = next(r for r in out["holdings"] if r["symbol"] == "AAA")
    assert row.get("stop_source") is None and not row.get("broker_protected")
    assert "stop_captured_at" not in row                 # nothing per-row dates the stop read
    assert out["stops_read"]["status"] == "READ"         # the section's receipt carries that date
    assert row["protection_state"] in ("GAP", "UNKNOWN")  # and the row says no resting stop


def test_no_stop_read_is_unknown_and_never_reads_as_unprotected():
    """No recorded read ⇒ the receipt is UNKNOWN with a reason, and the counts stay None, not 0."""
    stops = _stops(rows=[], last_broker_read_at=None, last_broker_read_label=None, as_of=None,
                   age_hours=None, stale=True, active_count=None, unprotected_count=None,
                   gap={"reason": "No broker stop read is recorded for current holdings."})
    out = cio_truth.holdings_payload({}, document=_doc(stops=stops), now=NOW)
    receipt = out["stops_read"]
    assert receipt["status"] == "UNKNOWN"
    assert receipt["gap"]["reason"]
    assert receipt["counts"]["active_count"] is None


def test_a_partial_refresh_is_named_in_the_receipt():
    stops = _stops(last_broker_read_at=None, as_of=None, age_hours=None, stale=True,
                   partial_observation_as_of="2026-11-13T20:00:00Z")
    out = cio_truth.holdings_payload({}, document=_doc(stops=stops), now=NOW)
    assert out["stops_read"]["status"] == "PARTIAL"
    assert out["stops_read"]["as_of"] is None


def test_a_planned_level_is_its_own_facet_and_not_protection():
    """PR-017: level + the date it was SET, beside the evidence state; it never reads as a resting stop."""
    row = cio_truth.stop_for("acct-a", "AAA", planned={"AAA:acct-a": {"stop_price": 8.0, "set_date": "2026-11-12"}},
                             now=NOW)
    assert row["stop_source"] == "planned"
    assert row["stop_price"] == 8.0
    assert row["planned"] == {"level": 8.0, "source": "stops.json", "as_of": "2026-11-12"}
    assert row["broker_protected"] is False
    assert row["stop_observation"] is None  # a planned level is not an observation


def test_a_broker_resting_stop_carries_no_planned_facet():
    broker_rows = [{"account": "acct-a", "symbol": "AAA", "order_id": "o-1", "status": "active",
                    "stop_price": 9.0, "captured_at": READ_AT, "qty": 10, "order_type": "STOP"}]
    row = cio_truth.stop_for("acct-a", "AAA", broker_rows=broker_rows, now=NOW)
    assert row["stop_source"] == "broker_resting"
    assert row["planned"] is None
