#!/usr/bin/env python3
"""Watchlist agent symbol gate — rejects garbage tokens before LLM spend."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from hermes_discovery.symbol_validation import gate_watchlist_symbol


def test_rejects_numeric_garbage():
    ok, reason = gate_watchlist_symbol("543354104")
    assert not ok
    assert "shape" in reason.lower()


def test_rejects_empty():
    ok, reason = gate_watchlist_symbol("")
    assert not ok


def test_portfolio_allowlist_with_shape():
    ok, reason = gate_watchlist_symbol("LDOS", portfolio_symbols=frozenset({"LDOS"}))
    assert ok
    assert "portfolio" in reason.lower()


def test_denylist_token_invalid_without_profile():
    ok, reason = gate_watchlist_symbol("CEO")
    assert not ok