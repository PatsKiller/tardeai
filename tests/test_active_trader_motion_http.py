#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.motion_engine import CONTRACT  # noqa: E402
from active_trader.motion_snapshot_api import read_motion_snapshot  # noqa: E402
from active_trader.read_http import dispatch  # noqa: E402

NOW = 1_753_700_000.0


def _payload(generated_at=NOW):
    return {
        "contract": CONTRACT,
        "generated_at": generated_at,
        "data_state": "LIVE_MOTION",
        "available": True,
        "ui_refresh_after_s": 5,
        "push_primary": True,
        "max_pull_fallbacks_per_minute": 2,
        "t2": {
            "operating_cap": 2,
            "provider_hard_cap": 8,
            "leases": [{"symbol": "AAPL"}],
            "decisions": [],
            "events": [],
        },
        "candidates": [{"symbol": "AAPL", "tier": "T2"}],
        "positions": [],
        "exit_signals": [],
        "authority": {"order": True},
    }


def test_missing_snapshot_returns_honest_unavailable(tmp_path):
    body = read_motion_snapshot(tmp_path / "missing.json", now=NOW)
    assert body["data_state"] == "MOTION_API_UNAVAILABLE"
    assert body["available"] is False
    assert body["candidates"] == []
    assert body["authority"]["order"] is False


def test_fresh_snapshot_is_preserved_but_authority_is_forced_off(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    body = read_motion_snapshot(path, now=NOW + 4, stale_after_s=35)
    assert body["data_state"] == "LIVE_MOTION"
    assert body["snapshot_age_s"] == 4
    assert body["candidates"][0]["symbol"] == "AAPL"
    assert body["authority"]["order"] is False
    assert body["write"] is False


def test_stale_snapshot_keeps_last_good_data_with_stale_state(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    body = read_motion_snapshot(path, now=NOW + 100, stale_after_s=35)
    assert body["data_state"] == "MOTION_DATA_STALE"
    assert body["available"] is True
    assert body["candidates"][0]["symbol"] == "AAPL"
    assert body["snapshot_age_s"] == 100


def test_dispatch_exposes_get_only_motion_route(monkeypatch, tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setenv("ACTIVE_TRADER_MOTION_SNAPSHOT", str(path))
    monkeypatch.setattr("time.time", lambda: NOW + 1)

    status, body = dispatch(None, "GET", "/api/v3/active-trader/motion", {})
    assert status == 200
    assert body["contract"] == CONTRACT
    assert body["candidates"][0]["symbol"] == "AAPL"

    status, body = dispatch(None, "POST", "/api/v3/active-trader/motion", {})
    assert status == 405
    assert body["authority"]["order"] is False
