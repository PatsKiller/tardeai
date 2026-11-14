"""LQ-20261113-3047 (Home/Portfolio A05): one protection count floor, $100, listed not hidden.

Approved policy (design/pages/portfolio/v002/DECISIONS-20261111.md §Exemptions): cash, money-market funds and sweep
vehicles are exempt; ETF / CEF / mutual fund / stock are never exempt; a position under $100 is listed, not counted,
not hidden; one config owner (config/position_count_authority.json ``min_position_usd``). The $1,000
``min_position_value_usd`` in config/desk_truth_monitors.json was a defect.

The book below is synthetic (no DB, no broker). The before/after test runs the same book at the old $1,000 and at
the policy $100 and names every class that is newly counted.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import desk_truth_monitor as dtm  # noqa: E402
import stop_coverage_incidents as sci  # noqa: E402
from scripts.lib import cio_truth  # noqa: E402
from scripts.lib import protection_policy as pp  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
CFG = {"paper_accounts": ["paper_x"], "exclude_asset_types": ["option", "MUTUAL_FUND"],
       "not_stop_protectable_labels": {"mutual_fund": "not stop-protectable (mutual fund)"},
       "exempt": [], "account_aliases": {}, "working_lifecycles": ["working", "near_trigger"],
       "snapshot_stale_after_h": 2.0}

# (symbol, market value, asset type, is_cash, account, has a working stop)
BOOK = [
    ("BIG", 5000.0, "EQUITY", False, "live_a", True),       # protected
    ("NAKED", 9000.0, "EQUITY", False, "live_a", False),    # unprotected
    ("MID", 500.0, "EQUITY", False, "live_a", False),       # $100-$999 stock, no stop
    ("ETFM", 250.0, "ETF", False, "live_a", True),          # $100-$999 ETF, stop
    ("CEFM", 150.0, "CEF", False, "live_a", False),         # $100-$999 closed-end fund, no stop
    ("DUST", 40.0, "EQUITY", False, "live_a", False),       # fractional / under $100
    ("CUSIP1", 0.0, "EQUITY", False, "live_a", False),      # unpriced ($0 on a nonzero quantity)
    ("FUND", 5000.0, "MUTUAL_FUND", False, "live_a", False),  # mutual fund (LQ-2964 label)
    ("NV", 21.0, "EQUITY", False, "moomoo", False),         # no stop read source for the account
    ("CASH", 10000.0, "CASH", True, "live_a", False),       # cash
    ("SWVXX", 3000.0, "MONEY_MARKET_FUND", False, "live_a", False),  # money-market fund
    ("SWEEPX", 2000.0, "SWEEP", False, "live_a", False),    # sweep vehicle
]
NEWLY_COUNTED = {("MID", "EQUITY"), ("ETFM", "ETF"), ("CEFM", "CEF")}


def _positions():
    return [{"account_key": a, "symbol": s, "qty": 10, "broker_market_value": mv, "asset_type": t, "is_cash": c,
             "as_of": NOW - timedelta(seconds=60)} for s, mv, t, c, a, _ in BOOK]


def _snapshot():
    return [{"account": a, "symbol": s, "lifecycle": "working" if stop else "cancelled",
             "snapshot_at": NOW - timedelta(seconds=60)} for s, _, _, _, a, stop in BOOK if a != "moomoo"]


def _scan(floor_usd=None, cfg=CFG):
    return sci.scan_from_snapshot(_snapshot(), _positions(), now=NOW, session_open=True, cfg=cfg,
                                  floor_usd=floor_usd)


def _symbols(rows):
    return sorted(r["symbol"] for r in rows)


# ── one owner, $100 ───────────────────────────────────────────────────────────────────────────────────────────
def test_the_floor_is_the_policy_100_from_its_one_config_owner():
    owner = json.loads((ROOT / "config" / "position_count_authority.json").read_text())
    assert owner["min_position_usd"] == 100
    assert pp.count_floor_usd() == 100.0
    assert pp.source() == {"count_floor_usd": 100.0, "config": pp.FLOOR_CONFIG, "source": "config"}
    assert cio_truth.COUNT_FLOOR_USD == 100.0


@pytest.mark.parametrize("rel", ["config/desk_truth_monitors.json", "config/numbers_truth_catalog.json"])
def test_the_1000_dollar_key_is_gone(rel):
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)

    assert "min_position_value_usd" not in set(keys(json.loads((ROOT / rel).read_text())))


def test_a_stale_1000_in_cfg_is_ignored_never_a_second_floor():
    stale = dict(CFG, min_position_value_usd=1000.0)
    assert _scan(cfg=stale)["population"] == _scan()["population"]
    rep = dtm.held_exit_coverage(_positions(), _snapshot(), stale, now=NOW, session=True)
    assert rep["value_floor_usd"] == 100.0 and rep["value_floor_source"].startswith(pp.FLOOR_CONFIG)


# ── exemptions ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("is_cash,asset_type,want", [
    (True, "EQUITY", "cash"), (False, "CASH", "cash"), (False, "MONEY_MARKET_FUND", "money-market fund"),
    (False, "money market", "money-market fund"), (False, "SWEEP", "sweep vehicle"),
    (False, "ETF", None), (False, "CEF", None), (False, "MUTUAL_FUND", None), (False, "EQUITY", None),
    (False, "STOCK", None), (False, None, None), (False, "SOMETHING_NEW", None),
])
def test_policy_exemptions(is_cash, asset_type, want):
    assert pp.exempt_reason(is_cash=is_cash, asset_type=asset_type) == want


# ── every held row listed, with its threshold, exemption reason or UNKNOWN ────────────────────────────────────
def test_every_row_is_listed_with_a_state_or_a_reason_none_hidden():
    pop = _scan()["population"]
    assert pop["total"] == len(BOOK)
    listed = _symbols(pop["counted_rows"]) + sorted(r["symbol"] for rows in pop["exclusions"].values() for r in rows)
    assert sorted(listed) == sorted(s for s, *_ in BOOK)                   # each exactly once
    ex = pop["exclusions"]
    assert {r["symbol"]: r["why"] for r in ex["policy_exempt"]} == {
        "CASH": "cash", "SWVXX": "money-market fund", "SWEEPX": "sweep vehicle"}
    assert ex["below_value_floor"] == [{"account": "live_a", "symbol": "DUST", "broker_market_value": 40.0,
                                        "threshold_usd": 100.0, "covered": False}]
    assert ex["stop_source_unobserved"][0]["state"] == "UNKNOWN" and ex["stop_source_unobserved"][0]["why"]
    assert ex["not_stop_protectable"][0]["label"] == "not stop-protectable (mutual fund)"
    assert _symbols(ex["unpriced_unverifiable"]) == ["CUSIP1"]
    assert pop["floor_usd"] == 100.0 and pop["floor_source"].startswith(pp.FLOOR_CONFIG)


# ── before/after: $1,000 -> $100 ─────────────────────────────────────────────────────────────────────────────
def test_before_after_eligibility_counts_and_the_newly_counted_classes():
    before, after = _scan(floor_usd=1000.0)["population"], _scan()["population"]
    assert (before["eligible"], before["covered"], before["uncovered"]) == (2, 1, 1)      # BIG, NAKED
    assert (after["eligible"], after["covered"], after["uncovered"]) == (5, 2, 3)
    assert _symbols(before["exclusions"]["below_value_floor"]) == ["CEFM", "DUST", "ETFM", "MID"]
    assert _symbols(after["exclusions"]["below_value_floor"]) == ["DUST"]
    newly = {r["symbol"] for r in after["counted_rows"]} - {r["symbol"] for r in before["counted_rows"]}
    types = {s: t for s, _, t, *_ in BOOK}
    assert {(s, types[s]) for s in newly} == NEWLY_COUNTED                  # a $100-$999 stock, ETF and CEF
    states = {r["symbol"]: r["state"] for r in after["counted_rows"]}
    assert (states["MID"], states["ETFM"], states["CEFM"]) == ("uncovered", "covered", "uncovered")
    # every other bucket is the same at either floor: the floor moves rows between counted and listed only
    for k in ("policy_exempt", "not_stop_protectable", "stop_source_unobserved", "unpriced_unverifiable"):
        assert before["exclusions"][k] == after["exclusions"][k], k
    assert before["total"] == after["total"] == len(BOOK)


def test_before_after_in_desk_truth_coverage():
    rep = dtm.held_exit_coverage(_positions(), _snapshot(), CFG, now=NOW, session=True)
    # NV ($21, moomoo) is under the floor here too: desk_truth has no unobserved-account bucket, the scan lists
    # it first as stop_source_unobserved. Either way it is listed, never counted.
    assert rep["value_floor_usd"] == 100.0 and rep["below_value_floor"] == 2
    assert _symbols(rep["below_value_floor_rows"]) == ["DUST", "NV"]
    assert {r["threshold_usd"] for r in rep["below_value_floor_rows"]} == {100.0}
    uncovered = sorted(f["evidence"]["symbol"] for f in rep["findings"] if f["code"] == "UNCOVERED")
    # $0 is checked here (desk_truth), UNKNOWN in the scan: the divergence is reported, not pinned as policy
    assert set(uncovered) - {"CUSIP1"} == {"MID", "CEFM", "NAKED"}
    assert {r["symbol"]: r["why"] for r in rep["policy_exempt_rows"]} == {
        "CASH": "cash", "SWVXX": "money-market fund", "SWEEPX": "sweep vehicle"}
    assert _symbols(rep["excluded_type_rows"]) == ["FUND"]
    assert _symbols(rep["unpriced_rows"]) == ["CUSIP1"]


# ── the readers agree on the floor ───────────────────────────────────────────────────────────────────────────
def test_readers_agree_on_which_priced_rows_are_under_the_floor():
    """stop_coverage, desk_truth and cio_truth list the same priced non-exempt rows under the floor."""
    scan_below = set(_symbols(_scan()["population"]["exclusions"]["below_value_floor"]))
    desk_below = {r["symbol"] for r in dtm.held_exit_coverage(_positions(), _snapshot(), CFG, now=NOW,
                                                              session=True)["below_value_floor_rows"]
                  if r["account"] != "moomoo"}     # the scan lists moomoo rows as unobserved first
    cio_not_counted = set()
    for s, mv, t, c, a, _ in BOOK:
        if c or pp.exempt_reason(is_cash=c, asset_type=t) or t == "MUTUAL_FUND" or a == "moomoo" or mv <= 0:
            continue
        row = cio_truth.protection_for({"symbol": s, "market_value": mv, "asset_type": t, "shares": 10,
                                        "account_id": "schwab_live_a"}, broker_available=True)
        if not row["protection"]["counted"]:
            cio_not_counted.add(s)
    assert scan_below == desk_below == cio_not_counted == {"DUST"}
