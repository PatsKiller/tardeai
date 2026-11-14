"""ANCHOR: STOP_COVERAGE_POPULATION_20261113 -- every held row is counted in exactly one coverage bucket.

Operator 2026-11-13 point 4: positions with a missing or zero market value are UNPRICED/UNVERIFIABLE,
not dust; an account with no stop rows is unobserved, not silently skipped; "0 gaps" must come with
total / eligible / covered / exclusions-by-reason. Synthetic data only; no DB, no broker.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import stop_coverage_incidents as sci  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
CFG = {"paper_accounts": ["paper_x"], "exclude_asset_types": ["MUTUAL_FUND"],
       "not_stop_protectable_labels": {"mutual_fund": "not stop-protectable (mutual fund)"},
       "min_position_value_usd": 1000.0, "exempt": [], "account_aliases": {}}


def _snap(sym, acct="live_a", lifecycle="working"):
    return {"account": acct, "symbol": sym, "lifecycle": lifecycle, "snapshot_at": NOW - timedelta(seconds=60)}


def _pos(sym, mv, acct="live_a", asset="EQUITY", qty=10):
    return {"account_key": acct, "symbol": sym, "qty": qty, "broker_market_value": mv,
            "as_of": NOW - timedelta(seconds=60), "asset_type": asset, "is_cash": False}


def _scan(snapshot, positions):
    return sci.scan_from_snapshot(snapshot, positions, now=NOW, session_open=True, cfg=CFG)


def test_every_row_is_in_exactly_one_bucket():
    snaps = [_snap("BIG"), _snap("OTHER", lifecycle="cancelled")]
    rows = [_pos("BIG", 5000.0), _pos("NAKED", 9000.0), _pos("DUST", 12.0), _pos("CUSIP1", 0.0, qty=3000),
            _pos("NOVAL", None), _pos("FUND", 5000.0, asset="MUTUAL_FUND"), _pos("NV", 21.0, acct="moomoo"),
            _pos("PP", 5000.0, acct="paper_x")]
    pop = _scan(snaps, rows)["population"]
    assert pop["total"] == 8
    # NOVAL (value missing) keeps the existing contract: it is checked, so uncovered it is a gap
    assert (pop["eligible"], pop["covered"], pop["uncovered"]) == (3, 1, 2)
    assert pop["exclusion_counts"] == {"below_value_floor": 1, "not_stop_protectable": 1, "paper_account": 1,
                                       "stop_source_unobserved": 1, "unpriced_unverifiable": 1}
    assert pop["eligible"] + sum(pop["exclusion_counts"].values()) == pop["total"]


def test_a_zero_market_value_is_unpriced_not_dust():
    pop = _scan([_snap("X")], [_pos("CUSIP1", 0.0, qty=3000)])["population"]
    assert "below_value_floor" not in pop["exclusion_counts"]
    assert pop["exclusions"]["unpriced_unverifiable"][0]["symbol"] == "CUSIP1"


def test_a_zero_valued_row_is_unknown_in_the_scan_never_a_gap_and_never_ok():
    scan = _scan([_snap("X")], [_pos("CUSIP1", 0.0, qty=3000)])
    rec = [s for s in scan["stops"] if s["symbol"] == "CUSIP1"][0]
    assert rec["health"] == "unknown" and "unpriced" in rec["flags"]
    p = sci.plan(scan, [])
    assert p["ok"] and p["gaps"] == []


def test_a_zero_valued_row_with_a_working_stop_is_covered():
    pop = _scan([_snap("CUSIP1")], [_pos("CUSIP1", 0.0)])["population"]
    assert (pop["eligible"], pop["covered"]) == (1, 1)


def test_an_account_without_stop_rows_is_listed_not_dropped():
    pop = _scan([_snap("A")], [_pos("A", 5000.0), _pos("NV", 5000.0, acct="moomoo")])["population"]
    # LQ-3047: an unobserved stop source is listed UNKNOWN with its reason, never silently dropped
    assert pop["exclusions"]["stop_source_unobserved"] == [
        {"account": "moomoo", "symbol": "NV", "state": "UNKNOWN", "why": "no stop snapshot row for this account"}]


def test_gap_detection_is_unchanged_for_priced_eligible_rows():
    scan = _scan([_snap("A")], [_pos("A", 5000.0), _pos("B", 5000.0)])
    alerts = [s["symbol"] for s in scan["stops"] if s["health"] == "alert"]
    assert alerts == ["B"]
