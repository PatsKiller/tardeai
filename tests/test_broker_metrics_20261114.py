"""S2 broker — one metric ID per figure (HQ-07) and a row census that adds up (PR-002).

These tests pin the two properties a page and a CSV export need in order to agree without either of them
doing arithmetic: every figure it cites carries a ``metric_id`` plus the ``snapshot_id`` it came from, and
every population it quotes is the payload's own count contract lifted verbatim — a fact the payload does not
publish is ``None`` with a named reason, never a zero.

Every fixture here is synthetic (``acct-a``, round dollars). Nothing reads the live book.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.broker_metrics import MEASURE_IDS, metrics, scope_coverage  # noqa: E402

SNAP = "snap_0123456789abcdef"


def _measure(**over):
    m = {"label": "Synthetic label", "definition": "Synthetic definition", "basis": "store",
         "value": 1000000.0, "status": "MEASURED", "as_of": "2026-11-14T14:41:02Z"}
    m.update(over)
    return m


def _payload(**over):
    p = {
        "session_id": "2026-11-14-regular",
        "positions_as_of": "2026-11-14T14:41:02Z",
        "measures_materialized_at": "2026-11-14T14:41:30Z",
        "holdings": [
            {"account_id": "acct-a", "symbol": "AAA", "market_value": 600000.0},
            {"account_id": "acct-a", "symbol": "BBB", "market_value": 300000.0},
            {"account_id": "acct-b", "symbol": "CCC", "market_value": 100000.0},
        ],
        "measures": {
            "session": "2026-11-14-regular",
            "basis": {"applied": "store", "why": "broker-reported values are the anchor"},
            "measures": {
                "account_value": _measure(),
                "price_move_estimate": _measure(value=-234.56, status="MEASURED", coverage={
                    "measured_rows": 3, "unknown_rows": 0, "row_count": 3, "unknown": []}),
                "account_value_change_1d": _measure(value=-234.56, status="MEASURED"),
                "verified_daily_pnl": _measure(value=None, status="UNKNOWN", as_of=None, source=None),
            },
            "reconciliation": {
                "contract_version": "pnl-reconciliation@1",
                "total": {
                    "status": "RECONCILED",
                    "accounts_reconciled": 2, "accounts_total": 2,
                    "residual": {"value_usd": -120.0, "known_components_residual_usd": -64.1,
                                 "tolerance_usd": 3.0, "provisional": False, "unknown_components": [],
                                 "within_tolerance": True, "policy": "signed per-account"},
                },
            },
        },
        "position_counts": {
            "position_count": 3, "held_count": 5, "below_100": 2, "counted": 3, "unpriced": 1,
            "min_position_usd": 100, "source": "positions_current", "as_of": "2026-11-14T14:41:02Z",
            "as_of_basis": "store",
            "scopes": {"holdings.all_rows": 8, "holdings.cash": 2, "holdings.non_cash": 6,
                       "holdings.held": 5, "holdings.held_under_100": 2, "holdings.unpriced": 1,
                       "holdings.non_cash_over_100": 3},
            "findings": [],
            "agree": False,  # cross-scope by construction: 3 counted vs 5 held. Never a defect.
        },
        "source_coverage": {"positions_current": "read", "quote_price": "read"},
    }
    p.update(over)
    return p


# --- HQ-07: one metric ID per figure -------------------------------------------------------------


def test_every_published_measure_gets_one_row_with_a_stable_id_and_the_snapshot():
    rows = metrics(_payload(), snapshot_id=SNAP)
    assert [r["metric_id"] for r in rows] == [f"portfolio.{n}" for n in MEASURE_IDS]
    for r in rows:
        assert r["snapshot_id"] == SNAP
        assert r["scope"]["accounts"] == ["acct-a", "acct-b"]
        assert r["scope"]["session_id"] == "2026-11-14-regular"
        assert r["period"]["session"] == "2026-11-14-regular"
        assert r["period"]["market_day"] == "2026-11-14T14:41:30Z"
        assert r["basis"] == "store"
    assert rows[0]["value_cents"] == 100000000      # $1,000,000.00
    assert rows[1]["value_cents"] == -23456         # −$234.56, exact via Decimal not float
    assert rows[0]["label"] == "Synthetic label" and rows[0]["definition"] == "Synthetic definition"


def test_a_measure_the_payload_does_not_publish_is_listed_unknown_not_dropped():
    """A page filtering on status == OK must still see the absent measure, with the reason."""
    p = _payload()
    del p["measures"]
    rows = metrics(p, snapshot_id=SNAP)
    assert len(rows) == len(MEASURE_IDS)
    for r in rows:
        assert r["status"] == "UNKNOWN"
        assert r["value_cents"] is None
        assert r["cause"]["reason"] == f"the payload publishes no {r['measure']} measure"
        assert r["cause"]["owner"] and r["cause"]["next_action"]


def test_the_verified_label_survives_only_with_a_stored_receipt():
    """VERIFIED is a claim about a stored record; a status string with no value/source/as_of is not one."""
    p = _payload()
    p["measures"]["measures"]["verified_daily_pnl"] = _measure(
        value=-123.45, status="VERIFIED", source=None, as_of=None)
    row = metrics(p, snapshot_id=SNAP)[-1]
    assert row["verified"] is False and row["receipt"] is None

    p["measures"]["measures"]["verified_daily_pnl"] = _measure(
        value=-123.45, status="VERIFIED", source="stored_reconciliation", as_of="2026-11-14T14:41:02Z")
    row = metrics(p, snapshot_id=SNAP)[-1]
    assert row["verified"] is True
    assert row["receipt"] == {"source": "stored_reconciliation", "as_of": "2026-11-14T14:41:02Z"}


def test_the_pnl_bridge_is_the_stored_reconciliation_and_its_residual():
    """PR-007/HQ-07: the bridge is lifted from the stored record, in cents, on the P&L rows only."""
    rows = {r["measure"]: r for r in metrics(_payload(), snapshot_id=SNAP)}
    bridge = rows["account_value_change_1d"]["bridge"]
    assert bridge["residual_cents"] == -12000
    assert bridge["known_components_residual_cents"] == -6410
    assert bridge["tolerance_cents"] == 300
    assert bridge["reconciliation_status"] == "RECONCILED"
    assert bridge["accounts_reconciled"] == 2 and bridge["accounts_total"] == 2
    assert bridge["contract_version"] == "pnl-reconciliation@1"
    assert rows["account_value_change_1d"]["residual_cents"] == -12000
    assert rows["verified_daily_pnl"]["bridge"] == bridge
    assert rows["account_value"]["bridge"] is None
    assert rows["price_move_estimate"]["bridge"] is None


def test_no_stored_reconciliation_leaves_the_bridge_empty_and_never_a_zero():
    p = _payload()
    del p["measures"]["reconciliation"]
    rows = {r["measure"]: r for r in metrics(p, snapshot_id=SNAP)}
    for name in ("account_value_change_1d", "verified_daily_pnl"):
        assert rows[name]["bridge"] is None
        assert rows[name]["residual_cents"] is None


def test_a_coverage_gap_travels_with_the_metric_that_has_it():
    p = _payload()
    p["measures"]["measures"]["price_move_estimate"]["coverage"] = {
        "measured_rows": 2, "unknown_rows": 1, "row_count": 3, "unknown": ["CCC"]}
    row = {r["measure"]: r for r in metrics(p, snapshot_id=SNAP)}["price_move_estimate"]
    assert row["complete"] is False
    assert row["coverage_gap"]["rows"] == ["CCC"]
    assert "1 of 3" in row["coverage_gap"]["reason"]


def test_completeness_is_none_when_the_payload_publishes_no_coverage():
    row = {r["measure"]: r for r in metrics(_payload(), snapshot_id=SNAP)}["account_value"]
    assert row["complete"] is None


# --- PR-002: the row census ----------------------------------------------------------------------


def test_scope_coverage_lifts_the_count_contract_verbatim_and_never_reads_agree():
    cov = scope_coverage(_payload(), snapshot_id=SNAP)
    assert cov["snapshot_id"] == SNAP
    assert cov["scopes"] == _payload()["position_counts"]["scopes"]
    assert cov["counted"] == 3 and cov["held"] == 5
    assert cov["rows_read"] == 8 and cov["cash_rows"] == 2 and cov["non_cash_rows"] == 6
    assert cov["min_position_usd"] == 100
    assert cov["count_source"] == "positions_current" and cov["count_basis"] == "store"
    # agree compares different populations and is false by construction; it must not be lifted at all.
    assert "agree" not in cov


def test_every_excluded_population_carries_its_reason_and_its_count():
    cov = scope_coverage(_payload(), snapshot_id=SNAP)
    by_scope = {e["scope"]: e for e in cov["excluded"]}
    assert by_scope["holdings.held_under_100"]["count"] == 2
    assert "$100" in by_scope["holdings.held_under_100"]["reason"]
    assert by_scope["holdings.unpriced"]["count"] == 1
    assert "never a zero" in by_scope["holdings.unpriced"]["reason"]


def test_a_population_the_payload_does_not_publish_is_none_with_a_reason_not_zero():
    cov = scope_coverage(_payload(), snapshot_id=SNAP)
    assert cov["filtered_rows"] is None and cov["duplicate_rows"] is None
    assert set(cov["unpublished"]) == {"filtered_rows", "duplicate_rows"}
    assert all(cov["unpublished"].values())


def test_rendered_rows_counts_the_rows_the_payload_actually_hands_a_page():
    cov = scope_coverage(_payload(), snapshot_id=SNAP)
    assert cov["rendered_rows"] == 3
    p = _payload(holdings=None)
    assert scope_coverage(p, snapshot_id=SNAP)["rendered_rows"] is None


def test_price_move_row_coverage_travels_beside_the_census():
    cov = scope_coverage(_payload(), snapshot_id=SNAP)
    assert cov["priceable"]["measured_rows"] == 3
    assert cov["priceable"]["unknown_rows"] == 0
    assert cov["source_coverage"] == {"positions_current": "read", "quote_price": "read"}


def test_a_payload_with_no_count_contract_says_so_rather_than_counting_zero():
    p = _payload()
    del p["position_counts"]
    cov = scope_coverage(p, snapshot_id=SNAP)
    assert cov["counted"] is None and cov["held"] is None and cov["min_position_usd"] is None
    assert cov["scopes"] == {} and cov["findings"] == []
    assert cov["rendered_rows"] == 3  # this is the only number the module counts itself
