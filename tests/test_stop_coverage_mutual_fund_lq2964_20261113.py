"""ANCHOR: STOP_COVERAGE_MUTUAL_FUND_LQ2964_20261113 -- a held mutual fund is not a stop gap, and is never hidden.

Lead decision 2026-11-13 09:39 ET: mutual funds cannot carry stop orders, so MUTUAL_FUND is in
held_exit_coverage.exclude_asset_types, and Home shows it as "not stop-protectable (mutual fund)".
Synthetic data only; no DB, no broker.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import stop_coverage_incidents as sci  # noqa: E402
from scripts import home_status_verdict as hsv  # noqa: E402
from scripts.lib import home_trade_ready as htr  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)  # 10:00 ET Friday, in session
LABEL = "not stop-protectable (mutual fund)"


def _committed_cfg() -> dict:
    return json.loads((ROOT / "config" / "desk_truth_monitors.json").read_text())["held_exit_coverage"]


def _snap(sym, acct="live_a"):
    return {"account": acct, "symbol": sym, "lifecycle": "working", "snapshot_at": NOW - timedelta(seconds=300)}


def _pos(sym, asset, acct="live_a"):
    return {"account_key": acct, "symbol": sym, "qty": 10, "broker_market_value": 5000.0,
            "as_of": NOW - timedelta(seconds=600), "asset_type": asset, "is_cash": False}


def test_committed_config_excludes_mutual_funds_and_labels_them():
    cfg = _committed_cfg()
    assert "MUTUAL_FUND" in cfg["exclude_asset_types"]
    assert "option" in cfg["exclude_asset_types"]          # the prior exclusion is kept
    assert cfg["not_stop_protectable_labels"]["mutual_fund"] == LABEL


def test_held_mutual_fund_is_not_a_gap_but_is_listed_with_its_label():
    cfg = dict(_committed_cfg(), paper_accounts=[], account_aliases={})
    sc = sci.scan_from_snapshot([_snap("AAA")], [_pos("AAA", "EQUITY"), _pos("AMANX", "MUTUAL_FUND"),
                                                 _pos("BBB", "EQUITY")], now=NOW, cfg=cfg)
    k = {r["symbol"]: r for r in sc["stops"]}
    assert "AMANX" not in k                                   # never a gap
    assert k["BBB"]["flags"] == ["unprotected"]               # an equity without a stop still is
    assert sc["not_stop_protectable"] == [{"symbol": "AMANX", "asset_type": "MUTUAL_FUND", "label": LABEL}]


def test_excluded_type_without_a_label_stays_silent_as_before():
    cfg = dict(_committed_cfg(), paper_accounts=[], account_aliases={})
    sc = sci.scan_from_snapshot([_snap("AAA")], [_pos("AAA", "EQUITY"), _pos("SPY250101C", "option")],
                                now=NOW, cfg=cfg)
    assert sc["not_stop_protectable"] == []
    assert {r["symbol"] for r in sc["stops"]} == {"AAA"}


def test_home_orders_reading_shows_the_fund_and_stays_ok(tmp_path):
    doc = {"started_at": NOW.isoformat(), "finished_at": NOW.isoformat(), "status": "ok", "gaps": 0,
           "day_stop_expired": 0, "unresolved_unknown": 0,
           "not_stop_protectable": [{"symbol": "AMANX", "asset_type": "MUTUAL_FUND", "label": LABEL}]}
    sci._heartbeat(doc, tmp_path / "data" / "runtime" / sci.HEARTBEAT_NAME)
    r = hsv.read_orders(lambda *a, **k: [], datetime.now(timezone.utc), tmp_path, [])
    assert r.state == htr.OK
    assert r.data_quality == [{"code": "not_stop_protectable", "symbol": "AMANX", "asset_type": "MUTUAL_FUND",
                               "label": LABEL}]


def test_main_heartbeat_carries_the_list_not_a_count(tmp_path, monkeypatch):
    rows = [{"symbol": "AMANX", "asset_type": "MUTUAL_FUND", "label": LABEL}]
    monkeypatch.setattr(sci, "scan_from_snapshot", lambda *a, **k: {"ok": True, "stops": [], "summary": {"total": 0},
                                                                    "not_stop_protectable": rows})
    monkeypatch.setattr(sci, "_fetch", lambda *a, **k: [])
    monkeypatch.setattr(sci, "run", lambda *a, **k: {"ok": True, "gaps": [], "resolve": [], "applied": True,
                                                     "reason": None})
    seen = {}
    monkeypatch.setattr(sci, "_heartbeat", lambda doc, path=None: seen.update(doc))
    import db_adapter
    monkeypatch.setattr(db_adapter, "_get_conn", lambda *a, **k: object())
    assert sci.main(["--apply"]) == 0
    assert seen["not_stop_protectable"] == rows
