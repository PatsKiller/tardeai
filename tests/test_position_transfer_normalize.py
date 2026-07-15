#!/usr/bin/env python3
"""Tests for transfer-aware position normalization (rollover / Roth ladder)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
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


def test_classify_fidelity_to_schwab():
    mod = _load("ptn", "scripts/lib/position_transfer_normalize.py")
    assert mod.classify_transfer_type("fidelity_rollover_ira", "schwab_rollover_ira") == "fidelity_to_schwab"
    assert "Fidelity" in mod.transfer_display_note("fidelity_to_schwab")


def test_classify_roth_ladder():
    mod = _load("ptn", "scripts/lib/position_transfer_normalize.py")
    assert mod.classify_transfer_type("schwab_rollover_ira", "schwab_roth") == "traditional_to_roth"
    note = mod.transfer_display_note("traditional_to_roth")
    assert "Roth" in note
    assert "carried forward" in note


def test_annotate_holding_sets_provenance():
    mod = _load("ptn", "scripts/lib/position_transfer_normalize.py")
    h = _holding("SCHG", "schwab_rollover_ira", 1700, basis_partial=True)
    ev = {
        "id": "xfer-test-SCHG",
        "from_account": "fidelity_rollover_ira",
        "to_account": "schwab_rollover_ira",
        "shares": 1700,
        "per_share_basis": 30.81,
        "total_basis": 52377.0,
        "basis_source": "snaptrade",
        "confidence": "high",
        "status": "auto_normalized",
        "detected_at": "2026-07-15T12:00:00+00:00",
    }
    mod.annotate_holding_row(h, ev)
    assert h["original_source_account"] == "fidelity_rollover_ira"
    assert h["current_account"] == "schwab_rollover_ira"
    assert h["performance_adjusted"] is True
    assert h["normalized_after_transfer"] is True
    assert len(h["transfer_history"]) == 1
    assert h["transfer_history"][0]["transfer_type"] == "fidelity_to_schwab"
    assert h["cost_basis_source"] == "auto_transfer_history"
    assert abs(h["cost_basis"] - 1700 * 30.81) < 1.0
    assert "Fidelity" in (h.get("transfer_display_note") or "")


def test_normalize_holdings_for_events_without_db(monkeypatch):
    """Normalize path works even if DB persistence is disabled."""
    mod = _load("ptn", "scripts/lib/position_transfer_normalize.py")
    doc = {"holdings": [
        _holding("JEPQ", "schwab_rollover_ira", 500, cost_basis=None, basis_partial=True),
    ]}
    events = [{
        "id": "xfer-jepq",
        "symbol": "JEPQ",
        "from_account": "fidelity_rollover_ira",
        "to_account": "schwab_rollover_ira",
        "shares": 500,
        "per_share_basis": 55.0,
        "total_basis": 27500.0,
        "basis_source": "snaptrade",
        "confidence": "high",
        "status": "auto_tagged",
        "detected_at": "2026-07-15T12:00:00+00:00",
    }]
    result = mod.normalize_holdings_for_events(doc, events, persist_db=False)
    assert result["normalized"] == 1
    h = doc["holdings"][0]
    assert h["original_source_account"] == "fidelity_rollover_ira"
    assert h["normalized_after_transfer"] is True


def test_end_to_end_detect_via_cost_basis_transfer(tmp_path, monkeypatch):
    cbt = _load("cbt", "scripts/lib/cost_basis_transfer.py")
    # Point JSON event store at tmp
    monkeypatch.setattr(cbt, "EVENTS_PATH", tmp_path / "events.json")
    monkeypatch.setattr(cbt, "OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(cbt, "FIDELITY_BASIS_PATH", tmp_path / "missing.json")

    prior = {"holdings": [
        _holding("SCHG", "fidelity_rollover_ira", 1000, 30000.0),
    ]}
    current = {"holdings": [
        _holding("SCHG", "schwab_rollover_ira", 1000, basis_partial=True,
                 cost_basis_source="partial_transfer_in"),
    ]}
    # process_holdings_change may call DB; disable via normalize path exception → fallback
    # Force fallback by making process_and_normalize fail
    import lib.position_transfer_normalize as ptn  # type: ignore

    def _boom(*a, **k):
        raise RuntimeError("no db in unit test")

    monkeypatch.setattr(ptn, "process_and_normalize", _boom, raising=False)
    # Direct detect + annotate without full process
    events = cbt.detect_transfers(prior, current)
    assert len(events) == 1
    assert events[0]["from_account"] == "fidelity_rollover_ira"
    tagged = cbt.tag_holdings_with_transfers(current, events)
    # Manual annotate as fallback path does
    ptn_mod = _load("ptn2", "scripts/lib/position_transfer_normalize.py")
    for h in tagged["holdings"]:
        ptn_mod.annotate_holding_row(h, {**events[0], "status": "auto_normalized"})
    assert tagged["holdings"][0]["original_source_account"] == "fidelity_rollover_ira"
