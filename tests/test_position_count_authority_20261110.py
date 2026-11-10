"""LQ-20261107-1820 (Reality Drift #10, r2): one position-count authority. Synthetic fixtures only.

One holding is marked 99.07 by the store and 101.5 by the live re-mark. Headline = non-cash held instruments at or
above the floor (>=), store basis; all-held is a separate labelled field.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from scripts.lib import portfolio_total_contract as ptc
from scripts.lib.position_count_authority import counts_for_rows, publish_position_counts

ROOT = Path(__file__).resolve().parents[1]
OVER = ptc.OVER_100_SCOPE


def _row(sym, live, store, acct="acct_a", cash=False, qty=10):
    return {"account_id": acct, "symbol": sym, "is_cash": cash, "shares": qty, "quantity": qty,
            "market_value": live, "broker_market_value": store}


def _portfolio(extra=()):
    return {"holdings": [_row("AAA", 500, 499), _row("BBB", 101.5, 99.07), _row("CCC", 50, 49),
                         _row("CASH", 1000, 1000, cash=True), *extra]}


def _out():
    return {"totals_basis": {"basis": "positions_store"}, "portfolio_total": {"as_of": "2026-01-01T00:00:00Z"},
            "observation": {"position_counts": {"scopes": {"risk.risk_included": 2}}}}


def test_headline_is_over_floor_on_store_basis_and_difference_is_stated():
    out = publish_position_counts(_out(), _portfolio())
    c = out["position_counts"]
    assert out["position_count"] == c["position_count"] == 1       # store: only AAA >= floor
    assert out["held_count"] == 3 and c["held_count"] == 3          # all held, separate and labelled
    assert c["source"] == "positions_current" and c["as_of"] == "2026-01-01T00:00:00Z"
    assert c["live_mark_scopes"][OVER] == 2
    f = [x for x in c["findings"] if x["code"] == "LIVE_MARK_COUNT_DIFFERS"][0]
    assert len(f["instruments_crossing_floor"]) == 1


def test_boundary_is_at_or_above():
    rows = [_row("EDGE", 100, 100), _row("LOW", 99.99, 99.99)]
    assert counts_for_rows(rows)["position_count"] == 1


def test_every_surface_reads_the_same_headline():
    out = publish_position_counts(_out(), _portfolio())
    rec = out["position_counts"]["reconciliation"]
    assert rec["agree"] is True and len(set(rec["surfaces"].values())) == 1
    assert out["position_count"] == out["portfolio_total"]["position_count"] == 1
    obs = out["observation"]["position_counts"]
    assert obs["scopes"][OVER] == 1 and obs["scopes"]["risk.risk_included"] == 2 and obs["as_of"]


def test_live_mark_basis_named_and_as_of_always_present():
    o = {"totals_basis": {"basis": "live_mark"}}
    out = publish_position_counts(o, _portfolio())
    c = out["position_counts"]
    assert c["source"] == "live_mark_rows" and c["position_count"] == 2 and c["live_mark_scopes"] is None
    assert c["as_of"] and c["as_of_basis"] == "read_time"


def test_row_without_store_value_is_flagged_not_silently_live():
    out = publish_position_counts(_out(), _portfolio([_row("DDD", 500, None)]))
    c = out["position_counts"]
    assert c["position_count"] == 1  # DDD excluded from the store count
    assert any(f["code"] == "ROW_NOT_ON_STORE_BASIS" and f["rows"] == ["acct_a:DDD"] for f in c["findings"])


def test_crossing_list_applies_held_filter():
    rows = [_row("AAA", 500, 499), _row("GONE", 500, 90, qty=0)]
    c = counts_for_rows(rows)
    assert not any("GONE" in x for f in c["findings"] for x in f.get("instruments_crossing_floor", []))


def test_summary_honours_floor_argument():
    c = counts_for_rows(_portfolio()["holdings"], min_position_usd=40)
    assert "$40" in c["summary"] and c["position_count"] == 3
    assert "$40" in ptc.position_summary({ptc.POSITION_SCOPE: 3, "holdings.held_under_100": 1}, 40)


def test_floor_comes_from_config_and_moves_the_count(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"min_position_usd": 40}))
    monkeypatch.setattr(ptc, "CONFIG_PATH", cfg)
    c = counts_for_rows(_portfolio()["holdings"])
    assert c["min_position_usd"] == 40.0 and c["floor_source"] == "config" and c["position_count"] == 3
    cfg.write_text(json.dumps({"min_position_usd": 1000}))
    assert counts_for_rows(_portfolio()["holdings"])["position_count"] == 0


@pytest.mark.parametrize("body", [None, "{not json", "{}", '{"min_position_usd": "x"}', '{"min_position_usd": -5}'])
def test_unreadable_floor_config_is_loud(tmp_path, monkeypatch, caplog, body):
    cfg = tmp_path / "c.json"
    if body is not None:
        cfg.write_text(body)
    monkeypatch.setattr(ptc, "CONFIG_PATH", cfg)
    with caplog.at_level(logging.WARNING):
        c = counts_for_rows(_portfolio()["holdings"])
    assert c["floor_source"].startswith("config_unreadable")
    assert any(f["code"] == "FLOOR_CONFIG_UNREADABLE" for f in c["findings"])
    assert "unreadable" in caplog.text


def test_no_hardcoded_floor_in_touched_code():
    import re
    for rel in ("scripts/api_v2.py", "scripts/lib/cio_truth.py", "scripts/lib/position_count_authority.py"):
        text = (ROOT / rel).read_text()
        assert not re.search(r'market_value"\)\s*(or 0\)|or 0\)\s*)?\s*(>=|>|<)\s*100\b', text), rel
    assert "market_value >= 100" not in (ROOT / "scripts/lib/cio_truth.py").read_text()


def _patch_both(monkeypatch, mod, attr, value):
    """api_v2 imports ``lib.<mod>``; tests import ``scripts.lib.<mod>``: patch whichever copies exist."""
    import importlib
    for name in (f"lib.{mod}", f"scripts.lib.{mod}"):
        try:
            monkeypatch.setattr(importlib.import_module(name), attr, value)
        except ImportError:
            pass


def test_overview_endpoint_end_to_end(monkeypatch):
    from scripts import api_v2
    portfolio = {"holdings": _portfolio()["holdings"], "valuation_as_of": "2026-01-01T00:00:00Z"}
    _patch_both(monkeypatch, "cio_truth", "resolve", lambda *a, **k: {"portfolio": portfolio})
    _patch_both(monkeypatch, "cio_truth", "overview_payload", lambda payload, document=None, **k: {
        "portfolio_total": {"as_of": "2026-01-01T00:00:00Z"}, "observation": {"position_counts": {"scopes": {}}},
        "position_count": 99, "position_counts": {"counted": 99}})
    monkeypatch.setattr(api_v2, "overview", lambda: {})
    _patch_both(monkeypatch, "portfolio_value_basis", "publish_store_totals",
                lambda out, p: out.update(totals_basis={"basis": "positions_store"}))
    out = api_v2._overview_with_today_move()
    assert out["position_count"] == 1 and out["position_counts"]["source"] == "positions_current"
    assert out["position_counts"]["reconciliation"]["agree"] is True
    # authority failure: the old counts stay, but say where they came from and when
    _patch_both(monkeypatch, "position_count_authority", "publish_position_counts",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    out = api_v2._overview_with_today_move()
    assert out["position_counts_authority_error"]
    assert out["position_counts"]["source"] and out["position_counts"]["as_of"]
