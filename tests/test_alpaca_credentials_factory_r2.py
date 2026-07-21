#!/usr/bin/env python3
"""R2: credential slots host mapping + factory paper/live behavior."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers import alpaca_credentials as ac  # noqa: E402
from brokers import alpaca_factory as af  # noqa: E402


def test_slot_host_mapping():
    assert ac.base_url_for_slot("ALPACA_PAPER").endswith("paper-api.alpaca.markets")
    assert ac.base_url_for_slot("ALPACA_TAXABLE").endswith("api.alpaca.markets")
    assert ac.base_url_for_slot("ALPACA_IRA").endswith("api.alpaca.markets")
    assert "paper" not in ac.base_url_for_slot("ALPACA_TAXABLE")


def test_paper_legacy_fallback(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_SECRET_KEY", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "legacykey12")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "legacysecret99")
    k, s, base = ac.resolve_credentials("ALPACA_PAPER")
    assert k == "legacykey12" and s == "legacysecret99"
    assert base.endswith("paper-api.alpaca.markets")


def test_base_ignores_alpaca_base_url_env(monkeypatch):
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    # slot still forces paper host for PAPER
    assert ac.base_url_for_slot("ALPACA_PAPER").endswith("paper-api.alpaca.markets")


def test_factory_live_raises():
    with mock.patch.object(af, "_row", return_value={
        "account_key": "alpaca_taxable_live", "broker": "alpaca",
        "environment": "live", "credential_slot": "ALPACA_TAXABLE",
        "is_enabled": False, "api_read_enabled": False, "api_write_enabled": False,
    }):
        with pytest.raises(NotImplementedError, match="live adapter not built"):
            af.adapter_for("alpaca_taxable_live")


def test_factory_paper_returns_adapter():
    with mock.patch.object(af, "_row", return_value={
        "account_key": "tradeai_automated", "broker": "alpaca",
        "environment": "paper", "credential_slot": "ALPACA_PAPER",
        "is_enabled": True, "api_read_enabled": True, "api_write_enabled": True,
    }):
        with mock.patch("alpaca_paper_adapter.AlpacaPaperAdapter") as Cls:
            Cls.return_value = mock.Mock(name="adapter")
            a = af.adapter_for("tradeai_automated")
            assert a is Cls.return_value
            Cls.assert_called_once()
