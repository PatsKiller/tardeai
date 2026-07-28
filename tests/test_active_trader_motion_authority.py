#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _motion_source() -> str:
    paths = [
        ROOT / "scripts" / "active_trader" / "motion_journal.py",
        ROOT / "scripts" / "active_trader" / "motion_engine.py",
        ROOT / "scripts" / "active_trader" / "motion_snapshot_api.py",
        ROOT / "scripts" / "active_trader_motion_tick.py",
    ]
    return "\n".join(
        path.read_text(encoding="utf-8").lower() for path in paths
    )


def test_motion_sources_have_no_network_broker_or_order_actions():
    source = _motion_source()
    forbidden = [
        "import requests",
        "import socket",
        "import urllib",
        "http://",
        "https://",
        "place_order",
        "submit_order",
        "cancel_order",
        "modify_order",
        "unlock_trade",
        "trade_unlock",
        "api_key",
        "secret_key",
        "oauth_token",
    ]
    assert [token for token in forbidden if token in source] == []


def test_motion_policy_has_no_hardwired_account_environment_taxonomy():
    source = _motion_source()
    forbidden = [
        "mode_paper",
        "paper/shadow",
        "paper execution",
        "paper exit",
        "account_not_execution_eligible",
        "mode_not_paper_or_shadow",
    ]
    assert [token for token in forbidden if token in source] == []


def test_tick_utility_is_one_shot_without_internal_loop():
    source = (ROOT / "scripts" / "active_trader_motion_tick.py").read_text(
        encoding="utf-8"
    )
    assert "while True" not in source
    assert "time.sleep(" not in source
    assert 'sub.add_parser("tick"' in source
    assert 'sub.add_parser("record"' in source


def test_motion_route_remains_get_only():
    source = (ROOT / "scripts" / "active_trader" / "read_http.py").read_text(
        encoding="utf-8"
    )
    assert 'if method != "GET"' in source
    assert 'suffix in ("motion", "live-motion", "live_motion")' in source
