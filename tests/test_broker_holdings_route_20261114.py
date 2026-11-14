"""Route-level: /api/v2/portfolio/holdings serves the shared broker evidence block (b3).

Red before the wiring hunk, green after: this file ships WITH the ``scripts/api_v2.py`` change, so it
fails on a tree where the route still returns the bare payload. It pins the two things the page and
the integrator depend on — the payload is preserved byte-for-byte in its own keys, and the evidence
block is present with a snapshot id — and that the route's own read path is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402

ROUTE = "/api/v2/portfolio/holdings"


def _payload():
    return {
        "holdings": [{"account_id": "acct-a", "symbol": "AAA", "price": 10.0, "qty": 100,
                      "market_value": 1000.0}],
        "count": 1,
        "position_count": 1,
        "total_value": 1000.0,
        "total_cash": 0.0,
        "today_change": -3.0,
        "today_change_status": "MEASURED",
        "positions_as_of": "2026-11-14T14:41:02Z",
        "valuation_as_of": "2026-11-14T14:45:00Z",
        "quote_as_of": "2026-11-14T14:58:10Z",
        "position_counts": {"position_count": 1, "held_count": 1, "below_100": 0, "unpriced": 0,
                            "counted": 1, "min_position_usd": 100, "source": "positions_current"},
        "measures": {"materialized_at": "2026-11-14T14:45:00Z",
                     "measures": {"account_value": {"measure": "account_value", "value": 1000.0,
                                                    "status": "MEASURED", "as_of": "2026-11-14T14:45:00Z"},
                                  "price_move_estimate": {"measure": "price_move_estimate", "value": -3.0,
                                                          "status": "MEASURED",
                                                          "coverage": {"measured_rows": 1, "unknown_rows": 0,
                                                                       "row_count": 1}},
                                  "account_value_change_1d": {"measure": "account_value_change_1d",
                                                              "value": -3.0, "status": "MEASURED"},
                                  "verified_daily_pnl": {"measure": "verified_daily_pnl",
                                                         "status": "UNKNOWN", "value": None}},
                     "source_coverage": {}},
        "measures_materialized_at": "2026-11-14T14:45:00Z",
        "truth": {"source": "broker_positions_store", "as_of": "2026-11-14T14:41:02Z",
                  "stale": False, "gap": None},
    }


class _Readers:
    """Stands in for lib.cio_truth: the route must call holdings_payload and nothing else."""

    calls: list = []

    @classmethod
    def holdings_payload(cls, payload, *, db_query=None):
        cls.calls.append(db_query)   # the route's own read argument, recorded
        return _payload()


def test_the_holdings_route_serves_one_evidence_block(monkeypatch):
    _Readers.calls = []
    monkeypatch.setattr(api_v2, "_cio_truth_readers", lambda: _Readers)
    out = api_v2.ROUTES[ROUTE]()
    assert set(out["evidence"]) == {"portfolio", "positions"}
    assert out["evidence"]["portfolio"]["snapshot_id"]
    assert out["evidence"]["portfolio"]["clocks"]["source_as_of"] == "2026-11-14T14:41:02Z"
    assert out["evidence"]["positions"]["value"]["position_count"] == 1
    assert out["evidence"]["positions"]["completeness"]["counted"] == 1
    assert out["evidence"]["positions"]["completeness"]["total"] == 1
    assert _Readers.calls == [api_v2._db_query]  # the route's own read, exactly once, unchanged


def test_the_route_does_not_recompute_or_reshape_the_payload(monkeypatch):
    """Every key the route published before is still there, with the same value."""
    monkeypatch.setattr(api_v2, "_cio_truth_readers", lambda: _Readers)
    payload = _payload()
    out = api_v2.ROUTES[ROUTE]()
    for key, value in payload.items():
        assert out[key] == value, key
    assert out["holdings"] == payload["holdings"]


def test_a_missing_measures_block_renders_unknown_not_ok(monkeypatch):
    """The route's missing-data state: no measures ⇒ UNKNOWN with a named cause, payload still served."""
    class Bare(_Readers):
        @classmethod
        def holdings_payload(cls, payload, *, db_query=None):
            p = _payload()
            p.pop("measures")
            return p

    monkeypatch.setattr(api_v2, "_cio_truth_readers", lambda: Bare)
    out = api_v2.ROUTES[ROUTE]()
    assert out["evidence"]["portfolio"]["verdict"] == "UNKNOWN"
    assert out["evidence"]["portfolio"]["cause"]["code"] == "MEASURES_ABSENT"
    assert out["total_value"] == 1000.0
