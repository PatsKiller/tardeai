#!/usr/bin/env python3
"""Tests for auto cross-account cost-basis transfer detection."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "cost_basis_transfer",
        ROOT / "scripts" / "lib" / "cost_basis_transfer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _holding(symbol: str, account: str, shares: float, cost_basis: float | None = None, **kw):
    row = {"symbol": symbol, "account": account, "shares": shares, "is_cash": False}
    if cost_basis is not None:
        row["cost_basis"] = cost_basis
        row["cost_basis_source"] = kw.pop("cost_basis_source", "snaptrade")
    row.update(kw)
    return row


def test_detect_fidelity_to_schwab_transfer_high_confidence():
    mod = _load()
    prior = {"holdings": [
        _holding("SCHG", "fidelity_rollover_ira", 1700, 52379.0, cost_basis_source="snaptrade"),
    ]}
    current = {"holdings": [
        _holding("SCHG", "schwab_rollover_ira", 1700, basis_partial=True,
                 cost_basis_source="partial_transfer_in"),
    ]}
    events = mod.detect_transfers(prior, current)
    assert len(events) == 1
    ev = events[0]
    assert ev["symbol"] == "SCHG"
    assert ev["from_account"] == "fidelity_rollover_ira"
    assert ev["to_account"] == "schwab_rollover_ira"
    assert ev["shares"] == 1700
    assert ev["confidence"] == "high"
    assert abs(ev["per_share_basis"] - 30.8112) < 0.01


def test_ignores_same_account_share_change():
    mod = _load()
    prior = {"holdings": [_holding("V", "schwab_rollover_ira", 1000, 43000.0)]}
    current = {"holdings": [_holding("V", "schwab_rollover_ira", 1100, 43000.0)]}
    assert mod.detect_transfers(prior, current) == []


def test_ignores_cash_symbols():
    mod = _load()
    prior = {"holdings": [{"symbol": "SPAXX", "account": "fidelity_rollover_ira", "shares": 100000, "is_cash": True}]}
    current = {"holdings": [{"symbol": "SPAXX", "account": "schwab_rollover_ira", "shares": 100000, "is_cash": True}]}
    assert mod.detect_transfers(prior, current) == []


def test_medium_confidence_when_basis_unknown():
    mod = _load()
    prior = {"holdings": [_holding("FCNTX", "fidelity_rollover_ira", 500)]}
    current = {"holdings": [_holding("FCNTX", "schwab_rollover_ira", 500)]}
    events = mod.detect_transfers(prior, current, fidelity_ps={})
    assert len(events) == 1
    assert events[0]["confidence"] == "low"
    assert events[0]["per_share_basis"] is None


def test_tag_holdings_applies_basis_on_auto_applied(tmp_path, monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(mod, "EVENTS_PATH", tmp_path / "events.json")

    prior = {"holdings": [_holding("ANET", "fidelity_rollover_ira", 200, 35274.0)]}
    current = {"holdings": [_holding("ANET", "schwab_rollover_ira", 200)]}
    out = mod.process_holdings_change(prior, current, sync_source="test", apply=True)
    assert out["events"] == 1
    tagged = out["holdings_doc"]
    row = next(h for h in tagged["holdings"] if h["symbol"] == "ANET")
    assert row.get("transfer_history_tag", {}).get("from_account") == "fidelity_rollover_ira"
    assert row["cost_basis_source"] == "auto_transfer_history"
    assert abs(row["cost_basis"] - 35274.0) < 1.0


def test_skips_duplicate_override(tmp_path, monkeypatch):
    mod = _load()
    ov_path = tmp_path / "overrides.json"
    ov_path.write_text('{"overrides":[{"account":"schwab_rollover_ira","symbol":"V","per_share_basis":43}],'
                       '"candidate_mappings_needing_confirmation":[]}')
    monkeypatch.setattr(mod, "OVERRIDES_PATH", ov_path)
    monkeypatch.setattr(mod, "EVENTS_PATH", tmp_path / "events.json")

    events = [{
        "id": "xfer-test", "symbol": "V", "from_account": "fidelity_rollover_ira",
        "to_account": "schwab_rollover_ira", "shares": 100, "per_share_basis": 43.0,
        "confidence": "high", "status": "auto_tagged", "basis_source": "snaptrade",
        "share_match_pct": 100.0,
    }]
    out = mod.apply_transfer_events(events, apply=True)
    assert out["applied_overrides"] == 0