"""LQ-20261113-3068 (review REVIEW-LQ-20261113-3047-independent C1/C2/C3): edges of the one protection floor.

C1: a $0 or missing market value is its own UNKNOWN/unvalued class, never "under the floor".
C2: the floor is strict ($100.00 is counted), POSITIONS_SQL keeps cash rows (so they are listed), recompute_book never
    calls a $0 row below the floor, and an operator-exempt row is listed (every row in exactly one bucket).
C3: a held row with no symbol is a DEFECT row, listed, never silently dropped.
The floor value itself ($100 vs $1,000) is the operator's ruling; these tests read it from count_floor_usd().
Synthetic rows only: no DB, no broker.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import desk_truth_monitor as dtm  # noqa: E402
import stop_coverage_incidents as sci  # noqa: E402
from scripts.lib import protection_policy as pp  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
FLOOR = pp.count_floor_usd()
CFG = {"paper_accounts": ["paper_x"], "exclude_asset_types": ["MUTUAL_FUND"], "not_stop_protectable_labels": {},
       "exempt": [{"account": "live_a", "symbol": "OPEX"}], "account_aliases": {},
       "working_lifecycles": ["working", "near_trigger"], "snapshot_stale_after_h": 2.0,
       "accounts": ["live_a"], "working_stop_statuses": ["working"]}


def _pos(sym, mv, acct="live_a", qty=10, asset="EQUITY", is_cash=False):
    return {"account_key": acct, "symbol": sym, "qty": qty, "broker_market_value": mv, "asset_type": asset,
            "is_cash": is_cash, "as_of": NOW - timedelta(seconds=60)}


def _snap(sym="ANCHOR", acct="live_a", lifecycle="working"):
    return {"account": acct, "symbol": sym, "lifecycle": lifecycle, "snapshot_at": NOW - timedelta(seconds=60)}


def _pop(positions, snapshot=None):
    return sci.scan_from_snapshot(snapshot or [_snap()], positions, now=NOW, session_open=True, cfg=CFG)["population"]


def _bucket_of(pop, sym):
    hits = [k for k, rows in pop["exclusions"].items() for r in rows if r["symbol"] == sym]
    hits += ["counted"] * sum(r["symbol"] == sym for r in pop["counted_rows"])
    assert len(hits) == 1, (sym, hits)
    return hits[0]


def _invariant(pop):
    assert pop["total"] == pop["eligible"] + sum(pop["exclusion_counts"].values())
    assert pop["eligible"] == len(pop["counted_rows"]) == pop["covered"] + pop["uncovered"]


# ── C2 Y6/Y11: the floor is strict; exactly the floor is counted ──────────────────────────────────────────────
def test_scan_counts_a_row_of_exactly_the_floor_and_lists_one_cent_under():
    pop = _pop([_pos("ATFLOOR", FLOOR), _pos("UNDER", round(FLOOR - 0.01, 2))])
    assert _bucket_of(pop, "ATFLOOR") == "counted"
    assert _bucket_of(pop, "UNDER") == "below_value_floor"
    assert pop["exclusions"]["below_value_floor"][0]["threshold_usd"] == FLOOR
    _invariant(pop)


def test_desk_truth_checks_a_row_of_exactly_the_floor():
    rep = dtm.held_exit_coverage([_pos("ATFLOOR", FLOOR), _pos("UNDER", round(FLOOR - 0.01, 2))], [_snap()], CFG,
                                 now=NOW, session=True)
    assert [r["symbol"] for r in rep["below_value_floor_rows"]] == ["UNDER"]
    assert [f["evidence"]["symbol"] for f in rep["findings"] if f["code"] == "UNCOVERED"] == ["ATFLOOR"]


def test_recompute_book_checks_a_row_of_exactly_the_floor():
    cov = dtm.recompute_book([_pos("ATFLOOR", FLOOR), _pos("UNDER", round(FLOOR - 0.01, 2))], [], [], CFG,
                             now=NOW, session=False)["coverage"]
    assert [r["symbol"] for r in cov["below_value_floor_rows"]] == ["UNDER"]
    assert [r["symbol"] for r in cov["uncovered"]] == ["ATFLOOR"]


# ── C2 Y9: cash rows are read so they can be listed, not filtered out in SQL ──────────────────────────────────
def test_positions_sql_reads_cash_rows_and_their_flag():
    sql = " ".join(sci.POSITIONS_SQL.split())
    where = sql.split(" WHERE ", 1)[1]
    assert re.fullmatch(r"qty > 0", where.strip()), where           # no NOT is_cash: cash is listed, not hidden
    assert "is_cash" in sql.split(" FROM ")[0] and "asset_type" in sql.split(" FROM ")[0]


# ── C2 Y12 + C1: recompute_book never calls a $0 or missing value "below the floor" ─────────────────────────
def test_recompute_book_keeps_a_zero_or_missing_value_uncovered_row_checked():
    cov = dtm.recompute_book([_pos("ZERO", 0.0), _pos("NOVAL", None), _pos("DUST", 12.0)], [], [], CFG,
                             now=NOW, session=False)["coverage"]
    assert [r["symbol"] for r in cov["below_value_floor_rows"]] == ["DUST"]
    assert sorted(r["symbol"] for r in cov["uncovered"]) == ["NOVAL", "ZERO"]
    assert cov["below_value_floor"] == 1


# ── C2 Y15: an operator-exempt row is listed with its reason, never hidden ────────────────────────────────────
def test_operator_exempt_row_is_listed_and_every_row_is_in_one_bucket():
    pop = _pop([_pos("OPEX", 5000.0), _pos("NAKED", 5000.0), _pos("CASH", 900.0, asset="CASH", is_cash=True)])
    assert pop["total"] == 3
    assert pop["exclusions"]["exempt"] == [{"account": "live_a", "symbol": "OPEX",
                                            "why": "operator exemption (held_exit_coverage.exempt)"}]
    assert _bucket_of(pop, "OPEX") == "exempt" and _bucket_of(pop, "NAKED") == "counted"
    _invariant(pop)


# ── C1: a zero / missing / unreadable value is UNKNOWN, never under the floor ─────────────────────────────────
def test_zero_missing_and_unreadable_values_are_never_below_the_floor():
    pop = _pop([_pos("ZERO", 0.0), _pos("NEGZ", -0.0), _pos("NOVAL", None), _pos("JUNK", "n/a"), _pos("DUST", 12.0)])
    assert [r["symbol"] for r in pop["exclusions"]["below_value_floor"]] == ["DUST"]
    assert sorted(r["symbol"] for r in pop["exclusions"]["unpriced_unverifiable"]) == ["NEGZ", "ZERO"]
    states = {r["symbol"]: r["value_state"] for r in pop["counted_rows"]}
    assert states == {"NOVAL": "UNKNOWN", "JUNK": "UNKNOWN"}            # checked (size unknown), and says so
    _invariant(pop)


def test_desk_truth_lists_a_zero_value_as_unpriced_not_below_the_floor():
    rep = dtm.held_exit_coverage([_pos("ZERO", 0.0), _pos("DUST", 12.0)], [_snap()], CFG, now=NOW, session=True)
    assert [r["symbol"] for r in rep["unpriced_rows"]] == ["ZERO"]
    assert [r["symbol"] for r in rep["below_value_floor_rows"]] == ["DUST"]


# ── C3: a held row with no symbol is a DEFECT row ────────────────────────────────────────────────────────────
def test_scan_lists_a_symbol_less_row_as_a_defect_never_drops_it():
    pop = _pop([_pos("", 5000.0, qty=7), _pos(None, None, qty=2), _pos("  ", 50.0), _pos("BIG", 5000.0)])
    assert pop["total"] == 4
    rows = pop["exclusions"]["no_symbol"]
    assert len(rows) == 3 and all(r["state"] == "DEFECT" and r["why"] and r["symbol"] == "" for r in rows)
    assert [r["qty"] for r in rows] == [7.0, 2.0, 10.0]
    assert [r["broker_market_value"] for r in rows] == [5000.0, None, 50.0]
    _invariant(pop)


def test_desk_truth_lists_a_symbol_less_row_as_a_defect_and_keeps_checking_it():
    rep = dtm.held_exit_coverage([_pos("", 5000.0, qty=7)], [_snap()], CFG, now=NOW, session=True)
    assert rep["no_symbol_rows"] == [{"account": "live_a", "symbol": "", "qty": 7.0, "broker_market_value": 5000.0,
                                      "state": "DEFECT", "why": "held row has no symbol"}]
    assert [f["evidence"]["symbol"] for f in rep["findings"] if f["code"] == "UNCOVERED"] == [""]


# ── D2 (REVIEW-3079 Z7): a NaN value is unreadable, never a value ─────────────────────────────────────────────
# Postgres numeric 'NaN' arrives from psycopg2 as Decimal('NaN'); float() turns it into nan, which compares False
# with everything, so without the guard it would pass as VALUED, dodge both the floor and the $0 check, and put a
# bare NaN (not strict JSON) into the heartbeat.
def test_scan_treats_a_nan_value_as_unknown_never_valued_or_below_the_floor():
    from decimal import Decimal
    import json

    pop = _pop([_pos("FNAN", float("nan")), _pos("DNAN", Decimal("NaN")), _pos("SNAN", "NaN"), _pos("", float("nan"))])
    states = {r["symbol"]: r["value_state"] for r in pop["counted_rows"]}
    assert states == {"FNAN": "UNKNOWN", "DNAN": "UNKNOWN", "SNAN": "UNKNOWN"}
    assert all(r["broker_market_value"] is None for r in pop["counted_rows"])
    assert not pop["exclusions"].get("below_value_floor") and not pop["exclusions"].get("unpriced_unverifiable")
    assert [r["broker_market_value"] for r in pop["exclusions"]["no_symbol"]] == [None]
    json.dumps(pop, allow_nan=False, default=str)          # strict JSON: no NaN reaches the heartbeat
    _invariant(pop)


def test_desk_truth_keeps_a_nan_value_held_and_checked_never_unpriced_or_below_the_floor():
    from decimal import Decimal

    rep = dtm.held_exit_coverage([_pos("FNAN", float("nan")), _pos("DNAN", Decimal("NaN")), _pos("", float("nan"))],
                                 [_snap()], CFG, now=NOW, session=True)
    assert rep["unpriced_rows"] == [] and rep["below_value_floor_rows"] == []
    assert [r["broker_market_value"] for r in rep["no_symbol_rows"]] == [None]
    uncovered = sorted(f["evidence"]["symbol"] for f in rep["findings"] if f["code"] == "UNCOVERED")
    assert uncovered == ["", "DNAN", "FNAN"]                # held with no stop: a gap, not silently skipped
