"""Performance producer contract (portfolio audit 2026-11-16, HANDOFF section 4). Synthetic fixtures only.

Additive ``performance_contract`` block: eligibility, anchor, end_date, observation_clock, residual flags with raw NAV
change, external_flows (null + reason: the producer holds no dated external-flow ledger), and the today_pnl account
census. Existing keys and values must be unchanged (cio_truth is shared with the classic site).
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from scripts import portfolio_period_quality as ppq  # noqa: E402
from scripts.lib import cio_truth as truth  # noqa: E402

NOW = datetime(2040, 1, 15, 15, 0, tzinfo=timezone.utc)
HOLDINGS = {"generated_at": "2040-01-15T14:55:00Z", "last_repriced": "2040-01-15T14:50:00Z", "reprice_source": "synthetic",
            "holdings": [
                {"symbol": "QZA", "account": "syn_alpha", "shares": 10, "price": 100, "market_value": 1000, "day_change": 5},
                {"symbol": "QZB", "account": "syn_beta", "shares": 4, "price": 50, "market_value": 200},
                {"symbol": "QZC", "account": "syn_gamma", "shares": 1, "price": 10, "market_value": 10, "day_change": 0}]}


def _state(tmp_path: Path) -> Path:
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    for day, a, b in (("2039-12-31", 900.0, 150.0), ("2040-01-08", 950.0, 160.0)):
        (snaps / f"{day}.json").write_text(json.dumps({"date": day, "accounts": {"syn_alpha": a, "syn_beta": b}}))
    return tmp_path


def _result():
    return {"current_value": 1210, "periods": {"1W": {"change": 50, "change_pct": 5, "start_date": "2040-01-08", "start_value": 950}},
            "accounts": {"syn_alpha": {"current_value": 1000, "periods": {
                            "1W": {"change": 50, "change_pct": 5.26, "start_date": "2040-01-08", "start_value": 950, "end_value": 1000},
                            "1M": {"change": None, "change_pct": None, "start_date": "2039-12-01"}}},
                         "syn_beta": {"current_value": 200, "periods": {
                            "1W": {"change": 40, "change_pct": 25, "start_date": "2040-01-08", "start_value": 160, "end_value": 200},
                            "3M": {"change": -5, "change_pct": -50, "start_date": "2039-10-15", "start_value": 10, "end_value": 5}}},
                         "syn_gamma": {"current_value": 10, "periods": {}}}}


def test_contract_block_carries_eligibility_anchor_and_raw_nav(tmp_path):
    out = ppq.annotate_performance_result(_result(), _state(tmp_path), deepcopy(HOLDINGS))
    block = out["performance_contract"]
    assert "performance_contract_error" not in out
    alpha_w = block["accounts"]["syn_alpha"]["1W"]
    assert alpha_w["eligibility"]["status"] == "unknown"  # a number is not eligibility evidence (R2)
    assert alpha_w["anchor"] == {"snapshot_id": "2040-01-08", "date": "2040-01-08",
                                 "source": "last stored snapshot on or before the start date", "start_value_matches_snapshot": True}
    assert block["accounts"]["syn_alpha"]["1M"]["eligibility"]["status"] == "unknown"  # no result, no reason served
    assert alpha_w["external_flows"] is None and "dated external-flow ledger" in alpha_w["external_flows_reason"]
    assert block["periods"]["1W"]["external_flows"] is None
    # residual-allocated cells say so and keep the raw NAV change beside the allocated one
    beta_cells = [c for c in block["accounts"]["syn_beta"].values()]
    for period, cell in out["accounts"]["syn_beta"]["periods"].items():
        entry = block["accounts"]["syn_beta"][period]
        if str(cell.get("display_label") or "").startswith("≈ market"):
            assert entry["residual_allocated"] is True
            assert entry["raw_change"] == cell["nav_change"] and entry["raw_change_pct"] == cell["nav_change_pct"]
            assert cell["display_change"] != entry["raw_change"] or cell["estimated_net_flow"] == 0
        else:
            assert entry["residual_allocated"] is False and entry["raw_change"] == cell.get("change")
    assert beta_cells


def test_an_account_without_cells_is_named_by_the_census_not_given_a_result(tmp_path):
    out = truth.performance_payload(ppq.annotate_performance_result(_result(), _state(tmp_path), deepcopy(HOLDINGS)),
                                    holdings_doc=deepcopy(HOLDINGS), now=NOW)
    block = out["performance_contract"]
    # gamma has only the producer's synthesized YTD shell: unknown, never an invented result
    gamma = block["accounts"]["syn_gamma"]["YTD"]
    assert gamma["eligibility"]["status"] == "unknown" and gamma["raw_change"] is None
    pnl = out["today_pnl"]
    assert pnl["represented_accounts"]["count"] == len(pnl["represented_accounts"]["internal_keys"])
    assert pnl["missing_accounts_stored_rows"]["internal_keys"] == ["syn_beta"]  # QZB row has no day_change: missing, not zero
    assert "syn_alpha" in pnl["represented_accounts"]["internal_keys"]
    # legacy keys keep their meaning
    assert pnl["missing_accounts"] is None and pnl["represented_account_count"] is None


def test_end_date_and_observation_clock_come_from_the_mark_clock_or_are_null_with_a_reason(tmp_path):
    out = truth.performance_payload(ppq.annotate_performance_result(_result(), _state(tmp_path), deepcopy(HOLDINGS)),
                                    holdings_doc=deepcopy(HOLDINGS), now=NOW)
    block = out["performance_contract"]
    hh = block["periods"]["1W"]
    assert hh["end_date"] is None and hh["end_date_reason"]  # household end value unproven (R1)
    live = block["accounts"]["syn_alpha"]["1W"]
    assert live["end_date"] == "2040-01-15" and live["observation_clock"]["start"]["date"] == "2040-01-08"
    stale = block["accounts"]["syn_beta"]["3M"]  # end value 5 is not the live holdings value 200
    assert stale["end_date"] is None and stale["observation_clock"] is None and stale["end_date_reason"]


def test_existing_keys_and_values_are_unchanged_by_the_additive_contract(tmp_path, monkeypatch):
    state = _state(tmp_path)
    new = truth.performance_payload(ppq.annotate_performance_result(_result(), state, deepcopy(HOLDINGS)),
                                    holdings_doc=deepcopy(HOLDINGS), now=NOW)
    monkeypatch.setattr(ppq, "add_performance_contract_fields", lambda *a, **k: None)
    monkeypatch.setattr(truth, "_add_performance_contract", lambda *a, **k: None)
    old = truth.performance_payload(ppq.annotate_performance_result(_result(), state, deepcopy(HOLDINGS)),
                                    holdings_doc=deepcopy(HOLDINGS), now=NOW)
    added_top = {"performance_contract"}
    added_pnl = {"represented_accounts", "missing_accounts_stored_rows"}
    assert set(new) - set(old) == added_top and not set(old) - set(new)
    assert {k: new[k] for k in old if k != "today_pnl"} == {k: old[k] for k in old if k != "today_pnl"}
    assert set(new["today_pnl"]) - set(old["today_pnl"]) == added_pnl
    assert {k: new["today_pnl"][k] for k in old["today_pnl"]} == old["today_pnl"]


def test_residual_allocated_cell_is_flagged_with_raw_nav_beside_it(tmp_path):
    cell = {"change": 9000.0, "change_pct": 90.0, "nav_change": 9000.0, "nav_change_pct": 90.0, "adjusted_change": 120.0,
            "display_change": 120.0, "display_label": "≈ market (ex-transfers)", "flags": ["ex_transfer_residual"],
            "estimated_net_flow": 8880.0, "start_date": "2040-01-08", "start_value": 10000.0, "end_value": 19000.0}
    plain = {"change": 3.0, "change_pct": 1.0, "start_date": "2040-01-08", "start_value": 300.0, "end_value": 303.0}
    result = {"periods": {}, "accounts": {"syn_alpha": {"current_value": 19000.0, "periods": {"1W": cell, "1M": plain}}}}
    ppq.add_performance_contract_fields(result, _state(tmp_path), [], None)
    entries = result["performance_contract"]["accounts"]["syn_alpha"]
    assert entries["1W"]["residual_allocated"] is True
    assert entries["1W"]["raw_change"] == 9000.0 and entries["1W"]["raw_change_pct"] == 90.0
    assert entries["1M"]["residual_allocated"] is False and entries["1M"]["raw_change"] == 3.0
    assert entries["1W"]["anchor"]["date"] is None  # empty series: no anchor invented
    assert cell["display_change"] == 120.0  # the cell itself is untouched


def test_household_end_date_is_not_the_pricing_date_when_history_ends_earlier(tmp_path):
    """Reviewer probe p2: history ends before the mark; no household cell may claim the mark date."""
    res = _result()
    res["periods"]["1D"] = {"change": None, "change_pct": None, "start_date": "2040-01-14"}
    out = truth.performance_payload(ppq.annotate_performance_result(res, _state(tmp_path), deepcopy(HOLDINGS)),
                                    holdings_doc=deepcopy(HOLDINGS), now=NOW)
    for key, entry in out["performance_contract"]["periods"].items():
        assert entry["end_date"] != "2040-01-15" and entry["end_date"] is None and entry["end_date_reason"], key


def test_account_figure_without_registry_is_unknown_not_eligible_probe_p1(tmp_path):
    result = {"periods": {}, "accounts": {"syn_alpha": {"current_value": 1000.0, "periods": {
        "1D": {"change": -555.0, "change_pct": -5.0, "start_date": "2040-01-14", "start_value": 1555.0, "end_value": 1000.0}}}}}
    ppq.add_performance_contract_fields(result, _state(tmp_path), [], None)
    status = result["performance_contract"]["accounts"]["syn_alpha"]["1D"]["eligibility"]
    assert status["status"] == "unknown" and status["source"]


def test_missing_current_value_is_unknown_never_ineligible(tmp_path):
    state = _state(tmp_path)
    for acct in ({"periods": {"1W": {"change": None, "change_pct": None, "start_date": "2040-01-08"}}},
                 {"current_value": None, "periods": {"1W": {"change": None, "change_pct": None, "start_date": "2040-01-08"}}}):
        result = {"periods": {}, "accounts": {"syn_alpha": acct}}
        ppq.add_performance_contract_fields(result, state, [], None)
        assert result["performance_contract"]["accounts"]["syn_alpha"]["1W"]["eligibility"]["status"] == "unknown"


def test_window_start_not_before_end_is_not_served_as_an_interval(tmp_path):
    res = {"current_value": 1000, "periods": {}, "accounts": {"syn_alpha": {"current_value": 1000, "periods": {
        "1W": {"change": 1, "change_pct": 1, "start_date": "2040-01-16", "start_value": 999, "end_value": 1000}}}}}
    out = truth.performance_payload(ppq.annotate_performance_result(res, _state(tmp_path), deepcopy(HOLDINGS)),
                                    holdings_doc=deepcopy(HOLDINGS), now=NOW)
    e = out["performance_contract"]["accounts"]["syn_alpha"]["1W"]
    assert e["end_date"] is None and e["end_date_reason"]
