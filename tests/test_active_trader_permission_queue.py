#!/usr/bin/env python3
"""ActiveTrader permission-queue API — read-only, GET-only, zero-authority, no order path."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.read_http import dispatch, ACTIVE_TRADER_PREFIX  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI          # noqa: E402

API = ReadOnlyActiveTraderAPI()


def test_permission_queue_read_only_manual_paper_only():
    status, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert status == 200
    assert body["read_only"] is True and body["write"] is False and body["auto_route"] is False
    assert body["mode"] == "MANUAL_PAPER_TEST_ONLY"
    assert all(v is False for v in body["authority"].values())


def test_permission_queue_no_order_or_live_routing():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    p = body["posture"]
    assert p["order_path"] is False and p["live_routing"] is False and p["final_submit_present"] is False
    assert p["selectable_paper_venue"] == "alpaca_paper"
    assert "moomoo" in p["data_plane_only"] and "thinkorswim_manual" in p["manual_handoff"]


def test_permission_queue_empty_is_sample():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert body["is_sample"] is True
    assert body["signals"] == [] and body["accounts"] == []   # nothing live wired yet, honestly empty


def test_permission_queue_is_get_only():
    status, body = dispatch(API, "POST", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert status == 405 and body["write"] is False


def test_existing_endpoints_still_ok():
    for suffix in ("health", "scalp/setups", "near-ready"):
        status, _ = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/{suffix}")
        assert status == 200


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
