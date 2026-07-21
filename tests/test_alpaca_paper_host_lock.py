#!/usr/bin/env python3
"""Host-lock for alpaca_stop_manager + alpaca_paper_reconciler (audit 2026-07-21 P0).

No network — assert fires before urlopen. Colocated with other Alpaca paper safety tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import alpaca_stop_manager as asm  # noqa: E402
import alpaca_paper_reconciler as apr  # noqa: E402

PAPER = "https://paper-api.alpaca.markets"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ALPACA_BASE_URL", "ALPACA_MODE"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_stop_mgr_live_url_raises(monkeypatch):
    monkeypatch.setenv("ALPACA_MODE", "paper")
    with pytest.raises(RuntimeError, match="BLOCKED"):
        asm.require_paper_trading_base({
            "ALPACA_BASE_URL": "https://api.alpaca.markets",
            "ALPACA_MODE": "paper",
        })


def test_reconciler_live_url_raises(monkeypatch):
    monkeypatch.setenv("ALPACA_MODE", "paper")
    with pytest.raises(RuntimeError, match="BLOCKED"):
        apr.require_paper_trading_base({
            "ALPACA_BASE_URL": "https://api.alpaca.markets",
            "ALPACA_MODE": "paper",
        })


def test_subdomain_suffix_spoof_raises():
    with pytest.raises(RuntimeError, match="BLOCKED"):
        asm.require_paper_trading_base({
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets.evil.com",
            "ALPACA_MODE": "paper",
        })
    with pytest.raises(RuntimeError, match="BLOCKED"):
        apr.require_paper_trading_base({
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets.evil.com",
            "ALPACA_MODE": "paper",
        })


def test_mode_live_with_paper_url_raises():
    with pytest.raises(RuntimeError, match="ALPACA_MODE"):
        asm.require_paper_trading_base({
            "ALPACA_BASE_URL": PAPER,
            "ALPACA_MODE": "live",
        })
    with pytest.raises(RuntimeError, match="ALPACA_MODE"):
        apr.require_paper_trading_base({
            "ALPACA_BASE_URL": PAPER,
            "ALPACA_MODE": "live",
        })


def test_unset_url_mode_paper_passes(monkeypatch):
    monkeypatch.setenv("ALPACA_MODE", "paper")
    env = {"ALPACA_MODE": "paper"}  # no ALPACA_BASE_URL
    assert asm.require_paper_trading_base(env) == PAPER.rstrip("/")
    assert apr.require_paper_trading_base(env) == PAPER.rstrip("/")


def test_stop_mgr_req_never_opens_socket_on_live(monkeypatch):
    """_alpaca_req must raise before urlopen when host is live."""
    env = {
        "ALPACA_BASE_URL": "https://api.alpaca.markets",
        "ALPACA_MODE": "paper",
        "ALPACA_API_KEY": "x",
        "ALPACA_SECRET_KEY": "y",
    }
    monkeypatch.setenv("ALPACA_MODE", "paper")
    with mock.patch("urllib.request.urlopen") as uo:
        with pytest.raises(RuntimeError, match="BLOCKED"):
            asm._alpaca_req(env, "/v2/orders")
        uo.assert_not_called()


def test_reconciler_positions_never_opens_socket_on_live(monkeypatch):
    env = {
        "ALPACA_BASE_URL": "https://api.alpaca.markets",
        "ALPACA_MODE": "paper",
        "ALPACA_API_KEY": "x",
        "ALPACA_SECRET_KEY": "y",
    }
    with mock.patch("urllib.request.urlopen") as uo:
        with pytest.raises(RuntimeError, match="BLOCKED"):
            apr.get_alpaca_positions(env)
        uo.assert_not_called()


def test_stop_mgr_telegram_on_block(monkeypatch):
    calls = []

    def fake_tg(msg, bypass_router=False):
        calls.append((msg, bypass_router))
        return True

    import types
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = fake_tg
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    with pytest.raises(RuntimeError):
        asm.require_paper_trading_base({
            "ALPACA_BASE_URL": "https://api.alpaca.markets",
            "ALPACA_MODE": "paper",
        })
    assert calls and calls[0][1] is True
    assert "BLOCKED" in calls[0][0]
