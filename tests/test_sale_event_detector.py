#!/usr/bin/env python3
"""Post-sale redeploy — sale_event_detector + deploy_events_db tests."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_event_key_uses_dedupe_key():
    det = _load_module("sale_event_detector", "scripts/lib/sale_event_detector.py")
    row = {"dedupe_key": "2026-07-14|Sell|FCNTX|4034|schwab_rollover_ira|ord:1", "symbol": "FCNTX"}
    assert det.event_key_for_row(row) == "txn:2026-07-14|Sell|FCNTX|4034|schwab_rollover_ira|ord:1"


def test_fcntx_proxy_metadata():
    det = _load_module("sale_event_detector", "scripts/lib/sale_event_detector.py")
    meta = det._instrument_meta("FCNTX")
    assert meta["symbol"] == "FCNTX"
    assert meta["instrument_type"] == "mutual_fund"
    assert meta["proxy_symbol"] == "SCHG"
    assert "large-cap growth" in (meta["proxy_sleeve"] or "")


def test_skip_spaxx_and_cash():
    det = _load_module("sale_event_detector", "scripts/lib/sale_event_detector.py")
    assert not det._is_sell_row({"action": "Sell", "symbol": "SPAXX"})
    assert not det._is_sell_row({"action": "Sell", "symbol": "CASH"})


def test_backfill_status_auto_dismiss_over_90d():
    db = _load_module("deploy_events_db", "scripts/lib/deploy_events_db.py")
    old = date.today() - timedelta(days=120)
    status, reason = db.backfill_status_for_date(old, dismiss_after_days=90)
    assert status == "dismissed"
    assert reason == "historical_backfill_over_90d"


def test_backfill_status_open_within_90d():
    db = _load_module("deploy_events_db", "scripts/lib/deploy_events_db.py")
    recent = date.today() - timedelta(days=10)
    status, reason = db.backfill_status_for_date(recent, dismiss_after_days=90)
    assert status == "open"
    assert reason is None


def test_normalize_fcntx_sell_row():
    det = _load_module("sale_event_detector", "scripts/lib/sale_event_detector.py")
    row = {
        "id": 218353,
        "trade_date": date(2026, 7, 14),
        "action": "Sell",
        "symbol": "FCNTX",
        "quantity": 4034.942,
        "amount": 107023.01,
        "account": "schwab_rollover_ira",
        "dedupe_key": "2026-07-14|Sell|FCNTX|4034.942|schwab_rollover_ira|ord:1007158466866",
    }
    ev = det.normalize_sell_row(row, source="live_detect")
    assert ev["symbol"] == "FCNTX"
    assert ev["proceeds_usd"] == 107023.01
    assert ev["proxy_symbol"] == "SCHG"
    assert ev["status"] == "open"
    assert ev["source"] == "live_detect"


def test_sync_deploy_events_dry_run_has_fcntx():
    det = _load_module("sale_event_detector", "scripts/lib/sale_event_detector.py")
    report = det.sync_deploy_events(apply=False, days=30, source="live_detect")
    keys = {e["symbol"] for e in (report.get("events") or [])}
    assert "FCNTX" in keys


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("ok", _name)
    print("all passed")